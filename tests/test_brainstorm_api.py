from src.service import create_app
from tests.test_service_api import assert_ok, assert_error, request


def make_app_with_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, data = assert_ok(request(app, "POST", "/api/workspaces", {
        "name": "Test WS", "root_path": str(tmp_path),
    }))
    return app, data["workspace"]


def test_brainstorm_session_can_be_created(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    status, data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Add OAuth2 login",
    }))
    assert status == 200
    assert data["session"]["id"]
    assert data["session"]["title"] == "Add OAuth2 login"
    assert data["session"]["status"] == "active"


def test_brainstorm_session_can_be_retrieved(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    status, data = assert_ok(request(app, "GET", f"/api/brainstorm/{session_id}"))
    assert data["session"]["id"] == session_id


def test_brainstorm_turn_can_be_appended(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/turns", {
        "role": "sarathi", "content": "Which auth approach?", "options": ["JWT", "Sessions"],
    }))
    assert len(data["session"]["dialogue_turns"]) == 1
    assert data["session"]["dialogue_turns"][0]["content"] == "Which auth approach?"


def test_brainstorm_turn_spec_update_is_applied(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    _, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/turns", {
        "role": "sarathi", "content": "Q", "spec_update": "## Goal\nDo the thing",
    }))
    assert data["session"]["spec_content"] == "## Goal\nDo the thing"


def test_brainstorm_research_can_be_appended(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/research", {
        "agent": "Vichara", "type": "codebase", "summary": "Found src/auth.py",
    }))
    assert len(data["session"]["research_findings"]) == 1
    assert data["session"]["research_findings"][0]["agent"] == "Vichara"


def test_brainstorm_session_can_be_approved(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    request(app, "POST", f"/api/brainstorm/{session_id}/turns", {
        "role": "sarathi", "content": "Q", "spec_update": "## Goal\nDo the thing",
    })
    status, data = assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/approve", {}))
    assert data["session"]["status"] == "approved"
    assert data["session"]["approved_at"] is not None
    assert data["task"]["id"]
    assert data["task"]["title"] == "Test"


def test_brainstorm_double_approve_returns_409(tmp_path):
    app, ws = make_app_with_workspace(tmp_path)
    _, create_data = assert_ok(request(app, "POST", "/api/brainstorm/sessions", {
        "workspace_id": ws["id"], "title": "Test",
    }))
    session_id = create_data["session"]["id"]
    assert_ok(request(app, "POST", f"/api/brainstorm/{session_id}/approve", {}))
    assert_error(
        request(app, "POST", f"/api/brainstorm/{session_id}/approve", {}),
        status=409, code="conflict",
    )


def test_brainstorm_session_not_found_returns_404(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    assert_error(
        request(app, "GET", "/api/brainstorm/nonexistent"),
        status=404, code="not_found",
    )
