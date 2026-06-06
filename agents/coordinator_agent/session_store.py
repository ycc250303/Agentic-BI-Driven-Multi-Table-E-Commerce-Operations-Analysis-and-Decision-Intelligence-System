from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(text: str, *, limit: int = 36) -> str:
    raw = str(text or "").lower()
    parts = re.findall(r"[a-z0-9]+", raw)
    if not parts:
        return "session"
    return "-".join(parts)[:limit].strip("-") or "session"


def _make_session_id(title: str = "") -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(title)}-{uuid.uuid4().hex[:6]}"


def _validate_session_id(session_id: str) -> str:
    sid = str(session_id or "").strip()
    if not sid or not SESSION_ID_RE.match(sid):
        raise ValueError(f"非法 session_id：{session_id!r}")
    return sid


class LocalSessionStore:
    """JSON file based session storage for local CLI and demos."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else _project_root() / "runtime" / "sessions"

    def _path(self, session_id: str) -> Path:
        sid = _validate_session_id(session_id)
        return self.root / f"{sid}.json"

    def create_session(self, *, title: str = "", session_id: str | None = None) -> dict[str, Any]:
        sid = _validate_session_id(session_id) if session_id else _make_session_id(title)
        now = _now_iso()
        return {
            "session_id": sid,
            "title": title or sid,
            "created_at": now,
            "updated_at": now,
            "memory_summary": "",
            "turns": [],
        }

    def load_session(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.is_file():
            raise FileNotFoundError(f"session 不存在：{session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"session 文件不是 JSON object：{path}")
        data.setdefault("session_id", _validate_session_id(session_id))
        data.setdefault("turns", [])
        data.setdefault("memory_summary", "")
        return data

    def save_session(self, session: dict[str, Any]) -> Path:
        sid = _validate_session_id(str(session.get("session_id") or ""))
        self.root.mkdir(parents=True, exist_ok=True)
        session["updated_at"] = _now_iso()
        path = self._path(sid)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(session, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            turns = data.get("turns") or []
            items.append(
                {
                    "session_id": data.get("session_id") or path.stem,
                    "title": data.get("title") or path.stem,
                    "created_at": data.get("created_at") or "",
                    "updated_at": data.get("updated_at") or "",
                    "turn_count": len(turns) if isinstance(turns, list) else 0,
                    "path": str(path),
                }
            )
        return sorted(items, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def delete_session(self, session_id: str) -> None:
        path = self._path(_validate_session_id(session_id))
        if path.is_file():
            path.unlink()
