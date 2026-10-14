"""使用 SQLGlot 对候选 SQL 做只读、白名单与查询预算校验。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import sqlglot
import yaml
from pydantic import Field
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

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
    - fingerprint：规范化 SQL 的指纹
    - sources：实际访问的数据源
    """

    sql: str
    fingerprint: str
    sources: tuple[str, ...]


class SqlPolicyError(ValueError):
    """可安全返回给修复节点的 SQL 策略错误。

    - retryable：修复节点可否据此再生成一次
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


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
        - 规范化时去掉注释，指纹取规范化 SQL 的前 24 位

        输出：
        - sql：去掉注释后的单条查询
        - fingerprint：规范化 SQL 的指纹
        - sources：实际访问的数据源，按名称排序
        - 违反策略：抛 ``SqlPolicyError``
        """
        candidate = sql.strip()
        if not candidate:
            raise SqlPolicyError("SQL 不能为空", retryable=True)
        if len(candidate) > self._policy.maximum_sql_characters:
            raise SqlPolicyError("SQL 长度超过策略上限", retryable=True)

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
            raise SqlPolicyError("SQL 无法解析为合法 MySQL", retryable=True) from exc

        if len(statements) != 1:
            raise SqlPolicyError("只能生成一条 SQL", retryable=False)

        statement = statements[0]
        if not isinstance(statement, exp.Query):
            raise SqlPolicyError("只允许 SELECT 或 WITH 查询", retryable=False)

        blocked = statement.find(*self._BLOCKED_EXPRESSIONS)
        if blocked is not None:
            raise SqlPolicyError("SQL 包含写入、DDL、锁或 SELECT INTO", retryable=False)

        self._validate_functions(statement)
        sources, alias_to_source, derived_aliases = self._validate_sources(
            statement,
            allowed_sources=allowed_sources,
        )
        self._validate_columns(
            statement,
            allowed_sources=allowed_sources,
            alias_to_source=alias_to_source,
            derived_aliases=derived_aliases,
        )
        self._validate_stars(statement)

        limited = self._apply_limit(statement, maximum_rows=maximum_rows)
        normalized = limited.sql(
            dialect=self._policy.dialect,
            pretty=False,
            comments=False,
        )
        fingerprint = sha256(normalized.encode("utf-8")).hexdigest()[:24]

        return ValidatedSql(
            sql=normalized,
            fingerprint=fingerprint,
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
                retryable=True,
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

        输出：
        - 无：违反时抛 ``SqlPolicyError``
        """
        for function in statement.find_all(exp.Func):
            if isinstance(function, exp.Connector):
                continue
            name = str(function.sql_name()).lower()  # type: ignore[no-untyped-call]
            if name in self._denied_functions:
                raise SqlPolicyError(
                    f"禁止调用函数 {name}",
                    retryable=False,
                )
            if self._allowed_functions and name not in self._allowed_functions:
                raise SqlPolicyError(
                    f"函数 {name} 不在允许列表中",
                    retryable=True,
                )

    def _validate_sources(
        self,
        statement: exp.Expression,
        *,
        allowed_sources: Mapping[str, Set[str]],
    ) -> tuple[set[str], dict[str, str], set[str]]:
        """提取真实数据源，并拒绝库名限定和白名单外的表。

        输入：
        - statement：已解析的单条查询
        - allowed_sources：当前任务允许的数据源到列名

        约束：
        - CTE 与子查询别名不算外部数据源
        - 显式数据库或系统库直接失败，不允许修复
        - 白名单外的数据源直接失败，不允许修复
        - 没有访问任何允许的数据源时允许修复

        输出：
        - 数据源集合：实际访问的表或视图
        - 别名映射：表别名和表名到真实数据源
        - 派生别名：CTE 与子查询别名，后续列检查时跳过
        """
        cte_names = {
            cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
        }
        derived_aliases = set(cte_names)
        derived_aliases.update(
            subquery.alias_or_name.lower()
            for subquery in statement.find_all(exp.Subquery)
            if subquery.alias_or_name
        )

        sources: set[str] = set()
        alias_to_source: dict[str, str] = {}

        for table in statement.find_all(exp.Table):
            name = table.name.lower()
            if name in cte_names:
                continue
            if table.db or table.catalog:
                raise SqlPolicyError(
                    "不能显式访问其他数据库或系统库",
                    retryable=False,
                )
            if name not in allowed_sources:
                raise SqlPolicyError(
                    f"数据源 {name} 不在当前任务白名单中",
                    retryable=False,
                )

            sources.add(name)
            alias = (table.alias_or_name or name).lower()
            alias_to_source[alias] = name
            alias_to_source[name] = name

        if not sources:
            raise SqlPolicyError("SQL 没有访问任何允许的数据源", retryable=True)

        return sources, alias_to_source, derived_aliases

    def _validate_columns(
        self,
        statement: exp.Expression,
        *,
        allowed_sources: Mapping[str, Set[str]],
        alias_to_source: Mapping[str, str],
        derived_aliases: Set[str],
    ) -> None:
        """检查列是否属于当前任务允许的数据源。

        输入：
        - statement：已解析的单条查询
        - allowed_sources：当前任务允许的数据源到列名
        - alias_to_source：限定符到真实数据源
        - derived_aliases：CTE 与子查询别名

        约束：
        - 派生别名上的列不在这里检查
        - 未知限定符或越权列允许修复
        - 无限定符的列必须出现在白名单，或是本语句选出的别名

        输出：
        - 无：违反时抛 ``SqlPolicyError``
        """
        selectable_columns = {
            column.lower() for columns in allowed_sources.values() for column in columns
        }
        selected_aliases = {
            alias.lower()
            for select in statement.find_all(exp.Select)
            for expression in select.expressions
            if (alias := expression.alias)
        }

        for column in statement.find_all(exp.Column):
            name = column.name.lower()
            qualifier = column.table.lower()

            if qualifier in derived_aliases:
                continue

            if qualifier:
                source_name = alias_to_source.get(qualifier)
                if source_name is None:
                    raise SqlPolicyError(
                        f"列 {name} 使用了未知限定符 {qualifier}",
                        retryable=True,
                    )
                if name not in allowed_sources[source_name]:
                    raise SqlPolicyError(
                        f"数据源 {source_name} 不允许访问列 {name}",
                        retryable=True,
                    )
                continue

            if name not in selectable_columns and name not in selected_aliases:
                raise SqlPolicyError(
                    f"列 {name} 不在当前任务白名单中",
                    retryable=True,
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
            raise SqlPolicyError("LIMIT 必须是整数常量", retryable=True)

        value = int(expression.this)
        if value < 1:
            raise SqlPolicyError("LIMIT 必须大于 0", retryable=True)
        if value > execution_limit:
            return statement.limit(execution_limit)

        return statement
