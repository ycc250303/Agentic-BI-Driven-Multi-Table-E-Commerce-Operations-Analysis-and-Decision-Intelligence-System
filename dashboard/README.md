# Dashboard（Streamlit Web 前端）

本目录为 Agentic BI 的 **Streamlit Web 界面**，与协调器 [`SessionManager`](../agents/coordinator_agent/session_manager.py) 共用同一套多轮会话后端；会话数据持久化在 `runtime/sessions/`。

## 运行

在项目根目录执行：

```bash
streamlit run dashboard/app.py
```

依赖根目录 `.env` 中的 LLM 与数据库配置（与 CLI / 协调器相同）。

另有一个零依赖的 HTTP + SSE 示例见 [`examples/session_web_demo/`](../examples/session_web_demo/)，本 Dashboard **进程内直接调用** `SessionManager`，不经过 HTTP。

---

## 目录结构

```
dashboard/
├── app.py                 # 入口：页面布局与组件编排
├── layout.py              # 注入全局 CSS
├── styles.css             # 主区域与侧边栏样式
├── constants.py           # UI 常量（面板高度、列宽等）
├── models.py              # UI 投影模型（Conversation / ChatMessage / VizRound）
├── session_store.py       # Streamlit 壳层 + SessionManager 适配
├── session_projection.py  # 磁盘 session turn → UI 消息 / 图表投影
├── turn_runner.py         # 封装 stream_turn_events，驱动单轮分析
├── viz_helpers.py         # 可视化轮次收集与渲染
├── agent_labels.py        # Agent / trace 步骤中文标签
├── text_utils.py          # 侧边栏标题等文本工具
├── components/
│   ├── sidebar.py         # 左侧：新建 / 列表 / 删除会话
│   ├── chat_panel.py      # 中间：对话、trace 进度、提交问题
│   ├── viz_panel.py       # 右侧：按提问分组的图表
│   └── agent_progress.py  # trace 时间线（运行中 status / 完成后 expander）
└── tests/
    └── test_session_projection.py
```

---

## 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  Sidebar          │  对话（chat_panel）  │  可视化（viz）   │
│  · 新建对话        │  3 : 2 宽屏两列，各自独立滚动          │
│  · 会话列表        │                                      │
└─────────────────────────────────────────────────────────────┘
```

- 入口见 [`app.py`](app.py)：侧边栏 + 对话 / 可视化两列（`PANEL_SCROLL_HEIGHT` 控制滚动高度）。
- 样式见 [`styles.css`](styles.css)，由 [`layout.py`](layout.py) 注入。

---

## 模块职责

| 模块 | 职责 |
|------|------|
| `app.py` | `st.set_page_config`、初始化 session、组装 sidebar / chat / viz |
| `session_store.py` | 维护 `active_conversation_id`、`pending_query`、`live_viz`；读写 `SessionManager` |
| `session_projection.py` | 将 `runtime/sessions/*.json` 中的 turn 转为 `ChatMessage` / `VizRound` |
| `turn_runner.py` | 调用 `SessionManager.stream_turn_events()`，消费 `web_events` 形状的事件 |
| `chat_panel.py` | 渲染历史消息；pending 问题 + rerun 触发分析；实时 trace 与图表预览 |
| `viz_panel.py` | 按时间顺序展示各轮图表（旧在上、新在下，与对话一致） |
| `sidebar.py` | 列出磁盘上全部 session（含 CLI 创建的）；单行省略标题 |

---

## 数据流

```
用户输入
  → session_store.set_pending_query
  → st.rerun
  → turn_runner.stream_turn(session_id, query)
       └─ SessionManager.stream_turn_events()
            ├─ trace.event   → chat_panel 实时 trace 时间线
            ├─ answer.final  → 更新 live 图表预览
            └─ turn.completed → 写入 runtime/sessions/{id}.json
  → clear pending、rerun
  → session_projection 从磁盘加载 turns，渲染对话与可视化
```

**权威数据源**：`runtime/sessions/` JSON 文件。  
**Streamlit 仅缓存**：当前选中 session、待执行 query、生成中图表预览。

---

## 与协调器的关系

| 能力 | 实现 |
|------|------|
| 多轮追问 / 指代 | `SessionManager` → `resolve_conversation_context` |
| 会话记忆 | `memory_summary` + `build_conversation_history` |
| Agent 过程 | turn 内 `trace_events`，完成后可在 expander 中查看全部步骤 |
| 图表 | turn 的 `state_summary.charts`；PNG 路径指向 `agents/viz_agent/chart_output/` |
| 行动建议 | `full_state=True` 时从 turn.state 投影 `decision_result` |

协调器 CLI：`python -m agents.coordinator_agent.run_session`  
与本 Dashboard 读写同一 `runtime/sessions/` 目录。

---

## 测试

```bash
pytest dashboard/tests/ -q
```
