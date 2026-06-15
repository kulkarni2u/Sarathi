"""Service-layer tests for three-tier policy layering (T5.1)."""

from __future__ import annotations

import pytest

from src.service.errors import ServiceError
from src.service.policy_layers import (
    get_session_policy,
    get_workspace_policy,
    set_session_policy_overrides,
    set_workspace_policy_overrides,
)
from src.storage import Storage, connect, run_migrations


def _setup(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    storage = Storage(conn)
    return conn, storage


def _create_session(storage, tmp_path):
    workspace = storage.create_workspace(name="Policy WS", root_path=str(tmp_path))
    task = storage.create_task(workspace_id=workspace["id"], title="Policy task")
    session = storage.create_session(workspace_id=workspace["id"], task_id=task["id"], owner="alice")
    return workspace, task, session


# ---------------------------------------------------------------------------
# get_workspace_policy / set_workspace_policy_overrides
# ---------------------------------------------------------------------------


def test_get_workspace_policy_no_policy_pack(tmp_path):
    _, storage = _setup(tmp_path)
    workspace = storage.create_workspace(name="No Pack", root_path=str(tmp_path))

    result = get_workspace_policy(storage, workspace["id"])

    assert result["effective"] == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }
    assert len(result["layers"]) == 2
    assert result["layers"][0]["scope"] == "server"
    assert result["layers"][0]["overrides"] == result["effective"]
    assert result["layers"][1] == {"scope": "workspace", "overrides": {}, "rejected": {}}


def test_get_workspace_policy_nonexistent_raises_404(tmp_path):
    _, storage = _setup(tmp_path)

    with pytest.raises(ServiceError) as exc_info:
        get_workspace_policy(storage, "does-not-exist")

    assert exc_info.value.status == 404


def test_set_workspace_policy_overrides_tightens_cap(tmp_path):
    _, storage = _setup(tmp_path)
    workspace = storage.create_workspace(name="Tighten WS", root_path=str(tmp_path))

    result = set_workspace_policy_overrides(
        storage, workspace["id"], {"cost_budget_tokens": 50000}
    )

    assert result["effective"]["cost_budget_tokens"] == 50000
    workspace_layer = result["layers"][1]
    assert workspace_layer["overrides"] == {"cost_budget_tokens": 50000}
    assert workspace_layer["rejected"] == {}

    # Persisted: a fresh read reflects the override.
    persisted = get_workspace_policy(storage, workspace["id"])
    assert persisted["effective"]["cost_budget_tokens"] == 50000

    refreshed_workspace = storage.get_workspace(workspace["id"])
    assert refreshed_workspace["metadata"]["policy_overrides"] == {"cost_budget_tokens": 50000}


def test_set_workspace_policy_overrides_invalid_value_raises_400(tmp_path):
    _, storage = _setup(tmp_path)
    workspace = storage.create_workspace(name="Invalid WS", root_path=str(tmp_path))

    with pytest.raises(ServiceError) as exc_info:
        set_workspace_policy_overrides(storage, workspace["id"], {"cost_budget_tokens": 0})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_request"


def test_set_workspace_policy_overrides_nonexistent_raises_404(tmp_path):
    _, storage = _setup(tmp_path)

    with pytest.raises(ServiceError) as exc_info:
        set_workspace_policy_overrides(storage, "does-not-exist", {"cost_budget_tokens": 1000})

    assert exc_info.value.status == 404


def test_set_workspace_policy_overrides_merge_preserves_other_keys(tmp_path):
    _, storage = _setup(tmp_path)
    workspace = storage.create_workspace(name="Merge WS", root_path=str(tmp_path))

    set_workspace_policy_overrides(storage, workspace["id"], {"cost_budget_tokens": 50000})
    result = set_workspace_policy_overrides(storage, workspace["id"], {"max_tool_calls": 5})

    workspace_layer = result["layers"][1]
    assert workspace_layer["overrides"] == {"cost_budget_tokens": 50000, "max_tool_calls": 5}
    assert result["effective"]["cost_budget_tokens"] == 50000
    assert result["effective"]["max_tool_calls"] == 5


# ---------------------------------------------------------------------------
# get_session_policy / set_session_policy_overrides
# ---------------------------------------------------------------------------


def test_get_session_policy_no_overrides(tmp_path):
    _, storage = _setup(tmp_path)
    _workspace, _task, session = _create_session(storage, tmp_path)

    result = get_session_policy(storage, session["id"])

    assert result["effective"] == {
        "cost_budget_tokens": None,
        "max_tool_calls": None,
        "required_approval_gates": [],
    }
    assert len(result["layers"]) == 3
    assert [layer["scope"] for layer in result["layers"]] == ["server", "workspace", "session"]


def test_get_session_policy_nonexistent_raises_404(tmp_path):
    _, storage = _setup(tmp_path)

    with pytest.raises(ServiceError) as exc_info:
        get_session_policy(storage, "does-not-exist")

    assert exc_info.value.status == 404


def test_session_policy_reflects_workspace_tier_and_session_tightening(tmp_path):
    _, storage = _setup(tmp_path)
    workspace, _task, session = _create_session(storage, tmp_path)

    # Workspace tightens the cost budget cap.
    set_workspace_policy_overrides(storage, workspace["id"], {"cost_budget_tokens": 100000})

    session_policy = get_session_policy(storage, session["id"])
    assert session_policy["effective"]["cost_budget_tokens"] == 100000
    assert session_policy["layers"][1]["overrides"] == {"cost_budget_tokens": 100000}

    # Session tightens further.
    session_result = set_session_policy_overrides(
        storage, session["id"], {"cost_budget_tokens": 50000}
    )
    assert session_result["effective"]["cost_budget_tokens"] == 50000
    session_layer = session_result["layers"][2]
    assert session_layer["overrides"] == {"cost_budget_tokens": 50000}
    assert session_layer["rejected"] == {}

    # Persisted.
    persisted = get_session_policy(storage, session["id"])
    assert persisted["effective"]["cost_budget_tokens"] == 50000
    refreshed_session = storage.get_session(session["id"])
    assert refreshed_session["metadata"]["policy_overrides"] == {"cost_budget_tokens": 50000}


def test_set_session_policy_overrides_loosen_vs_workspace_raises_400(tmp_path):
    _, storage = _setup(tmp_path)
    workspace, _task, session = _create_session(storage, tmp_path)

    # Workspace tightens to 100000.
    set_workspace_policy_overrides(storage, workspace["id"], {"cost_budget_tokens": 100000})

    # Session attempts to loosen back up to 200000 - rejected.
    with pytest.raises(ServiceError) as exc_info:
        set_session_policy_overrides(storage, session["id"], {"cost_budget_tokens": 200000})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "policy_violation"


def test_set_session_policy_overrides_invalid_value_raises_400(tmp_path):
    _, storage = _setup(tmp_path)
    _workspace, _task, session = _create_session(storage, tmp_path)

    with pytest.raises(ServiceError) as exc_info:
        set_session_policy_overrides(storage, session["id"], {"max_tool_calls": -1})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_request"


def test_set_session_policy_overrides_nonexistent_raises_404(tmp_path):
    _, storage = _setup(tmp_path)

    with pytest.raises(ServiceError) as exc_info:
        set_session_policy_overrides(storage, "does-not-exist", {"cost_budget_tokens": 1000})

    assert exc_info.value.status == 404
