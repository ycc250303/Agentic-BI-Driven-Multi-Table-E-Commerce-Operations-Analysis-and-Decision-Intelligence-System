"""使用 SQLGlot 对候选 SQL 做只读、白名单与查询预算校验。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import sqlglot
import yaml
from pydantic import Field
from sqlglot import expressions as exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from agentic_bi.core.models import StrictModel


class SqlPolicy(StrictModel):
    """SQL 策略配置。

    - dialect：SQL 方言，默认 mysql
    - maximum_sql_characters：SQL 字符上限
    - default_max_estimated_rows：未单独配置来源时的估算扫描上限
    - source_max_estimated_rows：按数据源覆盖的估算扫描上限
    - allowed_functions：允许的函数；为空表示不按白名单限制
    - denied_functions：禁止的函数
    """

    dialect: str = Field(default="mysql", min_length=1)
    maximum_sql_characters: int = Field(default=30_000, ge=100)
    default_max_estimated_rows: int = Field(default=500_000, ge=1)
    source_max_estimated_rows: dict[str, int] = Field(default_factory=dict)
    allowed_functions: tuple[str, ...] = ()
    denied_functions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    """通过静态校验后的 SQL。

    - sql：规范化后的单条查询
    - sources：实际访问的数据源
    """

    sql: str
    sources: tuple[str, ...]


class SqlPolicyViolation(StrEnum):
    """SQL 静态校验与查询预算检查使用的稳定失败分类。

    这些值用于错误响应、SQL 修复反馈和测试断言。枚举值保持稳定，面向用户的错误说明
    由 ``SqlPolicyError`` 单独携带。

    - EMPTY_SQL：候选 SQL 去除首尾空白后没有内容
    - SQL_TOO_LONG：候选 SQL 超过策略配置的字符数上限
    - PARSE_ERROR：SQLGlot 无法按配置方言解析候选 SQL
    - MULTIPLE_STATEMENTS：候选内容包含多条 SQL 语句
    - NON_READ_ONLY：根语句不是 SELECT 或 WITH 查询
    - BLOCKED_EXPRESSION：查询包含写入、DDL、锁或 SELECT INTO 等禁止表达式
    - DENIED_FUNCTION：查询调用策略明确禁止的函数
    - UNSUPPORTED_FUNCTION：查询调用函数允许列表以外的函数
    - CROSS_DATABASE_ACCESS：查询使用数据库名或目录名限定数据源
    - UNKNOWN_SOURCE：查询访问当前分析任务没有授权的数据源
    - MISSING_SOURCE：查询没有访问任何当前分析任务允许的数据源
    - UNKNOWN_QUALIFIER：列使用的表别名或派生数据源别名无法解析
    - UNKNOWN_COLUMN：列不属于对应物理来源，或未由 CTE、子查询输出
    - AMBIGUOUS_COLUMN：无限定符列同时存在于多个当前数据源
    - SELECT_STAR：查询使用普通星号选择；COUNT(*) 不属于此类
    - INVALID_LIMIT：LIMIT 不是大于零的整数常量
    - QUERY_BUDGET_EXCEEDED：EXPLAIN 估算扫描行数超过来源对应预算
    """

    EMPTY_SQL = "empty_sql"
    SQL_TOO_LONG = "sql_too_long"
    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NON_READ_ONLY = "non_read_only"
    BLOCKED_EXPRESSION = "blocked_expression"
    DENIED_FUNCTION = "denied_function"
    UNSUPPORTED_FUNCTION = "unsupported_function"
    CROSS_DATABASE_ACCESS = "cross_database_access"
    UNKNOWN_SOURCE = "unknown_source"
    MISSING_SOURCE = "missing_source"
    UNKNOWN_QUALIFIER = "unknown_qualifier"
    UNKNOWN_COLUMN = "unknown_column"
    AMBIGUOUS_COLUMN = "ambiguous_column"
    SELECT_STAR = "select_star"
    INVALID_LIMIT = "invalid_limit"
    QUERY_BUDGET_EXCEEDED = "query_budget_exceeded"


class SqlPolicyError(ValueError):
    """可安全返回给修复节点的 SQL 策略错误。

    - violation：稳定失败分类
    - retryable：修复节点可否据此再生成一次
    - context：来源、列和允许值等安全修复信息
    """

    def __init__(
        self,
        message: str,
        *,
        violation: SqlPolicyViolation,
        retryable: bool,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.violation = violation
        self.retryable = retryable
        self.context = dict(context or {})

    def repair_feedback(self) -> str:
        """返回不含 SQL 全文的结构化修复说明。"""
        fields = [f"error_code={self.violation.value}", f"message={self}"]
        fields.extend(f"{key}={value}" for key, value in sorted(self.context.items()))
        return "；".join(fields)


def load_sql_policy(path: Path) -> SqlPolicy:
    """读取并校验 SQL 策略。

    输入：
    - path：sql_policy.yaml 路径

    输出：
    - SQL 策略：文件不存在时抛 ``FileNotFoundError``；根节点不是对象时抛 ``ValueError``
    """
    if not path.is_file():
        raise FileNotFoundError(f"SQL 策略不存在: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("SQL 策略根节点必须是对象")
    return SqlPolicy.model_validate(raw)


class SqlGuard:
    """校验单条只读查询并附加硬结果上限。"""

    _BLOCKED_EXPRESSIONS = (
        exp.Command,
        exp.Create,
        exp.Delete,
        exp.Drop,
        exp.Insert,
        exp.Into,
        exp.Lock,
        exp.Update,
    )

    def __init__(self, policy: SqlPolicy) -> None:
        """保存策略，并把函数名规范为小写后比较。

        输入：
        - policy：已校验的 SQL 策略

        输出：
        - 无
        """
        self._policy = policy
        self._allowed_functions = {value.lower() for value in policy.allowed_functions}
        self._denied_functions = {value.lower() for value in policy.denied_functions}

    def validate(
        self,
        sql: str,
        *,
        allowed_sources: Mapping[str, Set[str]],
        maximum_rows: int,
    ) -> ValidatedSql:
        """验证候选 SQL 并返回规范化版本。

        输入：
        - sql：候选语句
        - allowed_sources：当前任务允许的数据源到列名
        - maximum_rows：结果行上限；执行时会再加一行用于判断截断

        约束：
        - 空语句、超长或无法解析：允许修复
        - 必须是单条 SELECT 或 WITH
        - 写入、DDL、锁和 SELECT INTO 直接失败，不交给模型改写
        - 规范化时去掉注释

        输出：
        - sql：去掉注释后的单条查询
        - sources：实际访问的数据源，按名称排序
        - 违反策略：抛 ``SqlPolicyError``
        """
        candidate = sql.strip()
        if not candidate:
            raise SqlPolicyError(
                "SQL 不能为空",
                violation=SqlPolicyViolation.EMPTY_SQL,
                retryable=True,
            )
        if len(candidate) > self._policy.maximum_sql_characters:
            raise SqlPolicyError(
                "SQL 长度超过策略上限",
                violation=SqlPolicyViolation.SQL_TOO_LONG,
                retryable=True,
            )

        try:
            statements = [
                statement
                for statement in sqlglot.parse(
                    candidate,
                    read=self._policy.dialect,
                )
                if statement is not None
            ]
        except ParseError as exc:
            raise SqlPolicyError(
                "SQL 无法解析为合法 MySQL",
                violation=SqlPolicyViolation.PARSE_ERROR,
                retryable=True,
            ) from exc

        if len(statements) != 1:
            raise SqlPolicyError(
                "只能生成一条 SQL",
                violation=SqlPolicyViolation.MULTIPLE_STATEMENTS,
                retryable=False,
            )

        statement = statements[0]
        if not isinstance(statement, exp.Query):
            raise SqlPolicyError(
                "只允许 SELECT 或 WITH 查询",
                violation=SqlPolicyViolation.NON_READ_ONLY,
                retryable=False,
            )

        blocked = statement.find(*self._BLOCKED_EXPRESSIONS)
        if blocked is not None:
            raise SqlPolicyError(
                "SQL 包含写入、DDL、锁或 SELECT INTO",
                violation=SqlPolicyViolation.BLOCKED_EXPRESSION,
                retryable=False,
            )

        self._validate_functions(statement)
        sources = self._validate_sources(
            statement,
            allowed_sources=allowed_sources,
        )
        self._validate_columns(
            statement,
            allowed_sources=allowed_sources,
        )
        self._validate_stars(statement)

        limited = self._apply_limit(statement, maximum_rows=maximum_rows)
        normalized = limited.sql(
            dialect=self._policy.dialect,
            pretty=False,
            comments=False,
        )
        return ValidatedSql(
            sql=normalized,
            sources=tuple(sorted(sources)),
        )

    def validate_plan(
        self,
        *,
        estimated_rows: int | None,
        sources: Iterable[str],
    ) -> None:
        """按来源差异校验 EXPLAIN 估算扫描量。

        输入：
        - estimated_rows：EXPLAIN 估算行数，为空则跳过
        - sources：语句访问的数据源

        约束：
        - 上限取默认值与各来源配置中的较大值

        输出：
        - 无：超过预算时抛 ``SqlPolicyError``，且允许修复
        """
        if estimated_rows is None:
            return

        maximum = self._policy.default_max_estimated_rows
        for source in sources:
            maximum = max(
                maximum,
                self._policy.source_max_estimated_rows.get(source, maximum),
            )

        if estimated_rows > maximum:
            raise SqlPolicyError(
                f"EXPLAIN 估算扫描 {estimated_rows} 行，超过预算 {maximum} 行",
                violation=SqlPolicyViolation.QUERY_BUDGET_EXCEEDED,
                retryable=True,
                context={"estimated_rows": estimated_rows, "maximum_rows": maximum},
            )

    def _validate_functions(self, statement: exp.Expression) -> None:
        """按策略检查语句中的函数调用。

        输入：
        - statement：已解析的单条查询

        约束：
        - 命中禁止函数：直接失败，不允许修复
        - 配置了允许列表时，列表外的函数允许修复后再生成
        - 允许列表为空：只拦截禁止函数
        - AND、OR、XOR 是逻辑连接，不按函数白名单检查
        - CASE WHEN 是条件表达式，不按函数白名单检查；其内部分支节点同样跳过
        - 独立的 IF 函数调用仍按白名单检查

        输出：
        - 无：违反时抛 ``SqlPolicyError``
        """
        for function in statement.find_all(exp.Func):
            if isinstance(function, exp.Connector | exp.Case):
                continue
            if isinstance(function, exp.If) and isinstance(function.parent, exp.Case):
                continue
            name = str(function.sql_name()).lower()  # type: ignore[no-untyped-call]
            if name in self._denied_functions:
                raise SqlPolicyError(
                    f"禁止调用函数 {name}",
                    violation=SqlPolicyViolation.DENIED_FUNCTION,
                    retryable=False,
                    context={"function": name},
                )
            if self._allowed_functions and name not in self._allowed_functions:
                raise SqlPolicyError(
                    f"函数 {name} 不在允许列表中",
                    violation=SqlPolicyViolation.UNSUPPORTED_FUNCTION,
                    retryable=True,
                    context={"function": name},
                )

    def _validate_sources(
        self,
        statement: exp.Expression,
        *,
        allowed_sources: Mapping[str, Set[str]],
    ) -> set[str]:
        """提取真实数据源，并拒绝库名限定和白名单外的表。

        输入：
        - statement：已解析的单条查询
        - allowed_sources：当前任务允许的数据源到列名

        约束：
        - CTE 与子查询别名不算外部数据源
        - 显式数据库或系统库直接失败，不允许修复
        - 白名单外的数据源允许模型改用当前任务的数据源
        - 没有访问任何允许的数据源时允许修复

        输出：
        - 数据源集合：实际访问的表或视图
        """
        cte_names = {
            cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
        }
        sources: set[str] = set()

        for table in statement.find_all(exp.Table):
            name = table.name.lower()
            if name in cte_names:
                continue
            if table.db or table.catalog:
                raise SqlPolicyError(
                    "不能显式访问其他数据库或系统库",
                    violation=SqlPolicyViolation.CROSS_DATABASE_ACCESS,
                    retryable=False,
                )
            if name not in allowed_sources:
                raise SqlPolicyError(
                    f"数据源 {name} 不在当前任务白名单中",
                    violation=SqlPolicyViolation.UNKNOWN_SOURCE,
                    retryable=True,
                    context={
                        "source": name,
                        "allowed_sources": sorted(allowed_sources),
                    },
                )

            sources.add(name)

        if not sources:
            raise SqlPolicyError(
                "SQL 没有访问任何允许的数据源",
                violation=SqlPolicyViolation.MISSING_SOURCE,
                retryable=True,
                context={"allowed_sources": sorted(allowed_sources)},
            )

        return sources

    def _validate_columns(
        self,
        statement: exp.Expression,
        *,
        allowed_sources: Mapping[str, Set[str]],
    ) -> None:
        """检查列是否属于当前任务允许的数据源。

        输入：
        - statement：已解析的单条查询
        - allowed_sources：当前任务允许的数据源到列名
        约束：
        - 每个查询作用域只检查该作用域实际引用的数据源
        - 派生来源只能访问其输出列
        - 无限定符列不存在时拒绝，同时命中多个来源时要求使用别名
        - ORDER BY、GROUP BY 和 HAVING 可以引用当前 SELECT 的输出别名

        输出：
        - 无：违反时抛 ``SqlPolicyError``
        """
        for scope in traverse_scope(statement):
            physical_sources, derived_sources = self._scope_sources(scope)
            selected_aliases = {
                expression.alias.lower()
                for expression in scope.expression.selects
                if expression.alias
            }

            for column in scope.columns:
                name = column.name.lower()
                qualifier = column.table.lower()

                if qualifier:
                    source = self._resolve_qualified_source(scope, qualifier)
                    if isinstance(source, exp.Table):
                        source_name = source.name.lower()
                        self._validate_source_column(
                            source_name,
                            name,
                            allowed_sources=allowed_sources,
                        )
                        continue
                    if isinstance(source, Scope):
                        self._validate_derived_column(qualifier, name, source)
                        continue
                    raise SqlPolicyError(
                        f"列 {name} 使用了未知限定符 {qualifier}",
                        violation=SqlPolicyViolation.UNKNOWN_QUALIFIER,
                        retryable=True,
                        context={"qualifier": qualifier, "column": name},
                    )

                candidates = [
                    alias
                    for alias, source_name in physical_sources.items()
                    if name in allowed_sources[source_name]
                ]
                candidates.extend(
                    alias
                    for alias, output_columns in derived_sources.items()
                    if name in output_columns
                )
                if len(candidates) == 1:
                    continue
                if len(candidates) > 1:
                    raise SqlPolicyError(
                        f"列 {name} 同时存在于多个当前数据源中，必须使用表别名限定",
                        violation=SqlPolicyViolation.AMBIGUOUS_COLUMN,
                        retryable=True,
                        context={"column": name, "candidate_qualifiers": sorted(candidates)},
                    )
                if (
                    name in selected_aliases
                    and column.find_ancestor(
                        exp.Order,
                        exp.Group,
                        exp.Having,
                    )
                    is not None
                ):
                    continue

                actual_sources = sorted(set(physical_sources.values()))
                raise SqlPolicyError(
                    f"当前数据源不包含列 {name}",
                    violation=SqlPolicyViolation.UNKNOWN_COLUMN,
                    retryable=True,
                    context={
                        "column": name,
                        "sources": actual_sources,
                        "allowed_columns": sorted(
                            {
                                column_name
                                for source_name in actual_sources
                                for column_name in allowed_sources[source_name]
                            }
                        ),
                    },
                )

    @staticmethod
    def _scope_sources(scope: Scope) -> tuple[dict[str, str], dict[str, set[str]]]:
        """返回一个查询作用域中的物理来源和派生来源输出列。"""
        physical: dict[str, str] = {}
        derived: dict[str, set[str]] = {}
        for alias, source in scope.sources.items():
            normalized_alias = alias.lower()
            if isinstance(source, exp.Table):
                physical[normalized_alias] = source.name.lower()
            elif isinstance(source, Scope):
                derived[normalized_alias] = {
                    name.lower() for name in source.expression.named_selects
                }
        return physical, derived

    @staticmethod
    def _resolve_qualified_source(scope: Scope, qualifier: str) -> exp.Table | Scope | None:
        """在当前和外层作用域解析列限定符。"""
        current: Scope | None = scope
        while current is not None:
            source = current.sources.get(qualifier)
            if isinstance(source, exp.Table | Scope):
                return source
            current = current.parent
        return None

    @staticmethod
    def _validate_source_column(
        source_name: str,
        column_name: str,
        *,
        allowed_sources: Mapping[str, Set[str]],
    ) -> None:
        """要求限定列属于其真实物理来源。"""
        if column_name in allowed_sources[source_name]:
            return
        raise SqlPolicyError(
            f"数据源 {source_name} 不包含列 {column_name}",
            violation=SqlPolicyViolation.UNKNOWN_COLUMN,
            retryable=True,
            context={
                "source": source_name,
                "column": column_name,
                "allowed_columns": sorted(allowed_sources[source_name]),
            },
        )

    @staticmethod
    def _validate_derived_column(alias: str, column_name: str, source: Scope) -> None:
        """要求 CTE 或子查询只暴露自己选择的输出列。"""
        output_columns = {name.lower() for name in source.expression.named_selects}
        if column_name in output_columns:
            return
        raise SqlPolicyError(
            f"派生数据源 {alias} 不包含列 {column_name}",
            violation=SqlPolicyViolation.UNKNOWN_COLUMN,
            retryable=True,
            context={
                "source": alias,
                "column": column_name,
                "allowed_columns": sorted(output_columns),
            },
        )

    @staticmethod
    def _validate_stars(statement: exp.Expression) -> None:
        """禁止除聚合计数以外的星号选择。

        输入：
        - statement：已解析的单条查询

        约束：
        - COUNT(*) 保留
        - 其他星号允许修复为显式字段

        输出：
        - 无：出现其他星号时抛 ``SqlPolicyError``
        """
        for star in statement.find_all(exp.Star):
            if star.find_ancestor(exp.Count) is None:
                raise SqlPolicyError(
                    "禁止 SELECT *，必须显式选择业务字段",
                    violation=SqlPolicyViolation.SELECT_STAR,
                    retryable=True,
                )

    @staticmethod
    def _apply_limit(
        statement: exp.Query,
        *,
        maximum_rows: int,
    ) -> exp.Query:
        """把结果行数限制在预算加一以内，多出的一行用于判断截断。

        输入：
        - statement：已解析的单条查询
        - maximum_rows：调用方给出的结果行上限

        约束：
        - 没有 LIMIT 时补上 maximum_rows + 1
        - LIMIT 必须是大于 0 的整数常量，否则允许修复
        - 已有 LIMIT 大于执行上限时收紧到该上限

        输出：
        - 带上限的查询：不改写语句的其他部分
        """
        execution_limit = maximum_rows + 1
        current_limit = statement.args.get("limit")

        if current_limit is None:
            return statement.limit(execution_limit)

        expression = current_limit.expression
        if not isinstance(expression, exp.Literal) or not expression.is_int:
            raise SqlPolicyError(
                "LIMIT 必须是整数常量",
                violation=SqlPolicyViolation.INVALID_LIMIT,
                retryable=True,
            )

        value = int(expression.this)
        if value < 1:
            raise SqlPolicyError(
                "LIMIT 必须大于 0",
                violation=SqlPolicyViolation.INVALID_LIMIT,
                retryable=True,
            )
        if value > execution_limit:
            return statement.limit(execution_limit)

        return statement
