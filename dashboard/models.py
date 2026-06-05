from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class AgentProgress:
    completed: list[str]
    current: str | None
    current_label: str | None
    finished: bool = False


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
    timestamp: datetime
    decision_summary: str | None = None
    warnings: list[str] = field(default_factory=list)
    agent_progress: AgentProgress | None = None
    viz_round: VizRound | None = None


@dataclass
class Conversation:
    id: str
    title: str
    messages: list[ChatMessage] = field(default_factory=list)
    last_state: dict[str, Any] | None = None
    agent_progress: AgentProgress | None = None
