"""Agent state dataclasses for the plan-then-execute controller."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    """One executed tool step inside an agent session."""
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class PlanStep:
    """One planned action: a tool plus the arguments to call it with."""
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class AgentPlan:
    """The plan the controller produced before executing anything."""
    intent: str
    confidence: float
    steps: list[PlanStep] = field(default_factory=list)
    rationale: str = ""


@dataclass(slots=True)
class AgentResult:
    """Final agent answer with a full evidence chain."""
    session_id: str
    conversation_id: str
    answer: str
    grounded: bool
    intent: str
    confidence: float
    tools_used: list[str]
    citations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    latency_ms: int
    confidence_note: str = ""
    escalated: bool = False
    followup_question: str | None = None
    answer_run_id: str | None = None
    deterministic_evidence: dict[str, Any] = field(default_factory=dict)
    terminal_status: str | None = None
    timeout_reason: str | None = None
    plan_status: dict[str, Any] = field(default_factory=dict)
    finalize_stage: str | None = None
    guard_triggered: list[str] = field(default_factory=list)
