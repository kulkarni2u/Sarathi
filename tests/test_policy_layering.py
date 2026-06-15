"""Tests for src.policy.layering: three-tier policy layering, strictest-wins."""

from __future__ import annotations

import pytest

from src.policy.layering import (
    caps_would_loosen,
    extract_server_caps,
    normalize_policy_overrides,
    resolve_policy_layers,
)


# ---------------------------------------------------------------------------
# extract_server_caps
# ---------------------------------------------------------------------------


def test_extract_server_caps_none_input():
    assert extract_server_caps(None) == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }


def test_extract_server_caps_from_compiled_policy_like_dict():
    compiled_policy = {
        "escalation": {
            "budget": {"max_total_tokens": 200000, "max_tool_calls": 50},
            "never_auto_approve_gates": ["Repository action"],
        },
    }
    assert extract_server_caps(compiled_policy) == {
        "cost_budget_tokens": 200000,
        "max_tool_calls": 50,
        "required_approval_gates": ["Repository action"],
    }


def test_extract_server_caps_missing_escalation():
    assert extract_server_caps({}) == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }


def test_extract_server_caps_malformed_escalation():
    # escalation is not a mapping
    assert extract_server_caps({"escalation": "not-a-dict"}) == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }


def test_extract_server_caps_malformed_budget_and_gates():
    compiled_policy = {
        "escalation": {
            "budget": "not-a-dict",
            "never_auto_approve_gates": "not-a-list",
        },
    }
    assert extract_server_caps(compiled_policy) == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }


def test_extract_server_caps_malformed_numeric_values():
    compiled_policy = {
        "escalation": {
            "budget": {"max_total_tokens": "lots", "max_tool_calls": None},
        },
    }
    assert extract_server_caps(compiled_policy) == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }


def test_extract_server_caps_partial_budget():
    compiled_policy = {
        "escalation": {
            "budget": {"max_total_tokens": 50000},
        },
    }
    result = extract_server_caps(compiled_policy)
    assert result["cost_budget_tokens"] == 50000
    assert result["max_tool_calls"] is None
    assert result["required_approval_gates"] == []


# ---------------------------------------------------------------------------
# normalize_policy_overrides
# ---------------------------------------------------------------------------


def test_normalize_policy_overrides_valid_partial():
    result = normalize_policy_overrides(
        {"cost_budget_tokens": 100000, "max_tool_calls": 20}
    )
    assert result == {"cost_budget_tokens": 100000, "max_tool_calls": 20}


def test_normalize_policy_overrides_none_clears_cap():
    result = normalize_policy_overrides({"cost_budget_tokens": None})
    assert result == {"cost_budget_tokens": None}


def test_normalize_policy_overrides_required_approval_gates_dedup_preserves_order():
    result = normalize_policy_overrides(
        {"required_approval_gates": ["Repository action", "Final handoff", "Repository action"]}
    )
    assert result == {"required_approval_gates": ["Repository action", "Final handoff"]}


def test_normalize_policy_overrides_unknown_keys_ignored():
    result = normalize_policy_overrides(
        {"cost_budget_tokens": 1000, "some_unknown_key": "value"}
    )
    assert result == {"cost_budget_tokens": 1000}


def test_normalize_policy_overrides_empty_dict():
    assert normalize_policy_overrides({}) == {}


@pytest.mark.parametrize(
    "overrides",
    [
        {"cost_budget_tokens": 0},
        {"cost_budget_tokens": -5},
        {"cost_budget_tokens": "lots"},
        {"cost_budget_tokens": 1.5},
        {"max_tool_calls": 0},
        {"max_tool_calls": -1},
        {"max_tool_calls": "many"},
        {"required_approval_gates": "not-a-list"},
        {"required_approval_gates": [1, 2]},
        {"required_approval_gates": [""]},
        "not-a-dict",
        ["also", "not", "a", "dict"],
        None,
    ],
)
def test_normalize_policy_overrides_invalid_raises(overrides):
    with pytest.raises(ValueError):
        normalize_policy_overrides(overrides)


# ---------------------------------------------------------------------------
# resolve_policy_layers
# ---------------------------------------------------------------------------


def test_resolve_policy_layers_server_only():
    server_caps = {
        "cost_budget_tokens": 200000,
        "max_tool_calls": 50,
        "required_approval_gates": ["Repository action"],
    }
    result = resolve_policy_layers(server_caps, None, None)

    assert result["effective"] == server_caps
    assert len(result["layers"]) == 2
    assert result["layers"][0] == {
        "scope": "server",
        "overrides": server_caps,
        "rejected": {},
    }
    assert result["layers"][1] == {
        "scope": "workspace",
        "overrides": {},
        "rejected": {},
    }


def test_resolve_policy_layers_workspace_tightens():
    server_caps = {
        "cost_budget_tokens": 200000,
        "max_tool_calls": 50,
        "required_approval_gates": [],
    }
    workspace_overrides = {"cost_budget_tokens": 100000}
    result = resolve_policy_layers(server_caps, workspace_overrides, None)

    assert result["effective"]["cost_budget_tokens"] == 100000
    assert result["effective"]["max_tool_calls"] == 50
    workspace_layer = result["layers"][1]
    assert workspace_layer["scope"] == "workspace"
    assert workspace_layer["overrides"] == {"cost_budget_tokens": 100000}
    assert workspace_layer["rejected"] == {}


