# Decision Agent

Decision Agent 负责把上游 SQL / NLP / Forecast / Visualization 产出的结构化证据转化为运营决策建议。它不直接访问原始数据库，也不重新生成 SQL；所有判断都来自传入的 state 或 `DecisionInputs`。

## 职责边界

- 汇总多来源证据，构造 `EvidenceBundle`。
- 识别物流、卖家、品类、区域、预测放缓等问题，并计算优先级。
- 生成结构化 `action_plan`、`root_causes`、`what_if_result` 和最终叙述。
- 对叙述结果做质量检查，避免证据不足时给出过强结论。
- 当叙述层 LLM 失败时，返回规则层确定性摘要，避免整个链路中断。

不承担：

- 原始表查询或 SQL 生成。
- 图表渲染。
- 评论主题/情感模型训练。
- 未由上游证据支持的经营事实推断。

## 主要入口

- `run_decision(inputs, model=None)`：核心入口，输入 `DecisionInputs`，返回 `DecisionResult`。
- `answer_decision(...)`：面向调用方的字符串回答入口。
- `run_decision_state(state, model=None)`：兼容 coordinator state 的入口。
- `build_decision_node(model=None)`：LangGraph 节点包装。

CLI 示例：

```powershell
.venv\Scripts\python.exe -m agents.decision_agent.run --fixture agents\decision_agent\tests\fixtures\high_delivery_risk.json --mode result
```

## 输入输出契约

核心输入是 `DecisionInputs`：

- `user_query`：用户问题。
- `intent`：通常为 `diagnostic`、`prescriptive`、`predictive` 或 `what_if`。
- `analysis_result`：SQL/Data Analysis Agent 的结构化结果，是核心证据来源。
- `nlp_result`：评论洞察结果，可为空。
- `forecast_result`：预测结果，可为空。
- `visualization_result`：图表摘要，可为空。
- `what_if_result`：上游已运行的模拟结果，可为空。

核心输出是 `DecisionResult`：

- `decision_theme`
- `problem_statement`
- `key_findings`
- `root_causes`
- `action_plan`
- `what_if_result`
- `risks`
- `assumptions`
- `narrative_answer`
- `quality_report`

这些 schema 定义在 `schemas.py`，外部集成应优先依赖这些结构化字段，而不是解析自然语言回答。

## What-if 覆盖范围

当前内置三个场景：

- `remove_top_bad_sellers`：基于 `analysis_result.simulation_inputs.seller_quality_impact`，估计剔除 Top N 高差评卖家的评分、负面率和 GMV 变化。
- `improve_delivery_days`：基于 `analysis_result.simulation_inputs.delivery_improvement`，估计配送时长缩短后的准时率和配送负面主题占比变化。
- `improve_category_quality`：基于 `analysis_result.simulation_inputs.category_quality_impact`，估计问题品类完成质检、差评 SKU 审核和详情页修正后的负面率、差评数和可选 GMV 变化。

若缺少模拟输入，Agent 会返回 `status="missing_inputs"`，不会用 0 或默认值伪造模拟结果。

`category_quality_impact` 至少需要：

- `category`
- `baseline_negative_rate`
- `improved_negative_rate`
- `baseline_bad_review_count`
- `improved_bad_review_count`

可选提供 `baseline_gmv` 与 `projected_gmv`，用于估计 GMV 变化。

后续可扩展方向：

- 区域运营模拟：重点州履约资源加配、客服补偿策略。
- 增长策略模拟：促销、库存、卖家供给调整。

## LLM 与 fallback

`run_decision(..., model=...)` 支持注入测试模型或外部模型。叙述生成会优先使用传入模型的 `with_structured_output(NarrativeResponse)`；未传入模型时使用默认 DeepSeek 结构化模型。

如果叙述层 LLM 返回空值、非结构化结果或抛出异常，Decision Agent 会：

- 保留规则层生成的 `DecisionResult`。
- 生成一段确定性 `narrative_answer`。
- 在 `quality_report.issues` 和 `assumptions` 中说明使用了规则层兜底。

## 测试

推荐先跑 Decision Agent 自身测试：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest agents\decision_agent\tests -q --tb=short
```

快速定位模型注入和契约问题：

```powershell
.venv\Scripts\python.exe -m pytest agents\decision_agent\tests\test_service.py -q
.venv\Scripts\python.exe -m pytest agents\decision_agent\tests\test_contract.py -q
```

规则层回归：

```powershell
.venv\Scripts\python.exe -m pytest agents\decision_agent\tests\test_rules.py agents\decision_agent\tests\test_quality.py agents\decision_agent\tests\test_evidence_bundle.py agents\decision_agent\tests\test_warning_policy.py agents\decision_agent\tests\test_adapters.py -q
```
