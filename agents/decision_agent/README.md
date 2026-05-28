# Decision Agent

## 对外入口

当前提供四层接口，按推荐顺序如下：

1. `answer_decision(...) -> str`
2. `run_decision(...) -> DecisionResult`
3. `run_decision_state(state) -> state`
4. `decision_node(state) -> state`

对应定位：

- 默认业务调用：`answer_decision(...)`
- 结构化结果消费：`run_decision(...)`
- 显式兼容层：`run_decision_state(...)`
- LangGraph / 协调器接入：`decision_node(...)` 或 `build_decision_node(...)`

补充：

- `run_decision_state(state) -> state` 是显式兼容函数
- `DecisionAgent` 类仅保留为向后兼容壳，不再建议作为新代码入口

## 推荐调用方式

### 1. 最简字符串接口

```python
from agents.decision_agent import answer_decision

answer = answer_decision(
    user_query="哪些方面需要优先优化？",
    analysis_result={...},
    nlp_result={...},
    forecast_result={...},
    visualization_result={...},
)
print(answer)
```

适用场景：

- 只关心最终建议文本
- 不希望理解 state 结构
- 简单脚本 / demo / 后端接口

### 2. 结构化接口

```python
from agents.decision_agent import DecisionInputs, run_decision

inputs = DecisionInputs(
    user_query="哪些方面需要优先优化？",
    intent="prescriptive",
    analysis_result={...},
    nlp_result={...},
    forecast_result={...},
    visualization_result={...},
)
result = run_decision(inputs)
print(result.narrative_answer)
print(result.action_plan)
```

适用场景：

- 测试
- 前端卡片化展示
- 保存结构化决策结果

### 3. LangGraph / 协调器兼容接口

```python
from agents.decision_agent.langgraph_node import build_decision_node

decision_node = build_decision_node()
next_state = decision_node(state)
print(next_state["decision_result"])
print(next_state["final_answer"])
```

说明：

- `state -> state` 只是兼容层
- 核心逻辑已不围绕 `BIState` 设计

## 输入

核心输入模型为 `DecisionInputs`，定义见 [schemas.py](./schemas.py)。

主要字段：

- `user_query`
- `intent`
- `analysis_result`
- `nlp_result`
- `forecast_result`
- `visualization_result`
- `conversation_history`

### 最小输入示例

```python
inputs = {
    "user_query": "哪些方面需要优先优化？",
    "analysis_result": {
        "summary_text": "...",
        "kpis": {
            "on_time_rate": 0.74,
            "avg_delivery_days": 9.6
        },
        "findings": [
            {
                "topic": "delivery",
                "metric": "on_time_rate",
                "scope": "northeast_region",
                "value": 0.74,
                "benchmark": 0.84,
                "gap": -0.10,
                "evidence": "东北部准时率显著低于全国平均。"
            }
        ],
        "tables": []
    }
}
```

## 上游接入要求

`decision_agent` 核心逻辑依赖“标准化上游结果”，不依赖某个 Agent 的私有原始 JSON。

当前 state 兼容适配见 [adapters.py](./adapters.py)，可消费：

- `analysis_result` / `analysis_summary`
- `nlp_result` / `review_insights`
- `forecast_result` / `forecast_summary`
- `visualization_result` / `chart_result`
- `what_if_result`

建议：

- 普通调用方直接提供标准化后的 `DecisionInputs`
- 只有协调器/历史兼容路径才走 `state` 适配

## 输出

结构定义见 [schemas.py](./schemas.py) 中的 `DecisionResult`。

核心字段：

- `decision_theme`
- `problem_statement`
- `key_findings`
- `root_causes`
- `action_plan`
- `what_if_result`
- `risks`
- `assumptions`
- `narrative_answer`

说明：

- `answer_decision(...)` 只返回 `narrative_answer`
- `warnings` 不属于默认主输出，只在 `state` 兼容层中保留

## CLI

```bash
python -m agents.decision_agent.run --fixture agents/decision_agent/tests/fixtures/high_delivery_risk.json
python -m agents.decision_agent.run --fixture agents/decision_agent/tests/fixtures/high_delivery_risk.json --mode result
python -m agents.decision_agent.run --fixture agents/decision_agent/tests/fixtures/high_delivery_risk.json --mode state
```

模式说明：

- `answer`: 输出字符串回答
- `result`: 输出结构化 `DecisionResult`
- `state`: 输出兼容层写回后的 state

默认模式：

- 不传 `--mode` 时，默认走 `answer`

## 测试

当前测试位于 [tests/](./tests)。

覆盖内容包括：

- adapter 测试
- 证据包测试
- 结构化接口测试
- state 兼容层测试
- smoke 测试

运行方式：

```bash
python -m pytest -q agents/decision_agent/tests
```

## 当前边界

1. `visualization_result` 当前只消费结构化摘要，不消费图片内容。
2. What-if 目前支持两个场景：
   - `remove_top_bad_sellers`
   - `improve_delivery_days`
3. 原始业务表仍不由 `decision_agent` 直接访问。
