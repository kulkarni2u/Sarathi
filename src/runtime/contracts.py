"""Typed runtime contracts for dispatcher-backed orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class DispatchRequest:
    """Structured request for an explore/execute runtime."""

    mode: Literal["explore", "execute"]
    task_id: str
    phase: str
    prompt: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300
    retry_budget: int = 0


@dataclass
class DispatchResponse:
    """Structured response from a runtime."""

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    raw_transcript_ref: str | None = None
    error: str | None = None


@dataclass
class GateResult:
    """Normalized gate evaluation."""

    passed: bool
    score: float
    threshold: float
    missing_evidence: list[str] = field(default_factory=list)
    decision: Literal["pass", "retry", "escalate", "fail"] = "pass"
