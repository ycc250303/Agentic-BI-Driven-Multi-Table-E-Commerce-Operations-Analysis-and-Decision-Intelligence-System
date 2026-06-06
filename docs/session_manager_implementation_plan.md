# Coordinator Session Manager Implementation Plan

## 0. 当前施工进度

截至第一轮施工，已完成：

- Phase 1 核心：本地 JSON session store、多轮 session manager、`run_session` CLI、`runtime/` 忽略规则。
- Phase 2 核心：标准 trace event collector，接入 coordinator 分解/路由/SQL/NLP/Viz/Decision/最终汇总的用户可见过程事件。
- SQL trace 增强：`data_analysis_agent/generate_sql` 与 `data_analysis_agent/execute_sql` 事件会携带并输出具体 SQL 命令。
- Phase 3 核心：语义会话解析器与滚动 `memory_summary` 已接入，不再保留机械解析或规则兜底。
- 会话解析增强：正式分析前由独立语义解析器判断本轮输入与上一轮问题/回答的业务关系，输出本轮真实任务；无法可靠判断时要求澄清，而不是猜测补全。
- Phase 4 核心：HAR 捕获逻辑已抽取到正式源码模块，`run_session --har-out` 可捕获本轮 httpx/LLM 流量；旧 `misc/har/capture_coordinator_har.py` 兼容入口复用正式模块。
- Phase 5 核心：Web/SSE 事件转换层已提供，`run_session --sse` 可实时输出 Server-Sent Events 文本，`SessionManager.stream_turn_events()` 可供 WebSocket/SSE handler 复用。
- 已补充组件测试文件与 README 入口。

暂未完成：

- 尚未实现具体 FastAPI/前端页面；目前提供的是无框架依赖的 Web/API 预留层。

下一步可选择实现一个最小 FastAPI/SSE handler 或前端聊天页面，直接消费实时事件流。

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
  -> conversation resolver 理解当前输入与前文的业务关系
  -> 生成 resolved_task 作为本轮真实任务
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
| `agents/coordinator_agent/memory.py` | 历史裁剪、语义会话摘要生成 |
| `agents/coordinator_agent/conversation_resolver.py` | 将当前输入 + 历史摘要解析成本轮真实业务任务 |
| `agents/coordinator_agent/tracing.py` | 标准化 trace event、从工具 payload/state 提取关键文本 |
| `agents/coordinator_agent/run_session.py` | 多轮 CLI 入口 |
| `agents/coordinator_agent/web_events.py` | SSE/WebSocket 事件转换 |
| `config/coordinator_agent/resolve_conversation_context.md` | 会话语义解析提示词 |
| `config/coordinator_agent/summarize_session_memory.md` | 会话摘要提示词 |
| `docs/session_manager_implementation_plan.md` | 本方案文档 |

可选后续文件：

| 文件 | 用途 |
|------|------|
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
      "resolved_task": "分析 Olist 中 casa_conforto 类产品的评论口碑、销售表现，并判断新卖家进入该类目的前景。",
      "standalone_query": "分析 Olist 中 casa_conforto 类产品的评论口碑、销售表现，并判断新卖家进入该类目的前景。",
      "conversation_resolution": {
        "relation_to_previous": "new_topic",
        "resolved_task": "分析 Olist 中 casa_conforto 类产品的评论口碑、销售表现，并判断新卖家进入该类目的前景。"
      },
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
- `resolved_task`：语义解析器确认的本轮真实业务任务，用于 coordinator 执行。
- `standalone_query`：兼容旧 Web/CLI 调用的别名，内容等同于 `resolved_task`。
- `conversation_resolution`：本轮输入与前文的关系、继承目标、继承对象、新增约束和澄清状态。
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

然后做会话语义解析：

```text
输入：
  - 会话摘要
  - 最近 3 轮问答
  - 当前问题
输出：
  - relation_to_previous
  - resolved_task
  - carried_over_goal / carried_over_subject
  - new_constraints / changed_constraints
  - needs_clarification / clarification_question
```

例子：

```text
历史：用户正在分析 casa_conforto 类产品口碑与入行前景。
当前：那 SP 州呢？
解析：relation_to_previous=scope_refinement；
      resolved_task=在上一轮入行风险与机会判断框架下，聚焦 SP 州评估 casa_conforto 类产品的风险更高还是更低、机会在哪里，并给出数据依据。
```

