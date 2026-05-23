# check_sql 任务完成报告

## 0. 本轮重构（结构化计划 + 语义校验）

- 新增结构化查询计划输出：`RewriteToQueryOutput.sub_questions`（含 `metric_key`、`scope`、`inherit_from`），`query_for_sql` 仅作兼容字段。
- 新增规则驱动语义校验：`agents/sql_agent/tools/validate_rewrite_plan.py` + `config/data_analysis_agent/rewrite_plan_rules.yaml`，在 `generate_sql` 前统一拦截口径漂移。
- 新增 SQL 共享规则模块：`agents/sql_agent/tools/sql_format_rules.py`，`generate/check/execute` 共用 `normalize_sql` 与格式/安全判定，避免重复实现漂移。
- 流水线改造：`run.py` 增加 `rewrite -> validate -> generate` 的重试闭环，并加入 `rewrite/generate` 异常兜底，失败反馈通过 `correction_context` 自动回注。
- 提示词与字典瘦身：`rewrite_to_query_tool.md`、`generate_sql_tool.md`、`system_core.md`、`schema_dictionary.md` 去重并修复断裂引用。
- 输出结构精简：`execute_sql_tool` 移除与 `results[]` 重复的顶层 CSV/列信息字段；`rewrite_to_query_tool` 自动省略默认值与空字段。

## 1. 交付物

- 人工基准 SQL 文件：`tasks/check_sql_reference_queries.sql`
- 全量流水线输出（7题）：`tasks/pipeline_run_output.txt`

## 2. 初始全量结果对比（基准 SQL vs run.py）

### Q1 `2017 年 GMV 是多少？按月和各州排名的趋势怎样？`
- 结论：**基本正确**。
- run.py 生成了 2 条 SQL：2017 GMV 总额 + 月-州 GMV 排序结果。
- 与基准差异：基准中额外给了“每月州排名序号”，run.py 用排序替代，业务可读性略弱但语义可接受。

### Q2 `平台整体准时交付率是多少？哪些州延迟最严重？`
- 结论：**正确**。
- run.py 正确回退 `orders` 计算全平台订单级准时率；并用 `mv_delivery_perf` 统计各州 `delayed_orders` 排名。

### Q3 `哪种支付方式最受欢迎？平均分期数是多少？`
- 结论：**正确（且优于简单平均）**。
- run.py 拆成 2 条 SQL，分别求最受欢迎支付方式（交易笔数）与按交易笔数加权的平均分期，口径合理。

### Q4 `产品的重量、尺寸与运费之间有什么关系？`
- 结论：**部分正确**。
- run.py 返回明细级样本（用于下游散点/相关分析），方向正确；
- 但未直接输出关系指标（如相关系数/分桶趋势），解释性略弱。

### Q5 `Top 10 差评品类是什么？`
- 初始结论：**不正确**。
- 问题：run.py 初始把“差评品类”改写为“平均评分最低品类”，并非“差评数量/差评率 Top 10”。

### Q6 `2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？`
- 初始结论：**不正确**。
- 问题：后两问被扩大为全平台口径，未绑定“最高销售额州”主体。

### Q7 `哪些卖家的差评率最高？`
- 结论：**部分正确**。
- SQL 逻辑能算差评率，但未设置最小样本门槛，结果前列会被少量订单卖家（如 1/1）主导，业务稳定性不足。

## 3. 根因分析与修复

为解决 Q5/Q6 错误，更新了提示词规则：

- `config/data_analysis_agent/rewrite_to_query_tool.md`
  - 新增“省略主语继承”“禁止擅自新增全平台范围词”硬约束；
  - 明确“差评品类”默认应转写为 `review_score <= 2` 的差评数量/订单数口径，而非平均评分最低。

- `config/data_analysis_agent/generate_sql_tool.md`
  - 新增“Top N 差评品类默认口径”规则；
  - 新增“跨子问题绑定”规则（先筛对象后续必须沿用对象）；
  - 新增“候选视图缺失必要维度时必须回退原始表，不得偷换成全平台”规则；
  - 新增“每条 SQL 必须以 SELECT 开头（避免 WITH 被 check_sql 拒绝）”规则。

## 4. 回归验证

### Q5 回归
- 结果：**修复成功**。
- 新 SQL 使用 `review_score <= 2`，并按差评订单数 `bad_review_orders` 降序取 Top 10。

### Q6 回归
- 结果：**修复成功**。
- 新 SQL：
  1) 用 `mv_state_sales` 找 2017 最高销售额州；
  2) 在该州范围内订单级计算准时率；
  3) 因 `mv_payment_dist` 无州维度，正确回退 `payments + orders + customers` 计算该州最受欢迎支付方式。
- 该题最终 `generate_sql_attempts = 2`：首次使用 `WITH` 被 `check_sql` 拒绝后，自动重试改为 `SELECT` 起始并通过。

## 5. run.py 是否支持“一次输入多个子问题”

- 结论：**支持**。
- 证据：Q2/Q3/Q6 都在单次输入下生成了多条 `query_sqls`（2~3 条），并被 `execute_sql_tool` 逐条执行成功。
- 你的示例“`哪种支付方式最受欢迎？平均分期数是多少？`”对应 Q3，已验证可一次性生成并执行两条 SQL。

## 6. 任务完成状态

- [x] 按要求先创建了一个 SQL 文件存储人工生成语句（`tasks/check_sql_reference_queries.sql`）
- [x] 激活 `bi` 环境并运行了 `agents/sql_agent/run.py`，记录输出（`tasks/pipeline_run_output.txt`）
- [x] 对比并判断了差异正确性
- [x] 对错误场景做了原因分析与修复（提示词优化）
- [x] 回归验证修复结果
- [x] 评估了 run.py 的多子问题生成能力
- [x] 完成结构化重构并全量复测（`tasks/pipeline_run_output.txt`）

## 7. 重构后复测摘要（最新）

- 7/7 题最终 `check_sql.syntax_ok = true` 且 `execute_sql.error_message = null`。
- 新增的 `validate_rewrite_plan_tool` 已接入主链路并生效：
  - 在最新全量回归中，Q6 已在语义校验阶段一次通过（`plan_ok=true`，`rewrite_to_query 调用次数 = 1`）。
  - 其余题目一次通过。
- Q5 现已稳定输出差评数量口径（`metric_key=bad_review_count` + `review_score <= 2`），不再漂移到“平均评分最低”。
- 多子问题生成能力保持可用：Q2/Q3/Q6 均输出多条 `query_sqls` 并被逐条执行。
