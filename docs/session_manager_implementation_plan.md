# Coordinator Session Manager Implementation Plan

## 1. 背景与目标

当前 coordinator 的主要入口是单轮调用：

```powershell
python -m agents.coordinator_agent.run --query "..."
python misc\har\capture_coordinator_har.py --query "..." --har-out misc\har\xxx.har
```

这两种方式都能完成一次 Agent 编排，但没有会话级记忆，也不适合像网页聊天一样持续交互。本方案目标是在不破坏现有单轮 CLI 的前提下，新增一个正式的 session manager，使系统支持：

- 新建会话、列出会话、选择会话继续提问。
- 每轮自动保存用户问题、最终回答、中间 Agent trace、关键 state 摘要。
- 后续问题能利用前文上下文，尤其能处理“那这个品类在 SP 州如何？”这类指代问题。
- 输出可展示给用户的 Agent 执行过程：哪个 Agent 做了什么、关键文本/结果是什么。
- 保留 HAR 捕获能力，但把它定位为调试/审计工具，而不是 session manager 的核心存储机制。

## 2. 非目标

- 不展示模型隐藏推理链或 chain-of-thought。
- 不把完整历史无限塞进每次 LLM prompt。
- 第一阶段不实现完整 Web UI，仅提供可被 Web/SSE 复用的结构化事件与 CLI。
- 不重写现有 SQL/NLP/Viz/Decision Agent 的核心业务逻辑。

## 3. 总体设计

新增一层会话编排：

```text
用户输入
  -> session manager 读取 session
  -> memory/context builder 生成上下文
  -> question rewriter 将当前问题改写为独立 BI 问题
  -> coordinator graph 执行本轮
  -> trace collector 收集中间事件
  -> session store 保存 turn/state 摘要
  -> CLI/Web 输出 final_answer + trace_events
```

现有 coordinator graph 仍负责单轮多 Agent 编排。session manager 只处理“多轮上下文”和“持久化”。

## 4. 推荐新增文件

| 文件 | 用途 |
|------|------|
| `agents/coordinator_agent/session_manager.py` | 会话主服务：创建/加载/运行一轮/保存 |
| `agents/coordinator_agent/session_store.py` | 本地 JSON session 读写、列表、元数据更新 |
| `agents/coordinator_agent/memory.py` | 历史裁剪、摘要生成、指代上下文构造 |
| `agents/coordinator_agent/question_rewriter.py` | 将当前问题 + 历史摘要改写成独立问题 |
| `agents/coordinator_agent/tracing.py` | 标准化 trace event、从工具 payload/state 提取关键文本 |
| `agents/coordinator_agent/run_session.py` | 多轮 CLI 入口 |
| `config/coordinator_agent/rewrite_followup_query.md` | 指代/追问改写提示词 |
| `config/coordinator_agent/summarize_session_memory.md` | 会话摘要提示词，可先规则兜底 |
| `docs/session_manager_implementation_plan.md` | 本方案文档 |

可选后续文件：

| 文件 | 用途 |
|------|------|
| `agents/coordinator_agent/web_events.py` | SSE/WebSocket 事件转换 |
| `agents/coordinator_agent/har_capture.py` | 从 `misc/har/capture_coordinator_har.py` 抽取正式 HAR 捕获工具 |

## 5. Session 数据结构

建议第一阶段使用本地 JSON 文件，目录为 `runtime/sessions/`。实施时同步在 `.gitignore` 增加：

```gitignore
/runtime/
```

单个 session 文件示例：

```json
{
  "session_id": "20260604-153012-casa-conforto",
  "title": "casa_conforto 口碑与入行前景",
  "created_at": "2026-06-04T15:30:12+08:00",
  "updated_at": "2026-06-04T15:42:01+08:00",
  "memory_summary": "用户关注 casa_conforto 类产品的评价、销量与进入前景...",
  "turns": [
    {
      "turn_id": 1,
      "created_at": "2026-06-04T15:30:12+08:00",
      "user_query": "人们对 casa_conforto 类产品的评价如何？入行此类产品是否有前景？",
      "standalone_query": "分析 Olist 中 casa_conforto 类产品的评论口碑、销售表现，并判断新卖家进入该类目的前景。",
      "final_answer": "...",
      "trace_events": [],
      "state_summary": {
        "intent": "prescriptive",
        "sub_questions": [],
        "suggested_agents": [],
        "warnings": []
      }
    }
  ]
}
```

