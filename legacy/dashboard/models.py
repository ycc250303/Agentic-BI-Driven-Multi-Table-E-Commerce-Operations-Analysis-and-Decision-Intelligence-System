from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class VizRound:
    """一轮问答对应的可视化结果。"""

    user_query: str
    charts: list[dict[str, Any]] = field(default_factory=list)
    summary_text: str | None = None
    skipped: bool = False


@dataclass
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    resolved_task: str | None = None
    decision_summary: str | None = None
    warnings: list[str] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    viz_round: VizRound | None = None


@dataclass
class Conversation:
    id: str
    title: str
    messages: list[ChatMessage] = field(default_factory=list)
    turn_count: int = 0
    updated_at: str = ""
