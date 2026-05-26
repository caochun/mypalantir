from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    type: str


@dataclass
class TextEvent(Event):
    type: str = "text"
    content: str = ""


@dataclass
class ToolCallEvent(Event):
    type: str = "tool_call"
    name: str = ""
    args: dict = field(default_factory=dict)
    result: str = ""
    step_id: int | None = None


@dataclass
class PlanEvent(Event):
    type: str = "plan"
    reasoning: str = ""
    steps: list[dict] = field(default_factory=list)


@dataclass
class StepStartEvent(Event):
    type: str = "step_start"
    step_id: int = 0
    target: str = ""
    purpose: str = ""


@dataclass
class StepDoneEvent(Event):
    type: str = "step_done"
    step_id: int = 0
    target: str = ""
    status: str = ""
    note: str = ""


@dataclass
class ReviewEvent(Event):
    type: str = "review"
    step_id: int = 0
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class CompactEvent(Event):
    type: str = "compact"
    before_tokens: int = 0
    after_tokens: int = 0


@dataclass
class PlanningEvent(Event):
    type: str = "planning"
    content: str = ""


@dataclass
class SynthesizingEvent(Event):
    type: str = "synthesizing"
    content: str = ""


@dataclass
class HookBlockedEvent(Event):
    type: str = "hook_blocked"
    hook_event: str = ""
    reason: str = ""


@dataclass
class ConfirmationEvent(Event):
    type: str = "confirmation_required"
    tool_name: str = ""
    args: dict = field(default_factory=dict)
    reason: str = ""


def event_to_dict(event: Event) -> dict:
    result = {"type": event.type}
    for k, v in event.__dict__.items():
        if k == "type":
            continue
        if v or v == 0 or v is False:
            result[k] = v
    return result