字段说明：

- `user_query`：用户原始输入，必须完整保存。
- `standalone_query`：用于本轮 coordinator 执行的改写后问题。
- `memory_summary`：跨轮压缩记忆，避免 prompt 过长。
- `trace_events`：用于 CLI/Web 展示过程。
- `state_summary`：只保存关键 state，完整 state 可选保存到调试文件，不默认长期保存。

## 6. Trace Event 结构

不展示隐藏推理，只展示可审计的 Agent 过程。

```json
{
  "event_id": "turn-2-004",
  "turn_id": 2,
  "agent": "data_analysis_agent",
  "step": "generate_sql_tool",
  "kind": "tool_result",
  "title": "SQL 生成完成",
  "summary": "生成 1 条查询，用于统计 casa_conforto 在 SP 州的销售额与评分。",
  "payload_preview": "{...前 1200 字...}",
  "created_at": "2026-06-04T15:38:20+08:00"
}
```

推荐 `agent` 枚举：

- `coordinator_agent`
- `data_analysis_agent`
- `visualization_agent`
- `nlp_agent`
- `decision_agent`
- `session_manager`

推荐 `kind` 枚举：

- `session`
- `planning`
- `routing`
- `tool_result`
- `agent_result`
- `final_answer`
- `warning`

## 7. 多轮记忆策略

每次运行前构造上下文：

```text
memory_summary
最近 N 轮 user_query/final_answer 摘要
当前 user_query
```

然后做问题改写：

```text
输入：
  - 会话摘要
  - 最近 3 轮问答
  - 当前问题
输出：
  - standalone_query
  - rewrite_reason
  - referenced_context
```

例子：

```text
历史：用户正在分析 casa_conforto 类产品口碑与入行前景。
当前：那 SP 州呢？
改写：分析 Olist 数据中 casa_conforto 类产品在 SP 州的销售表现、评论口碑与进入前景。
```

如果 LLM 改写失败，规则兜底：

- 当前问题包含“那/这个/它/继续/上面/刚才”等指代词时，将最近一轮主题拼接进问题。
- 当前问题已经完整明确时，直接使用原文。

## 8. Coordinator 接入点

需要扩展 [agents/coordinator_agent/graph.py](../agents/coordinator_agent/graph.py)：

```python
def run_coordinator(
    user_query: str,
    *,
    conversation_history: list[dict[str, str]] | None = None,
    trace_collector: TraceCollector | None = None,
    ...
) -> dict[str, Any]:
    initial: AgentState = {
        "user_query": user_query,
        "question": user_query,
        "conversation_history": conversation_history or [],
    }
    ...
```

同时在关键节点补 trace：

- `decompose_node`：记录 intent、sub_questions、suggested_agents。
- `orchestrator_node`：记录每次路由 next_agent 与 reasoning。
- `data_analysis_node`：通过已有 `on_tool_end` 记录 SQL 工具结果。
- `nlp_node`：传入 `on_tool_end`，记录评论洞察摘要。
- `visualization_node`：通过已有 `on_tool_end` 记录图表规划/生成结果。
- `decision_node`：记录 decision_result 的 narrative/action_plan 摘要。
- `synthesize_node`：记录 final_answer 摘要。

注意：已有 `run_coordinator(query)` 调用方式必须保持兼容。

## 9. CLI 行为设计

新增入口：

```powershell
python -m agents.coordinator_agent.run_session --new --query "..."
python -m agents.coordinator_agent.run_session --session-id 20260604-153012-casa-conforto --query "那 SP 州呢？"
python -m agents.coordinator_agent.run_session --list
python -m agents.coordinator_agent.run_session --show 20260604-153012-casa-conforto
```

