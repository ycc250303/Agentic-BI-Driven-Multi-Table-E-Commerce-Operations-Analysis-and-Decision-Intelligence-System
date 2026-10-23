# 数据分析 Agent 测试复现

以下命令均在仓库根目录执行。

## 前置配置

在根目录 `.env` 中配置模型 API Key 和 MySQL 只读账号：

```dotenv
AGENTIC_BI_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<DeepSeek API Key>

AGENTIC_BI_DB_HOST=127.0.0.1
AGENTIC_BI_DB_PORT=3306
AGENTIC_BI_DB_NAME=olist
AGENTIC_BI_DB_READONLY_USER=agent_reader
AGENTIC_BI_DB_READONLY_PASSWORD=<只读账号密码>
```

需要查看 LangSmith Trace 时增加：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<LangSmith API Key>
LANGSMITH_PROJECT=agentic-bi-analysis-dev
```

不要提交 `.env`、密码或 API Key。

## 1. 静态检查与单元测试

```bash
pip install -e '.[dev]'
ruff check src tests
ruff format --check src tests
mypy src
pytest tests/unit -q
```

验收结果：Ruff、格式检查和 mypy 无错误，全部单元测试通过。

生产加载入口负责 Pydantic 结构校验；Analysis 入口校验模型或调用方提供的业务语义，下游读取方法直接使用已校验标识。SQL 执行前继续检查 AST、白名单、结果列和查询预算。

## 2. 初始化数据库与只读账号

```bash
python utils/setup.py
python utils/create_readonly_user.py
```

验收结果：原始表和六个 `mv_*` 视图可查询；在线 Agent 只能使用只读账号，不能执行写入或 DDL。

## 3. 验证完整分析链路

```bash
agentic-bi-analysis \
  "2017 年哪个客户州的销售额最高？"
```

未安装命令行入口时使用：

```bash
python -m agentic_bi.agents.analysis.run \
  "2017 年哪个客户州的销售额最高？"
```

验收结果：

- 返回 `success`。
- 识别 `total_gmv`、`customer_state`、2017 年和 Top 1 排名语义。
- SQL 经过 AST、白名单、EXPLAIN 和只读执行校验。
- 返回单一 Evidence、证据引用结论和 CSV/SQL Artifact；SQL Artifact 的 `content_hash` 标识规范化 SQL 内容。
- LangSmith 中可看到 `interpret_request → generate_sql → validate_and_execute → summarize`。

## 4. 验证同粒度多指标查询

```bash
agentic-bi-analysis \
  "按月比较 GMV、订单量、客单价和运费。"
```

验收结果：一条查询返回共享月粒度的四个指标；Evidence 的 `grain` 为 `sales_month`；摘要不补充 Evidence 之外的事实。

## 5. 验证复合任务边界

```bash
agentic-bi-analysis \
  "先找 2017 年销售额最高的州，再查询该州的准时率。"
```

验收结果：返回 `needs_input` 或稳定的 `invalid_request`，不在 Analysis Agent 内自行构建有依赖的任务 DAG，也不猜测目标州。

## 6. 验证上下文缺失

```bash
agentic-bi-analysis "那 SP 州呢？"
```

验收结果：返回 `needs_input`，询问指标和时间范围，不执行 SQL，不根据示例或模型常识猜测上下文。

## 7. 验证安全与降级

```bash
pytest tests/unit/data/test_sql_guard.py -q
pytest tests/unit/data/test_database.py -q
pytest tests/unit/agents/analysis -q
```

验收结果：

- DDL、DML、多语句、系统库、危险函数和未授权数据源被直接阻止。
- 语法、未知列、结果形态和超预算等可修复错误最多重试两轮。
- 数据库或认证不可用时返回 `failed`，且不泄漏 SQL、密码或异常栈。
- 空结果返回 `success`，并明确说明没有数据。
- 结果超限时通过 `truncated=true` 表达截断状态。
- 查询成功但摘要失败时返回 `partial`，保留 Evidence 和 Artifact。
- LangSmith Trace 不包含 API Key、数据库密码或完整大结果。

上述步骤全部通过后，数据分析 Agent 才可接入 Coordinator 主链路。旧 32 题评测未实际运行前，不得声称新实现超过旧基线。
