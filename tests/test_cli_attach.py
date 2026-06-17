"""Tests for the `sarathi attach` CLI command (T4.1 wave 3)."""
import argparse
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import src.cli as cli


def _make_args(share_token="tok", user="alice", role="observer"):
    return argparse.Namespace(share_token=share_token, user=user, role=role)


def test_attach_no_service_prints_hint(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    called = {"post": False}

    def _fake_post(*args, **kwargs):
        called["post"] = True
        raise AssertionError("_service_post_json should not be called when no service")

    monkeypatch.setattr(cli, "_service_post_json", _fake_post)

    cli.handle_attach(_make_args())

    out = capsys.readouterr().out
    assert "No running Sarathi service found" in out
    assert "python3 -m src.service" in out
    assert called["post"] is False


def test_attach_success_prints_session_and_participants(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: None)

    def _fake_post(service_url, path, body, *, token=None):
        assert path == "/api/sessions/attach"
        assert body["share_token"] == "tok"
        assert body["user"] == "alice"
        return {
            "session": {
                "id": "sess-1",
                "task_id": "task-99",
                "visibility": "shared",
            },
            "participant": {"user": "alice", "role": "driver"},
        }

    def _fake_get(service_url, path, *, token=None):
        if path == "/api/sessions/sess-1":
            return {
                "participants": [
                    {"user": "alice", "role": "driver", "status": "active"},
                    {"user": "bob", "role": "observer", "status": "active"},
                ]
            }
        if path == "/api/sessions/sess-1/messages":
            return {"messages": [{"role": "user", "content": "hello world"}]}
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(cli, "_service_post_json", _fake_post)
    monkeypatch.setattr(cli, "_service_get_json", _fake_get)

    cli.handle_attach(_make_args(role="driver"))

    out = capsys.readouterr().out
    assert "sess-1" in out
    assert "task-99" in out
    assert "driver" in out
    assert "alice" in out
    assert "bob" in out
    assert "hello world" in out


def test_attach_observer_note(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: None)

    def _fake_post(service_url, path, body, *, token=None):
        return {
            "session": {"id": "s2", "task_id": "t2", "visibility": "shared"},
            "participant": {"user": "alice", "role": "observer"},
        }

    def _fake_get(service_url, path, *, token=None):
        if path.endswith("/messages"):
            return {"messages": []}
        return {"participants": []}

    monkeypatch.setattr(cli, "_service_post_json", _fake_post)
    monkeypatch.setattr(cli, "_service_get_json", _fake_get)

    cli.handle_attach(_make_args(role="observer"))

    out = capsys.readouterr().out
    assert "read-only" in out
    assert "(no messages yet)" in out


def test_attach_error_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_read_service_discovery", lambda: {"url": "http://svc"}
    )
    monkeypatch.setattr(cli, "_service_auth_token", lambda info: None)

    def _fake_post(service_url, path, body, *, token=None):
        raise RuntimeError("Session is closed.")

    monkeypatch.setattr(cli, "_service_post_json", _fake_post)

    # Should not raise
    cli.handle_attach(_make_args())

    out = capsys.readouterr().out
    assert "Could not attach" in out
    assert "Session is closed." in out


@contextmanager
def _stub_post_server(ok=True):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            if ok:
                payload = {"ok": True, "data": {"hello": "world"}}
                status = 200
            else:
                payload = {"ok": False, "error": {"message": "nope"}}
                status = 200
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, server
    finally:
        server.shutdown()
        server.server_close()


def test_service_post_json_round_trip():
    with _stub_post_server(ok=True) as (base_url, _server):
        result = cli._service_post_json(base_url, "/x", {"a": 1})
        assert result == {"hello": "world"}

    with _stub_post_server(ok=False) as (base_url, _server):
        with pytest.raises(RuntimeError) as excinfo:
            cli._service_post_json(base_url, "/x", {"a": 1})
        assert "nope" in str(excinfo.value)
