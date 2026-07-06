"""Typed runtime contracts for dispatcher-backed orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, Literal, Mapping


BudgetState = Literal["ok", "warning", "near_limit", "exhausted", "unknown"]
UsageSource = Literal["reported", "estimated", "mixed"]


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
    context_pack: dict[str, Any] | None = None
    token_budget: int | None = None
    timeout_seconds: int = 300
    retry_budget: int = 0
    # Traceability/enforcement for the "declare before dispatch" invariant:
    # the harness_id of the HarnessConfig (see src/harness.py) that was
    # compiled before this dispatch was issued. Populated directly by
    # TaskGraphExecutor for graph-node dispatch (when given a harness_config)
    # and backfilled by the engine's harness-aware dispatcher wrapper for
    # phase-level dispatch.
    harness_id: str | None = None


@dataclass
class UsageRecord:
    """Normalized token usage for a single dispatch."""

    provider_id: str
    provider_family: str
    dispatch_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = True
    budget_limit: int | None = None
    budget_remaining: int | None = None
    budget_state: BudgetState = "unknown"
    usage_source: UsageSource = "estimated"
    # Dollar cost for this dispatch, when known. None means "unpriced" — not
    # zero cost. Populated either from a provider's self-reported cost (e.g.
    # claude's total_cost_usd) or computed from a policy pricing table (see
    # src/runtime/pricing.py); self-reported always wins. Optional and
    # defaulted so existing constructors/serialization keep working.
    cost_usd: float | None = None

    def to_artifact(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_family": self.provider_family,
            "dispatch_id": self.dispatch_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated": self.estimated,
            "budget_limit": self.budget_limit,
            "budget_remaining": self.budget_remaining,
            "budget_state": self.budget_state,
            "usage_source": self.usage_source,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> UsageRecord | None:
        if not isinstance(payload, Mapping):
            return None
        provider_id = payload.get("provider_id")
        provider_family = payload.get("provider_family")
        dispatch_id = payload.get("dispatch_id")
        if not all(isinstance(value, str) and value for value in (provider_id, provider_family, dispatch_id)):
            return None
        return cls(
            provider_id=provider_id,
            provider_family=provider_family,
            dispatch_id=dispatch_id,
            input_tokens=_int_value(payload.get("input_tokens")),
            output_tokens=_int_value(payload.get("output_tokens")),
            total_tokens=_int_value(payload.get("total_tokens")),
            estimated=bool(payload.get("estimated", True)),
            budget_limit=_optional_int(payload.get("budget_limit")),
            budget_remaining=_optional_int(payload.get("budget_remaining")),
            budget_state=_budget_state(payload.get("budget_state")),
            usage_source=_usage_source(payload.get("usage_source")),
            cost_usd=_optional_float(payload.get("cost_usd")),
        )


@dataclass
class DispatchResponse:
    """Structured response from a runtime."""

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    raw_transcript_ref: str | None = None
    usage: UsageRecord | None = None
    error: str | None = None


@dataclass
class GateResult:
    """Normalized gate evaluation."""

    passed: bool
    score: float
    threshold: float
    missing_evidence: list[str] = field(default_factory=list)
    decision: Literal["pass", "retry", "escalate", "fail"] = "pass"


def build_usage_record(
    *,
    provider_id: str,
    provider_family: str | None = None,
    dispatch_id: str,
    prompt: str = "",
    response_text: str = "",
    reported_usage: Mapping[str, Any] | None = None,
    budget_limit: int | None = None,
    reported_cost_usd: float | None = None,
) -> UsageRecord:
    """Create a normalized usage record from provider telemetry or estimates.

    ``reported_cost_usd`` is a provider's self-reported dollar cost (e.g.
    claude CLI's ``total_cost_usd``), when the caller already has it in hand.
    It takes precedence over anything a pricing table would later compute
    (see src/runtime/pricing.py) — callers that don't have a self-reported
    cost should leave this as None and let cost resolution happen downstream.
    """
    provider_family = provider_family or provider_id
    reported = reported_usage if isinstance(reported_usage, Mapping) else None

    input_tokens = _optional_int(_usage_value(reported, "input_tokens", "prompt_tokens"))
    output_tokens = _optional_int(_usage_value(reported, "output_tokens", "completion_tokens"))
    total_tokens = _optional_int(_usage_value(reported, "total_tokens"))

    estimated_input = _estimate_token_count(prompt)
    estimated_output = _estimate_token_count(response_text)

    used_reported = False
    used_estimated = False

    if input_tokens is None:
        input_tokens = estimated_input
        used_estimated = True
    else:
        used_reported = True

    if output_tokens is None:
        output_tokens = estimated_output
        used_estimated = True
    else:
        used_reported = True

    if total_tokens is None:
        total_tokens = max(input_tokens + output_tokens, estimated_input + estimated_output)
        used_estimated = True
    else:
        used_reported = True

    resolved_budget_limit = _optional_int(_usage_value(reported, "budget_limit", "budget"))
    if resolved_budget_limit is None:
        resolved_budget_limit = budget_limit
    resolved_budget_remaining = _optional_int(_usage_value(reported, "budget_remaining"))
    resolved_budget_state = _budget_state(_usage_value(reported, "budget_state"))

    if resolved_budget_limit is not None and resolved_budget_remaining is None:
        resolved_budget_remaining = max(resolved_budget_limit - total_tokens, 0)

    if resolved_budget_state == "unknown" and resolved_budget_limit is not None:
        ratio = total_tokens / resolved_budget_limit if resolved_budget_limit > 0 else 1.0
        if ratio >= 1.0:
            resolved_budget_state = "exhausted"
        elif ratio >= 0.9:
            resolved_budget_state = "near_limit"
        elif ratio >= 0.75:
            resolved_budget_state = "warning"
        else:
            resolved_budget_state = "ok"

    usage_source = _usage_source(_usage_value(reported, "usage_source"))
    if usage_source == "estimated" and used_reported and used_estimated:
        usage_source = "mixed"
    elif usage_source == "estimated" and used_reported:
        usage_source = "reported"
    elif usage_source == "reported" and used_estimated:
        usage_source = "mixed"
    elif reported is None:
        usage_source = "estimated"

    estimated = reported is None or used_estimated
    return UsageRecord(
        provider_id=provider_id,
        provider_family=provider_family,
        dispatch_id=dispatch_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated=estimated,
        budget_limit=resolved_budget_limit,
        budget_remaining=resolved_budget_remaining,
        budget_state=resolved_budget_state,
        usage_source=usage_source,
        cost_usd=_optional_float(reported_cost_usd),
    )


def _usage_value(payload: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _estimate_token_count(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, ceil(len(cleaned) / 4))


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _budget_state(value: Any) -> BudgetState:
    valid = {"ok", "warning", "near_limit", "exhausted", "unknown"}
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in valid:
            return normalized  # type: ignore[return-value]
    return "unknown"


def _usage_source(value: Any) -> UsageSource:
    valid = {"reported", "estimated", "mixed"}
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in valid:
            return normalized  # type: ignore[return-value]
    return "estimated"
