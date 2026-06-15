"""Service-layer tests for session sharing & co-drive (T4.1, wave 2)."""

from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-sessions-service"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-sessions-service"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-sessions-service"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def create_workspace(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    return workspace_data["workspace"]


def create_task(app, tmp_path):
    workspace = create_workspace(app, tmp_path)
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/task-drafts",
            {"prompt": "Co-drive a session.", "title": "Session task"},
        )
    )
    return draft_data["task"]


def create_session(app, tmp_path, *, owner="local"):
    task = create_task(app, tmp_path)
    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/sessions",
            {"owner": owner},
        )
    )
    assert status == 201
    return task, data["session"]


def test_create_session_for_task_has_share_token_and_owner_participant(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task, session = create_session(app, tmp_path, owner="alice")

    assert session["share_token"]
    assert session["owner"] == "alice"
    assert session["visibility"] == "private"
    assert session["status"] == "active"

    status, data = assert_ok(request(app, "GET", f"/api/sessions/{session['id']}"))
    assert status == 200
    participants = data["participants"]
    assert len(participants) == 1
    assert participants[0]["user"] == "alice"
    assert participants[0]["role"] == "owner"
    assert participants[0]["status"] == "active"


def test_attach_via_share_token_adds_observer(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    status, data = assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob"},
        )
    )
    assert status == 201
    assert data["session"]["id"] == session["id"]
    assert data["participant"]["user"] == "bob"
    assert data["participant"]["role"] == "observer"

    _, participants_data = assert_ok(
        request(app, "GET", f"/api/sessions/{session['id']}/participants")
    )
    users = {p["user"]: p["role"] for p in participants_data["participants"]}
    assert users == {"alice": "owner", "bob": "observer"}


def test_two_participants_with_distinct_roles(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob", "role": "observer"},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "carol", "role": "driver"},
        )
    )

    _, participants_data = assert_ok(
        request(app, "GET", f"/api/sessions/{session['id']}/participants")
    )
    roles = {p["user"]: p["role"] for p in participants_data["participants"]}
    assert roles == {"alice": "owner", "bob": "observer", "carol": "driver"}


def test_observer_cannot_post_but_driver_can(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")
    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob", "role": "observer"},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "carol", "role": "driver"},
        )
    )

    assert_error(
        request(
            app,
            "POST",
            f"/api/sessions/{session['id']}/messages",
            {"user": "bob", "content": "I should be blocked."},
        ),
        status=403,
        code="forbidden",
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/sessions/{session['id']}/messages",
            {"user": "carol", "content": "Driver message."},
        )
    )
    assert status == 201
    assert data["message"]["content"] == "Driver message."

    _, messages_data = assert_ok(
        request(app, "GET", f"/api/sessions/{session['id']}/messages")
    )
    contents = [m["content"] for m in messages_data["messages"]]
    assert "Driver message." in contents


def test_non_participant_cannot_post(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    assert_error(
        request(
            app,
            "POST",
            f"/api/sessions/{session['id']}/messages",
            {"user": "stranger", "content": "Hi."},
        ),
        status=403,
        code="forbidden",
    )


def test_leave_session_marks_participant_left(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")
    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob", "role": "observer"},
        )
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/sessions/{session['id']}/leave",
            {"user": "bob"},
        )
    )
    assert status == 200
    assert data["participant"]["user"] == "bob"
    assert data["participant"]["status"] == "left"


def test_leave_missing_participant_is_not_found(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    assert_error(
        request(
            app,
            "POST",
            f"/api/sessions/{session['id']}/leave",
            {"user": "ghost"},
        ),
        status=404,
        code="not_found",
    )


def test_participation_events_logged(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task, session = create_session(app, tmp_path, owner="alice")
    assert_ok(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob", "role": "driver"},
        )
    )

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    event_types = [event["event_type"] for event in studio_data["events"]]
    assert "session.created" in event_types
    assert "session.participant_joined" in event_types


def test_update_session_visibility(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    status, data = assert_ok(
        request(
            app,
            "PATCH",
            f"/api/sessions/{session['id']}",
            {"visibility": "link"},
        )
    )
    assert status == 200
    assert data["session"]["visibility"] == "link"

    _, get_data = assert_ok(request(app, "GET", f"/api/sessions/{session['id']}"))
    assert get_data["session"]["visibility"] == "link"


def test_attach_to_closed_session_conflicts(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, session = create_session(app, tmp_path, owner="alice")

    assert_ok(
        request(
            app,
            "PATCH",
            f"/api/sessions/{session['id']}",
            {"status": "closed"},
        )
    )

    assert_error(
        request(
            app,
            "POST",
            "/api/sessions/attach",
            {"share_token": session["share_token"], "user": "bob"},
        ),
        status=409,
        code="conflict",
    )