交互模式：

```powershell
python -m agents.coordinator_agent.run_session --session-id 20260604-153012-casa-conforto --interactive
```

输出格式默认：

```text
Session: 20260604-153012-casa-conforto
Turn: 2

===== Agent 过程 =====
[coordinator_agent/decompose] 识别为 prescriptive，拆分 2 个子问题...
[data_analysis_agent/rewrite_to_query_tool] 已生成结构化查询计划...
[data_analysis_agent/execute_sql_tool] 查询成功，返回 12 行...
[decision_agent/compose_final_answer] 形成进入建议...

===== 最终回答 =====
...
```

可选参数：

| 参数 | 行为 |
|------|------|
| `--new` | 新建 session |
| `--session-id` | 继续指定 session |
| `--query` | 单轮输入 |
| `--interactive` | 循环输入直到 `exit` |
| `--list` | 列出 session |
| `--show` | 展示某 session 元数据与历史 |
| `--trace-json` | 输出 trace JSON，便于 Web 端消费 |
| `--har-out` | 可选捕获本轮 HAR |
| `--full-state` | 调试时保存/输出完整 state |
| `--no-llm-plan` | 透传 coordinator 原参数 |
| `--no-llm-viz` | 透传 coordinator 原参数 |
| `--no-llm-synthesize` | 透传 coordinator 原参数 |

## 10. HAR 捕获集成

`misc/har/capture_coordinator_har.py` 的价值是捕获 HTTP 请求与响应，并通过 prompt 关键词推断 Agent 阶段。正式实现时：

- 保留该脚本用于离线调试。
- 抽取 `install_httpx_har_capture()` 到正式模块，供 `run_session --har-out` 可选调用。
- session manager 不依赖 HAR 文件恢复会话，因为 HAR 只代表外部 HTTP 流量，不是完整业务状态。
- HAR entry 的 `_agentic_bi` 可以与 `trace_events` 对齐，但二者用途不同：
  - `trace_events`：用户可见过程与 Web 展示。
  - `HAR`：调试、审计、复现 LLM HTTP 请求。

## 11. 实施阶段

### Phase 1: 可用的本地多轮 CLI

- 新增 `session_store.py`，支持 create/load/save/list。
- 新增 `session_manager.py`，支持 run one turn。
- 新增 `run_session.py`，支持 `--new`、`--session-id`、`--query`、`--list`。
- 扩展 `run_coordinator()` 支持 `conversation_history` 参数。
- 每轮保存 `user_query`、`standalone_query`、`final_answer`、`state_summary`。
- 暂时用规则方式生成 `standalone_query`，LLM 改写可在 Phase 2。

验收：

```powershell
python -m agents.coordinator_agent.run_session --new --query "人们对 casa_conforto 类产品的评价如何？入行此类产品是否有前景？"
python -m agents.coordinator_agent.run_session --session-id <id> --query "那 SP 州呢？"
python -m agents.coordinator_agent.run_session --list
```

第二轮 session 文件中应出现两条 turns，第二轮 `standalone_query` 应包含第一轮主题。

### Phase 2: 标准 trace events

- 新增 `tracing.py`。
- 将 coordinator 的 `on_tool_end` 统一包装为 trace event。
- 在 decompose/orchestrator/synthesize 记录节点级事件。
- CLI 默认展示 trace 文本，`--trace-json` 输出完整事件 JSON。
- NLP 节点接入 `on_tool_end`，避免评论洞察过程缺失。

验收：

- 一次完整问题至少输出 coordinator、data_analysis、synthesize 的 trace。
- 评论类问题包含 nlp trace。
- 决策类问题包含 decision trace。

### Phase 3: LLM 追问改写与记忆摘要

- 新增 `question_rewriter.py` 与 prompt。
- 新增 `memory.py`，维护 `memory_summary`。
- 当历史轮次超过阈值时，滚动更新摘要。
- coordinator synthesize evidence 中加入简短 `conversation_history` 或 `memory_summary`，让最终回答知道用户连续目标。

