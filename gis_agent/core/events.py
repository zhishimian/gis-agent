from collections.abc import Callable
from dataclasses import dataclass
from time import time
from typing import Any, Literal

EventType = Literal[
    "turn_started",
    "model_replied",
    "tool_started",
    "tool_finished",
    "turn_finished",
]


@dataclass(frozen=True)
class AgentEvent:
    type: EventType
    session_id: str
    payload: dict[str, Any]
    timestamp_ms: int


EventCallback = Callable[[AgentEvent], None]


def emit_event(callback: EventCallback | None, event_type: EventType, session_id: str, **payload: Any) -> None:
    if callback is None:
        return
    callback(AgentEvent(type=event_type, session_id=session_id, payload=payload, timestamp_ms=int(time() * 1000)))