def test_resolve_policy_layers_workspace_tries_to_loosen():
    server_caps = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }
    workspace_overrides = {"cost_budget_tokens": 200000}
    result = resolve_policy_layers(server_caps, workspace_overrides, None)

    # effective stays at the server's stricter value
    assert result["effective"]["cost_budget_tokens"] == 100000
    workspace_layer = result["layers"][1]
    assert workspace_layer["overrides"] == {"cost_budget_tokens": 200000}
    assert workspace_layer["rejected"] == {"cost_budget_tokens": 200000}


def test_resolve_policy_layers_session_further_tightens():
    server_caps = {
        "cost_budget_tokens": 200000,
        "max_tool_calls": 50,
        "required_approval_gates": [],
    }
    workspace_overrides = {"cost_budget_tokens": 100000}
    session_overrides = {"cost_budget_tokens": 50000, "max_tool_calls": 10}

    result = resolve_policy_layers(server_caps, workspace_overrides, session_overrides)

    assert result["effective"]["cost_budget_tokens"] == 50000
    assert result["effective"]["max_tool_calls"] == 10
    assert len(result["layers"]) == 3

    session_layer = result["layers"][2]
    assert session_layer["scope"] == "session"
    assert session_layer["overrides"] == {"cost_budget_tokens": 50000, "max_tool_calls": 10}
    assert session_layer["rejected"] == {}


def test_resolve_policy_layers_session_attempts_to_loosen_vs_workspace_effective():
    server_caps = {
        "cost_budget_tokens": 200000,
        "max_tool_calls": 50,
        "required_approval_gates": [],
    }
    # workspace tightens to 100000
    workspace_overrides = {"cost_budget_tokens": 100000}
    # session tries to loosen back up to 150000 (looser than workspace-effective 100000,
    # but still tighter than server's 200000)
    session_overrides = {"cost_budget_tokens": 150000}

    result = resolve_policy_layers(server_caps, workspace_overrides, session_overrides)

    # effective remains at the workspace-tightened value
    assert result["effective"]["cost_budget_tokens"] == 100000

    workspace_layer = result["layers"][1]
    assert workspace_layer["overrides"] == {"cost_budget_tokens": 100000}
    assert workspace_layer["rejected"] == {}

    session_layer = result["layers"][2]
    assert session_layer["overrides"] == {"cost_budget_tokens": 150000}
    assert session_layer["rejected"] == {"cost_budget_tokens": 150000}


def test_resolve_policy_layers_required_approval_gates_union_order():
    server_caps = {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": ["PRD/AC", "Repository action"],
    }
    workspace_overrides = {
        "required_approval_gates": ["Repository action", "Final handoff"],
    }
    session_overrides = {
        "required_approval_gates": ["Task graph", "PRD/AC"],
    }

    result = resolve_policy_layers(server_caps, workspace_overrides, session_overrides)

    assert result["effective"]["required_approval_gates"] == [
        "PRD/AC",
        "Repository action",
        "Final handoff",
        "Task graph",
    ]

    # No "rejected" entries arise from required_approval_gates merging.
    for layer in result["layers"]:
        assert layer["rejected"] == {} or set(layer["rejected"]) <= {
            "cost_budget_tokens",
            "max_tool_calls",
        }
    workspace_layer = result["layers"][1]
    assert workspace_layer["overrides"] == {
        "required_approval_gates": ["Repository action", "Final handoff"]
    }
    session_layer = result["layers"][2]
    assert session_layer["overrides"] == {"required_approval_gates": ["Task graph", "PRD/AC"]}


def test_resolve_policy_layers_workspace_overrides_none_treated_as_empty():
    server_caps = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 10,
        "required_approval_gates": ["PRD/AC"],
    }
    result = resolve_policy_layers(server_caps, None, {"cost_budget_tokens": 50000})

    assert len(result["layers"]) == 3
    assert result["layers"][1] == {
        "scope": "workspace",
        "overrides": {},
        "rejected": {},
    }
    assert result["effective"]["cost_budget_tokens"] == 50000


# ---------------------------------------------------------------------------
# caps_would_loosen
# ---------------------------------------------------------------------------


def test_caps_would_loosen_detects_loosened_numeric_caps():
    parent_effective = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 20,
        "required_approval_gates": ["PRD/AC"],
    }
    proposed = {"cost_budget_tokens": 200000, "max_tool_calls": 30}
    result = caps_would_loosen(parent_effective, proposed)
    assert result == {"cost_budget_tokens": 200000, "max_tool_calls": 30}


def test_caps_would_loosen_detects_single_loosened_cap():
    parent_effective = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 20,
        "required_approval_gates": [],
    }
    proposed = {"cost_budget_tokens": 50000, "max_tool_calls": 30}
    result = caps_would_loosen(parent_effective, proposed)
    assert result == {"max_tool_calls": 30}


def test_caps_would_loosen_none_loosens_against_capped_parent():
    parent_effective = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 20,
        "required_approval_gates": [],
    }
    proposed = {"cost_budget_tokens": None}
    result = caps_would_loosen(parent_effective, proposed)
    assert result == {"cost_budget_tokens": None}


def test_caps_would_loosen_only_tightening_returns_empty():
    parent_effective = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 20,
        "required_approval_gates": [],
    }
    proposed = {"cost_budget_tokens": 50000, "max_tool_calls": 10}
    assert caps_would_loosen(parent_effective, proposed) == {}


def test_caps_would_loosen_required_approval_gates_only_returns_empty():
    parent_effective = {
        "cost_budget_tokens": 100000,
        "max_tool_calls": 20,
        "required_approval_gates": ["PRD/AC"],
    }
    proposed = {"required_approval_gates": ["PRD/AC", "Final handoff"]}
    assert caps_would_loosen(parent_effective, proposed) == {}
