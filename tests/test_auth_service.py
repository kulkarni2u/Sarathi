"""Service-layer tests for opt-in multi-user auth (T4.3, wave 2)."""

from src.service import create_app


ADMIN = "admin-token"


def request(app, method, path, body=None, *, token=None, correlation_id="corr-auth"):
    headers = {"x-correlation-id": correlation_id}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return app.handle(method, path, body=body, headers=headers)


def assert_ok(response, correlation_id="corr-auth"):
    status, payload = response
    assert payload["ok"] is True, payload
    assert payload["correlation_id"] == correlation_id
    return status, payload["data"]


def _auth_app(tmp_path):
    return create_app(tmp_path / "sarathi.db", token=ADMIN, auth_enabled=True)


def _workspace_and_task(app):
    _, ws = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "W", "root_path": "/tmp/x"}, token=ADMIN)
    )
    _, draft = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{ws['workspace']['id']}/task-drafts",
            {"prompt": "auth task", "title": "Auth task"},
            token=ADMIN,
        )
    )
    return draft["task"]


# --- auth OFF (default) is unchanged ---------------------------------------

def test_auth_off_shared_token_still_works(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="shared", auth_enabled=False)
    status, payload = request(app, "GET", "/api/workspaces", token="shared")
    assert status == 200 and payload["ok"] is True


def test_auth_off_rejects_bad_token(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="shared", auth_enabled=False)
    status, payload = request(app, "GET", "/api/workspaces", token="wrong")
    assert status == 401 and payload["ok"] is False


# --- auth ON: principal required -------------------------------------------

def test_auth_on_requires_a_valid_principal(tmp_path):
    app = _auth_app(tmp_path)
    # No token at all -> 401.
    status, payload = request(app, "GET", "/api/workspaces")
    assert status == 401 and payload["ok"] is False
    # A bogus token -> 401.
    status, _ = request(app, "GET", "/api/workspaces", token="nope")
    assert status == 401


def test_auth_on_admin_token_works(tmp_path):
    app = _auth_app(tmp_path)
    status, payload = request(app, "GET", "/api/workspaces", token=ADMIN)
    assert status == 200 and payload["ok"] is True


def test_admin_can_provision_user_who_can_then_authenticate(tmp_path):
    app = _auth_app(tmp_path)
    status, data = assert_ok(
        request(app, "POST", "/api/users", {"username": "bob"}, token=ADMIN)
    )
    assert status == 201
    bob_token = data["user"]["token"]
    assert bob_token
    # Bob can now call the API with his own token.
    status, payload = request(app, "GET", "/api/workspaces", token=bob_token)
    assert status == 200 and payload["ok"] is True


def test_non_admin_cannot_provision_users(tmp_path):
    app = _auth_app(tmp_path)
    _, data = assert_ok(request(app, "POST", "/api/users", {"username": "carol"}, token=ADMIN))
    carol_token = data["user"]["token"]
    status, payload = request(
        app, "POST", "/api/users", {"username": "dave"}, token=carol_token
    )
    assert status == 403 and payload["ok"] is False


def test_duplicate_username_conflicts(tmp_path):
    app = _auth_app(tmp_path)
    assert_ok(request(app, "POST", "/api/users", {"username": "eve"}, token=ADMIN))
    status, payload = request(app, "POST", "/api/users", {"username": "eve"}, token=ADMIN)
    assert status == 409 and payload["ok"] is False


def test_auth_on_observer_cannot_post_by_spoofing_actor(tmp_path):
    """With auth on, the actor is the authenticated principal, so an observer
    cannot post by claiming a driver's user id in the body."""
    app = _auth_app(tmp_path)
    # Provision two users.
    _, obs = assert_ok(request(app, "POST", "/api/users", {"username": "observer1"}, token=ADMIN))
    observer_token = obs["user"]["token"]
    _, drv = assert_ok(request(app, "POST", "/api/users", {"username": "driver1"}, token=ADMIN))

    # Owner (admin) creates a session and adds the two participants.
    task = _workspace_and_task(app)
    _, sess = assert_ok(
        request(app, "POST", f"/api/tasks/{task['id']}/sessions", {"owner": "owner1"}, token=ADMIN)
    )
    session_id = sess["session"]["id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/sessions/{session_id}/participants",
            {"user": "observer1", "role": "observer"},
            token=ADMIN,
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            f"/api/sessions/{session_id}/participants",
            {"user": "driver1", "role": "driver"},
            token=ADMIN,
        )
    )

    # Observer tries to post while spoofing the driver's user id in the body.
    status, payload = request(
        app,
        "POST",
        f"/api/sessions/{session_id}/messages",
        {"user": "driver1", "content": "sneaky"},
        token=observer_token,
    )
    assert status == 403 and payload["ok"] is False
