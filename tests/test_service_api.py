import http.client
import json
import threading
from urllib.parse import urlparse

import pytest

from src.service import create_app, create_http_server


def request(app, method, path, body=None, correlation_id="corr-test"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-test"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    assert "error" not in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-test"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code
    assert payload["error"]["status"] == status
    assert payload["error"]["message"]
    assert "data" not in payload


def test_health_returns_ok_with_correlation_id(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, data = assert_ok(request(app, "GET", "/api/health"))

    assert status == 200
    assert data == {"status": "ok"}


def test_workspace_lifecycle_is_persisted_without_touching_repo_paths(tmp_path):
    db_path = tmp_path / "state" / "sarathi.db"
    root_path = tmp_path / "repo-that-service-must-not-create"
    app = create_app(db_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Pravaha UI", "root_path": str(root_path)},
        )
    )
    assert status == 201
    assert data["workspace"]["id"]
    assert data["workspace"]["name"] == "Pravaha UI"
    assert data["workspace"]["root_path"] == str(root_path)
    assert not root_path.exists()

    status, data = assert_ok(request(create_app(db_path), "GET", "/api/workspaces"))
    assert status == 200
    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["name"] == "Pravaha UI"


def test_task_lifecycle_for_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]

    status, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {
                "title": "Create service boundary",
                "description": "Expose minimal stdlib local API.",
            },
        )
    )
    assert status == 201
    task = task_data["task"]
    assert task["workspace_id"] == workspace_id
    assert task["title"] == "Create service boundary"
    assert task["status"] == "pending"

    status, get_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}"))
    assert status == 200
    assert get_data["task"] == task

    status, list_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/tasks"))
    assert status == 200
    assert list_data["tasks"] == [task]


def test_workspace_and_placeholder_task_resources(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace = workspace_data["workspace"]
    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/tasks",
            {"title": "Future orchestration"},
        )
    )
    task = task_data["task"]

    assert_ok(request(app, "GET", f"/api/workspaces/{workspace['id']}"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/graph"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/evidence"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/reviews"))
    assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/handoff"))
    assert_ok(request(app, "GET", f"/api/providers?workspace_id={workspace['id']}"))
    assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace['id']}"))


def test_approval_endpoint_persists_gate_and_event(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sutra", "root_path": "/tmp/sutra"},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, task_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/tasks",
            {"title": "Approve graph"},
        )
    )
    task_id = task_data["task"]["id"]

    status, approval_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task_id}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )

    assert status == 201
    approval = approval_data["approval_gate"]
    assert approval["id"]
    assert approval["workspace_id"] == workspace_id
    assert approval["task_id"] == task_id
    assert approval["status"] == "approved"

    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    assert events_data["events"]
    assert events_data["events"][-1]["object_id"] == approval["id"]


def test_http_sse_stream_returns_persisted_events(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        _, workspace_data = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            body={"name": "Sutra", "root_path": "/tmp/sutra"},
        )
        workspace_id = workspace_data["data"]["workspace"]["id"]

        status, headers, body = http_raw(
            "GET",
            f"{base_url}/api/events/stream?workspace_id={workspace_id}",
            token="secret",
        )

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert "event: snapshot" in body
        assert "workspace.created" in body


def test_http_sse_stream_accepts_query_token_for_browser_eventsource(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        _, workspace_data = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            body={"name": "Sutra", "root_path": "/tmp/sutra"},
        )
        workspace_id = workspace_data["data"]["workspace"]["id"]

        status, headers, body = http_raw(
            "GET",
            f"{base_url}/api/events/stream?workspace_id={workspace_id}&token=secret",
        )

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert "event: snapshot" in body
        assert "workspace.created" in body


