from __future__ import annotations

def truncate_text(text: str, max_chars: int, *, suffix: str = "…") -> str:
    if len(text) <= max_chars:
        return text
    keep = max(max_chars - len(suffix), 0)
    return text[:keep] + suffix


def format_session_button_label(title: str, *, active: bool) -> str:
    return f"▸ {title}" if active else title
