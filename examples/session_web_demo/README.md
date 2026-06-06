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

## 接口

- `GET /`：网页入口
- `GET /api/sessions`：列出本地 session
- `GET /api/session?id=<session_id>`：读取某个 session 的历史对话
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