def test_errors_are_typed_and_include_correlation_id(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    assert_error(
        request(app, "GET", "/api/tasks/missing", correlation_id="corr-missing"),
        status=404,
        code="not_found",
        correlation_id="corr-missing",
    )
    assert_error(
        request(app, "POST", "/api/workspaces", {"name": "No Root"}),
        status=400,
        code="invalid_request",
    )
    assert_error(
        request(app, "DELETE", "/api/workspaces"),
        status=404,
        code="not_found",
    )


def test_callable_api_requires_token_when_configured(tmp_path):
    app = create_app(tmp_path / "sarathi.db", token="secret")

    assert_error(
        app.handle("GET", "/api/health", headers={"x-correlation-id": "corr-auth"}),
        status=401,
        code="unauthorized",
        correlation_id="corr-auth",
    )

    status, data = assert_ok(
        app.handle(
            "GET",
            "/api/health",
            headers={
                "authorization": "Bearer secret",
                "x-correlation-id": "corr-authorized",
            },
        ),
        correlation_id="corr-authorized",
    )
    assert status == 200
    assert data == {"status": "ok"}


def test_http_server_requires_token_and_returns_json(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, unauthorized = http_json("GET", f"{base_url}/api/health")
        assert status == 401
        assert unauthorized["ok"] is False
        assert unauthorized["error"]["code"] == "unauthorized"

        status, payload = http_json(
            "GET",
            f"{base_url}/api/health",
            token="secret",
            correlation_id="corr-http",
        )
        assert status == 200
        assert payload["ok"] is True
        assert payload["correlation_id"] == "corr-http"
        assert payload["data"] == {"status": "ok"}


def test_http_server_rejects_invalid_json(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            raw_body=b"{bad json",
        )
        assert status == 400
        assert payload["error"]["code"] == "invalid_json"


def test_http_server_returns_json_for_unsupported_methods(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json("DELETE", f"{base_url}/api/workspaces", token="secret")

        assert status == 404
        assert payload["ok"] is False
        assert payload["error"]["code"] == "not_found"


def test_http_server_supports_browser_cors_preflight(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, headers, body = http_raw(
            "OPTIONS",
            f"{base_url}/api/workspaces",
            correlation_id="corr-preflight",
            extra_headers={
                "origin": "http://127.0.0.1:5173",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization, content-type",
            },
        )

        assert status == 204
        assert body == ""
        assert headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert "POST" in headers["access-control-allow-methods"]
        assert "authorization" in headers["access-control-allow-headers"].lower()


def test_http_server_adds_cors_headers_to_json_responses(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, headers, payload = http_json_with_headers(
            "GET",
            f"{base_url}/api/health",
            token="secret",
            extra_headers={"origin": "http://127.0.0.1:5173"},
        )

        assert status == 200
        assert payload["ok"] is True
        assert headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_http_server_rejects_oversized_body(tmp_path):
    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        status, payload = http_json(
            "POST",
            f"{base_url}/api/workspaces",
            token="secret",
            raw_body=b"{" + (b" " * 70_000) + b"}",
        )

        assert status == 413
        assert payload["error"]["code"] == "request_too_large"


class running_server:
    def __init__(self, db_path, token):
        self.server = create_http_server(db_path=db_path, token=token, host="127.0.0.1", port=0)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def http_json(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    status, _headers, body_text = http_raw(
        method,
        url,
        token=token,
        body=body,
        raw_body=raw_body,
        correlation_id=correlation_id,
        extra_headers=extra_headers,
    )
    return status, json.loads(body_text)


def http_json_with_headers(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    status, headers, body_text = http_raw(
        method,
        url,
        token=token,
        body=body,
        raw_body=raw_body,
        correlation_id=correlation_id,
        extra_headers=extra_headers,
    )
    return status, headers, json.loads(body_text)


def http_raw(
    method,
    url,
    *,
    token=None,
    body=None,
    raw_body=None,
    correlation_id="corr-http",
    extra_headers=None,
):
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    data = raw_body if raw_body is not None else None
    if data is None and body is not None:
        data = json.dumps(body).encode("utf-8")
    headers = {"x-correlation-id": correlation_id}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if body is not None or raw_body is not None:
        headers["content-type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    try:
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")
    finally:
        connection.close()
