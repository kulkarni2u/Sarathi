"""Three-tier policy layering: server -> workspace -> session, strictest-wins for caps."""
from __future__ import annotations

from typing import Any, Mapping

_CAP_KEYS = ("cost_budget_tokens", "max_tool_calls")


def extract_server_caps(compiled_policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract baseline caps from a compiled policy pack.

    - `escalation.budget.max_total_tokens` -> `cost_budget_tokens` (int or None)
    - `escalation.budget.max_tool_calls` -> `max_tool_calls` (int or None)
    - `required_approval_gates`: from `escalation.never_auto_approve_gates` if present
      (a list of gate-name strings), else `[]`.

    Tolerant of `compiled_policy` being None, missing `escalation`, or malformed values.
    """
    cost_budget_tokens: int | None = None
    max_tool_calls: int | None = None
    required_approval_gates: list[str] = []

    escalation: Any = None
    if compiled_policy is not None:
        try:
            escalation = compiled_policy.get("escalation")
        except (AttributeError, TypeError):
            escalation = None

    if isinstance(escalation, Mapping):
        budget = escalation.get("budget")
        if isinstance(budget, Mapping):
            max_total_tokens = budget.get("max_total_tokens")
            if isinstance(max_total_tokens, int) and not isinstance(max_total_tokens, bool):
                cost_budget_tokens = max_total_tokens

            budget_max_tool_calls = budget.get("max_tool_calls")
            if isinstance(budget_max_tool_calls, int) and not isinstance(budget_max_tool_calls, bool):
                max_tool_calls = budget_max_tool_calls

        gates = escalation.get("never_auto_approve_gates")
        if isinstance(gates, list):
            required_approval_gates = [gate for gate in gates if isinstance(gate, str)]

    return {
        "cost_budget_tokens": cost_budget_tokens,
        "max_tool_calls": max_tool_calls,
        "required_approval_gates": required_approval_gates,
    }


def normalize_policy_overrides(overrides: Any) -> dict[str, Any]:
    """Validate & normalize a user-supplied overrides mapping for PATCH endpoints.

    Returns a partial dict containing only the keys present in `overrides` after
    validation/normalization. Raises `ValueError` on invalid input.
    """
    if not isinstance(overrides, Mapping):
        raise ValueError("Policy overrides must be an object.")

    normalized: dict[str, Any] = {}

    for key in _CAP_KEYS:
        if key not in overrides:
            continue
        value = overrides[key]
        if value is None:
            normalized[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"Field '{key}' must be a positive integer or null.")
        normalized[key] = value

    if "required_approval_gates" in overrides:
        gates = overrides["required_approval_gates"]
        if not isinstance(gates, list) or not all(
            isinstance(gate, str) and gate.strip() for gate in gates
        ):
            raise ValueError(
                "Field 'required_approval_gates' must be a list of non-empty strings."
            )
        deduped: list[str] = []
        seen: set[str] = set()
        for gate in gates:
            if gate in seen:
                continue
            seen.add(gate)
            deduped.append(gate)
        normalized["required_approval_gates"] = deduped

    return normalized


def _tighter_or_equal(candidate: Any, current: int | None) -> bool:
    """True if `candidate` (int or None) is stricter than or equal to `current`."""
    if candidate is None:
        # None == uncapped == +infinity; only equal (i.e. current is also None)
        return current is None
    if current is None:
        return True
    return candidate <= current


def resolve_policy_layers(
    server_caps: Mapping[str, Any],
    workspace_overrides: Mapping[str, Any] | None = None,
    session_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the diffable layered-resolution artifact."""
    effective: dict[str, Any] = {
        "cost_budget_tokens": server_caps.get("cost_budget_tokens"),
        "max_tool_calls": server_caps.get("max_tool_calls"),
    }
    gates: list[str] = []
    for gate in server_caps.get("required_approval_gates") or []:
        if gate not in gates:
            gates.append(gate)

    layers: list[dict[str, Any]] = [
        {
            "scope": "server",
            "overrides": {
                "cost_budget_tokens": server_caps.get("cost_budget_tokens"),
                "max_tool_calls": server_caps.get("max_tool_calls"),
                "required_approval_gates": list(server_caps.get("required_approval_gates") or []),
            },
            "rejected": {},
        }
    ]

    tiers: list[tuple[str, Mapping[str, Any] | None]] = [
        ("workspace", workspace_overrides if workspace_overrides is not None else {}),
        ("session", session_overrides),
    ]

    for scope, tier_overrides in tiers:
        if scope == "session" and session_overrides is None:
            continue

        tier_overrides = tier_overrides or {}
        layer_overrides: dict[str, Any] = {}
        rejected: dict[str, Any] = {}

        for key in _CAP_KEYS:
            if key not in tier_overrides:
                continue
            candidate = tier_overrides[key]
            layer_overrides[key] = candidate
            if _tighter_or_equal(candidate, effective.get(key)):
                effective[key] = candidate
            else:
                rejected[key] = candidate

        if "required_approval_gates" in tier_overrides:
            tier_gates = tier_overrides["required_approval_gates"] or []
            layer_overrides["required_approval_gates"] = list(tier_gates)
            for gate in tier_gates:
                if gate not in gates:
                    gates.append(gate)

        layers.append({"scope": scope, "overrides": layer_overrides, "rejected": rejected})

    return {
        "effective": {
            "cost_budget_tokens": effective["cost_budget_tokens"],
            "max_tool_calls": effective["max_tool_calls"],
            "required_approval_gates": gates,
        },
        "layers": layers,
    }


def caps_would_loosen(
    parent_effective: Mapping[str, Any], proposed_overrides: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the subset of `proposed_overrides` whose numeric cap would be LOOSER
    than `parent_effective`'s value for that key."""
    result: dict[str, Any] = {}
    for key in _CAP_KEYS:
        if key not in proposed_overrides:
            continue
        candidate = proposed_overrides[key]
        parent_value = parent_effective.get(key)
        if not _tighter_or_equal(candidate, parent_value):
            result[key] = candidate
    return result