验收：

- “那 SP 州呢？”、“继续看差评原因”、“如果我要进入这个品类呢？”可以被改写成独立问题。
- session 文件不会因多轮对话无限膨胀到不可用。

### Phase 4: HAR 可选集成

- 抽取 HAR 捕获工具到正式模块。
- `run_session --har-out runtime/har/<session_id>_<turn_id>.har` 可用。
- HAR 的 Agent 标签与 trace event 尽量一致。

验收：

- 开启 `--har-out` 后，session 正常保存，同时生成 HAR。
- 不开启 HAR 时，session manager 行为不受影响。

### Phase 5: Web/API 预留

- 将 `SessionManager.run_turn()` 设计为返回结构化对象：

```python
{
    "session_id": "...",
    "turn_id": 2,
    "standalone_query": "...",
    "trace_events": [...],
    "final_answer": "...",
}
```

- Web 端可直接把 trace events 转为 SSE/WebSocket 消息。
- 如果后续接 FastAPI，只需要包一层 HTTP handler，不需要改 coordinator 业务逻辑。

## 12. 测试计划

单元测试：

- `session_store` 创建、加载、覆盖保存、列表排序。
- `memory` 裁剪最近 N 轮。
- `question_rewriter` 规则兜底。
- `tracing` payload preview 截断与 JSON 解析。

集成测试：

- 使用 `--no-llm-plan --no-llm-viz --no-llm-synthesize` 跑快速多轮 smoke test。
- 检查第二轮确实读取第一轮 session。
- 检查 trace event 数量和关键 agent 字段。

回归测试：

```powershell
pytest agents/coordinator_agent/tests/ -q
pytest agents/decision_agent/tests/ -q
```

CLI smoke：

```powershell
python -m agents.coordinator_agent.run --query "2017年哪个州的销售额最高？" --no-llm-plan --no-llm-synthesize
python -m agents.coordinator_agent.run_session --new --query "2017年哪个州的销售额最高？" --no-llm-plan --no-llm-synthesize
```

## 13. 风险与处理

| 风险 | 处理 |
|------|------|
| 追问太短，SQL Agent 无法理解 | 先做 standalone query rewrite，再进 coordinator |
| 历史过长导致 prompt 变大 | 保存完整 turns，但 prompt 只用摘要 + 最近 N 轮 |
| trace 泄露技术噪声 | `payload_preview` 截断，只展示摘要；完整 payload 仅调试模式输出 |
| HAR monkey patch 影响运行 | HAR 只在显式 `--har-out` 时安装 |
| 旧 CLI 被破坏 | `run_coordinator(query)` 和 `run.py --query` 保持兼容 |
| session 文件进入 git | 增加 `/runtime/` 到 `.gitignore` |

## 14. 实施检查清单

- [ ] 增加 `/runtime/` gitignore。
- [ ] 新增 session 数据模型与本地 store。
- [ ] 新增 session manager 服务。
- [ ] 扩展 `run_coordinator()` 注入 conversation history。
- [ ] 新增 `run_session.py` CLI。
- [ ] 保存每轮 turn 与 state summary。
- [ ] 实现规则版 standalone query rewrite。
- [ ] 新增 trace event collector。
- [ ] 接入 SQL/NLP/Viz/Decision/Coordinator 关键事件。
- [ ] 实现 LLM 版 follow-up rewrite。
- [ ] 实现滚动 memory summary。
- [ ] 可选接入 HAR 捕获。
- [ ] 补充 tests 与 README 使用说明。

## 15. 推荐优先级

第一轮实施只做 Phase 1 + Phase 2 的核心部分，即“能多轮、能保存、能展示过程”。  
等 CLI 稳定后，再做 LLM 追问改写与 HAR 抽取。这样可以最快验证真实用户体验，同时避免把 HAR、Web、记忆摘要一次性耦合到一起。
