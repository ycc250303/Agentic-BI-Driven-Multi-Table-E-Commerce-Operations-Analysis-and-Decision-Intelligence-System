# Session Web Demo

一个零新增依赖的 session manager 网页调用示例。后端使用 Python 标准库 `http.server`，前端用 `fetch` 读取 `SessionManager.stream_turn_events()` 输出的 SSE 事件流。

## 运行

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe examples\session_web_demo\server.py --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010/
```

真实 BI 分析仍依赖项目已有的 `.env`、LLM Key 和数据库配置。会话文件继续写入 `runtime/sessions/`。

## 查看项目输出的图片

可视化 Agent 会把 PNG 写到 `agents/viz_agent/chart_output/`，也可以通过环境变量 `AGENTIC_BI_VIZ_DIR` 指定其他目录。命令行里可先用已有 CSV 生成一张图：

```powershell
.\.venv\Scripts\python.exe agents\viz_agent\run.py --csv "agents\sql_agent\query_results\2026-06-06 14-51-12.csv" --query "各州 GMV 对比，生成柱状图" --no-llm
```

命令输出中的 `image_path` 就是 PNG 文件路径，可以直接双击打开。启动本 demo 后，协调器生成的图表会跟随最终回答显示在网页里；历史会话里的图表也会从 `state_summary.charts` 恢复显示。

## 接口

- `GET /`：网页入口
- `GET /api/sessions`：列出本地 session
- `GET /api/session?id=<session_id>`：读取某个 session 的历史对话
- `GET /api/image?path=<png_path>`：读取可视化输出目录里的 PNG 图片
- `POST /api/turn`：提交本轮问题，返回 `text/event-stream`

`POST /api/turn` 请求体示例：

```json
{
  "query": "2017年哪个州的销售额最高？",
  "session_id": null,
  "new_session": true
}
```

前端主要处理这些事件：

- `turn.started`
- `trace.event`
- `answer.final`
- `turn.completed`
- `turn.error`
