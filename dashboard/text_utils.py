from __future__ import annotations

from dashboard.constants import SESSION_BUTTON_MAX_CHARS


def truncate_text(text: str, max_chars: int, *, suffix: str = "…") -> str:
    if len(text) <= max_chars:
        return text
    keep = max(max_chars - len(suffix), 0)
    return text[:keep] + suffix


def format_session_button_label(
    title: str,
    *,
    active: bool,
    max_chars: int = SESSION_BUTTON_MAX_CHARS,
) -> str:
    text = f"▸ {title}" if active else title
    return truncate_text(text, max_chars)
