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

What-if 不再以固定业务场景作为主入口。当前流程是：

1. `plan_what_if` 先判断用户是否提出反事实问题，并用结构化 `WhatIfPlan` 表达干预对象、目标指标、变化假设和缺失输入。
2. `run_what_if` 只执行计划中明确给出的安全计算，不从常识猜测 GMV 弹性、转化率、投入产出比等业务参数。
3. 若缺少 baseline、change 或业务弹性，返回 `status="missing_inputs"` 或 `status="directional_only"`，不会用 0 或经验值伪造模拟。

当前通用计算支持：

- `add`：`simulated = baseline + change`
- `subtract`：`simulated = baseline - change`
- `multiply`：`simulated = baseline * change`
- `percent_change`：`simulated = baseline * (1 + change)`
- `percentage_point_change`：`simulated = baseline + change`

示例：

- “如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？”可以规划为 `percent_change`，输出定量 `baseline_metrics`、`simulated_metrics` 和 `delta_metrics`。
- “如果差评率降低 5 个百分点，销售额会怎样？”若缺少差评率到 GMV 的弹性，会返回 `missing_inputs`。
- “如果加大 SP 州运营投入会怎样？”若缺少投入金额、转化提升或履约容量假设，会返回方向性说明或缺口说明。

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
