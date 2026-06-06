from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_VIZ_DIR = PROJECT_ROOT / "agents" / "viz_agent" / "chart_output"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.coordinator_agent.session_manager import CoordinatorRunOptions, SessionManager
from agents.coordinator_agent.web_events import encode_sse_event


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    turns = []
    for turn in session.get("turns") or []:
        turns.append(
            {
                "turn_id": turn.get("turn_id"),
                "created_at": turn.get("created_at") or "",
                "user_query": turn.get("user_query") or "",
                "resolved_task": turn.get("resolved_task") or turn.get("standalone_query") or "",
                "final_answer": turn.get("final_answer") or "",
                "trace_events": turn.get("trace_events") or [],
                "state_summary": turn.get("state_summary") or {},
            }
        )
    return {
        "session_id": session.get("session_id") or "",
        "title": session.get("title") or "",
        "created_at": session.get("created_at") or "",
        "updated_at": session.get("updated_at") or "",
        "memory_summary": session.get("memory_summary") or "",
        "turns": turns,
    }


def _allowed_image_dirs() -> list[Path]:
    dirs = [DEFAULT_VIZ_DIR]
    raw = os.environ.get("AGENTIC_BI_VIZ_DIR")
    if raw:
        dirs.append(Path(raw).expanduser())
    return [p.resolve() for p in dirs]


def _options_from_payload(payload: dict[str, Any]) -> CoordinatorRunOptions:
    raw = payload.get("options") or {}
    if not isinstance(raw, dict):
        raw = {}
    return CoordinatorRunOptions(
        use_llm_plan=bool(raw.get("use_llm_plan", True)),
        use_llm_viz=bool(raw.get("use_llm_viz", True)),
        use_llm_synthesize=bool(raw.get("use_llm_synthesize", True)),
        full_state=bool(raw.get("full_state", False)),
    )


class SessionWebDemoHandler(BaseHTTPRequestHandler):
    manager = SessionManager()
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html")
            return
        if parsed.path == "/api/sessions":
            self._handle_list_sessions()
            return
        if parsed.path == "/api/session":
            self._handle_get_session(parsed)
            return
        if parsed.path == "/api/image":
            self._handle_get_image(parsed)
            return
        if parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            self._send_static(rel)
            return
        self._send_json(404, {"error": "not_found", "message": "路径不存在。"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/turn":
            self._handle_run_turn()
            return
        self._send_json(404, {"error": "not_found", "message": "路径不存在。"})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[session-web-demo] " + fmt % args + "\n")

    def _send_json(self, status: int, payload: Any) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json(404, {"error": "not_found", "message": "文件不存在。"})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or path.suffix in {".js", ".css", ".html"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        base = STATIC_DIR.resolve()
        requested = (base / rel).resolve()
        try:
            requested.relative_to(base)
        except ValueError:
            self._send_json(403, {"error": "forbidden", "message": "非法静态资源路径。"})
            return
        self._send_file(requested)

    def _handle_get_image(self, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        raw_path = str((params.get("path") or [""])[0]).strip()
        if not raw_path:
            self._send_json(400, {"error": "bad_request", "message": "缺少图片路径。"})
            return

        requested = Path(raw_path).expanduser().resolve()
        if requested.suffix.lower() != ".png":
            self._send_json(403, {"error": "forbidden", "message": "仅允许访问 PNG 图片。"})
            return
        allowed = False
        for base in _allowed_image_dirs():
            try:
                requested.relative_to(base)
            except ValueError:
                continue
            allowed = True
            break
        if not allowed:
            self._send_json(403, {"error": "forbidden", "message": "图片路径不在可视化输出目录中。"})
            return
        self._send_file(requested)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > 1024 * 1024:
            raise ValueError("请求体过大。")
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON object。")
        return payload

    def _handle_list_sessions(self) -> None:
        self._send_json(200, {"sessions": self.manager.list_sessions()})

    def _handle_get_session(self, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        session_id = str((params.get("id") or [""])[0]).strip()
        if not session_id:
            self._send_json(400, {"error": "bad_request", "message": "缺少 session id。"})
            return
        try:
            session = self.manager.load_session(session_id)
        except FileNotFoundError as exc:
            self._send_json(404, {"error": "not_found", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"error": type(exc).__name__, "message": str(exc)})
            return
        self._send_json(200, {"session": _public_session(session)})

    def _handle_run_turn(self) -> None:
        try:
            payload = self._read_json_body()
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"error": type(exc).__name__, "message": str(exc)})
            return

        query = str(payload.get("query") or "").strip()
        session_id = str(payload.get("session_id") or "").strip() or None
        new_session = bool(payload.get("new_session", not bool(session_id)))
        title = str(payload.get("title") or "").strip()
        options = _options_from_payload(payload)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        try:
            for event in self.manager.stream_turn_events(
                query=query,
                session_id=session_id,
                new_session=new_session,
                title=title,
                options=options,
            ):
                self.wfile.write(encode_sse_event(event).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Session manager web demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SessionWebDemoHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Session web demo running at {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping session web demo.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
