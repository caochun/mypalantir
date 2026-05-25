from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    step_id: int
    action: str
    target: str
    args: dict[str, Any] = field(default_factory=dict)
    purpose: str = ""
    depends_on: list[int] = field(default_factory=list)


@dataclass
class Plan:
    question: str
    steps: list[PlanStep] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class StepResult:
    step_id: int
    target: str
    output: Any = None
    status: str = "success"
    note: str = ""


@dataclass
class ReviewResult:
    step_id: int
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""