不再使用“识别代词 + 拼接主题”的规则。若已有历史但语义解析失败，错误应显式暴露；若解析器认为上下文不足，应先向用户澄清，而不是猜一个问题继续分析。

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
- 每轮保存 `user_query`、`resolved_task`、`conversation_resolution`、`final_answer`、`state_summary`。
- `standalone_query` 仅作为兼容别名保留，内容等同于 `resolved_task`。

验收：

```powershell
python -m agents.coordinator_agent.run_session --new --query "人们对 casa_conforto 类产品的评价如何？入行此类产品是否有前景？"
python -m agents.coordinator_agent.run_session --session-id <id> --query "那 SP 州呢？"
python -m agents.coordinator_agent.run_session --list
```

第二轮 session 文件中应出现两条 turns，第二轮 `conversation_resolution` 应说明本轮与上一轮的业务关系，`resolved_task` 应体现继承的目标、对象和新增约束。

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

### Phase 3: 语义会话解析与记忆摘要

- 新增 `conversation_resolver.py` 与 prompt。
- 新增 `memory.py`，维护 `memory_summary`。
- 当历史轮次超过阈值时，滚动更新摘要。
- coordinator synthesize evidence 中加入简短 `conversation_history` 或 `memory_summary`，让最终回答知道用户连续目标。

验收：

- “那 SP 州呢？”、“继续看差评原因”、“如果我要进入这个品类呢？”应被解析为与前文相关的真实任务。
- 解析结果应保留上一轮真实业务目标。例如上一轮关注“某品类入行风险和机会”，本轮问“那 SP 州呢？”，应解析为评估该品类在 SP 州入行风险更高还是更低、机会在哪里，而不是只分析 SP 州表现。
- 对无法判断继承哪段上下文的问题，应返回澄清问题或显式失败，不应规则拼接。
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
    "resolved_task": "...",
    "standalone_query": "...",
    "conversation_resolution": {...},
    "trace_events": [...],
    "final_answer": "...",
}
```

- Web 端可直接把 trace events 转为 SSE/WebSocket 消息。
- 如果后续接 FastAPI，只需要包一层 HTTP handler，不需要改 coordinator 业务逻辑。
- 已提供实时事件流接口，Web handler 可在 Agent 运行过程中逐条推送事件，而不是等整轮结束后回放。

## 12. 测试计划

单元测试：

- `session_store` 创建、加载、覆盖保存、列表排序。
- `memory` 裁剪最近 N 轮。
- `conversation_resolver` 结构化语义解析与失败不兜底。
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
| 追问太短，SQL Agent 无法理解 | 先做语义会话解析，生成 `resolved_task` 后再进 coordinator；无法可靠解析时先澄清 |
| 历史过长导致 prompt 变大 | 保存完整 turns，但 prompt 只用摘要 + 最近 N 轮 |
| trace 泄露技术噪声 | `payload_preview` 截断，只展示摘要；完整 payload 仅调试模式输出 |
| HAR monkey patch 影响运行 | HAR 只在显式 `--har-out` 时安装 |
| 旧 CLI 被破坏 | `run_coordinator(query)` 和 `run.py --query` 保持兼容 |
| session 文件进入 git | 增加 `/runtime/` 到 `.gitignore` |

## 14. 实施检查清单

- [x] 增加 `/runtime/` gitignore。
- [x] 新增 session 数据模型与本地 store。
- [x] 新增 session manager 服务。
- [x] 扩展 `run_coordinator()` 注入 conversation history。
- [x] 新增 `run_session.py` CLI。
- [x] 保存每轮 turn 与 state summary。
- [x] 实现语义会话解析器。
- [x] 新增 trace event collector。
- [x] 接入 SQL/NLP/Viz/Decision/Coordinator 关键事件。
- [x] 移除机械追问改写和规则兜底。
- [x] 会话解析支持与上一轮问题/回答的业务关系分析。
- [x] 实现滚动 memory summary。
- [x] 可选接入 HAR 捕获。
- [x] 提供实时 SSE/WebSocket 事件流接口。
- [x] 补充 tests 与 README 使用说明。

## 15. 推荐优先级

第一轮实施只做 Phase 1 + Phase 2 的核心部分，即“能多轮、能保存、能展示过程”。  
CLI 稳定后，优先完善语义会话解析器的测试样例、澄清交互和前端 SSE 消费层；HAR 仍保持为可选调试能力。
