"""进程级日志：入口调用 ``configure_logging``；``session_id`` 经 contextvars 贯穿。"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_session_id: ContextVar[str] = ContextVar("session_id", default="-")
_configured = False


def get_session_id() -> str:
    return _session_id.get() or "-"


def set_session_id(session_id: str | None) -> Token[str]:
    return _session_id.set(str(session_id or "-"))


def reset_session_id(token: Token[str]) -> None:
    _session_id.reset(token)


@contextmanager
def bind_session_id(session_id: str | None) -> Iterator[str]:
    token = set_session_id(session_id)
    try:
        yield get_session_id()
    finally:
        reset_session_id(token)


class SessionIdFilter(logging.Filter):
    """把当前 session_id 写入 LogRecord，供 formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = get_session_id()
        return True


def configure_logging(*, level: int | str = logging.INFO) -> None:
    """幂等配置根 logger。已有 handler 时只补 session_id filter，不重复 basicConfig。"""
    global _configured
    if _configured:
        return
    resolved = (
        level
        if isinstance(level, int)
        else getattr(logging, str(level).upper(), logging.INFO)
    )
    root = logging.getLogger()
    session_filter = SessionIdFilter()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s session_id=%(session_id)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        handler.addFilter(session_filter)
        root.addHandler(handler)
        root.setLevel(resolved)
    else:
        for handler in root.handlers:
            if not any(isinstance(item, SessionIdFilter) for item in handler.filters):
                handler.addFilter(session_filter)
        if root.level == logging.NOTSET:
            root.setLevel(resolved)
    _configured = True
