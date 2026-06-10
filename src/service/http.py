"""HTTP server, request handler, and small request-parsing helpers."""

from __future__ import annotations

import json
import os
import socketserver
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .app import create_app
from .errors import (
    MAX_BODY_BYTES,
    ServiceError,
    _correlation_id,
    _error,
    _first_query,
    _path_parts,
    _query,
)

_ALLOWED_BROWSER_HOSTS = {"127.0.0.1", "localhost"}


def create_http_server(
    *,
    db_path: str | Path,
    token: str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    resolved_db_path = Path(db_path).expanduser().resolve()
    app = create_app(resolved_db_path, token=token)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_OPTIONS(self) -> None:
            self.send_response(204, "No Content")
            self._write_cors_headers()
            self.send_header("content-length", "0")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_DELETE(self) -> None:
            self._handle()

        def do_PATCH(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self) -> None:
            # No loopback auth bypass: on shared machines or containers any
            # local process (or a browser via a permitted localhost origin)
            # can reach 127.0.0.1, so the bearer token is always required.
            if self.command == "GET" and _path_parts(self.path) == ["api", "events", "stream"]:
                self._handle_sse()
                return

            body, error = self._read_json_body()
            if error is not None:
                correlation_id = _correlation_id(self.headers)
                self._write_json(error.status, _error(error, correlation_id))
                return

            status, payload = app.handle(
                self.command,
                self.path,
                body=body,
                headers=dict(self.headers.items()),
            )
            self._write_json(status, payload)

        def _handle_sse(self) -> None:
            correlation_id = _correlation_id(self.headers)
            try:
                app._authorize_stream(dict(self.headers.items()), _query(self.path))
                status, data = app._route("GET", ["api", "events"], _query(self.path), {})
                payload = json.dumps(data, sort_keys=True)
                self.send_response(status, HTTPStatus(status).phrase)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "keep-alive")
                self.send_header("x-accel-buffering", "no")
                self._write_cors_headers()
                self.end_headers()
                last_payload = payload
                try:
                    self._write_sse_snapshot(payload)
                    while True:
                        time.sleep(2.0)
                        try:
                            _, next_data = app._route("GET", ["api", "events"], _query(self.path), {})
                        except ServiceError:
                            break
                        next_payload = json.dumps(next_data, sort_keys=True)
                        if next_payload != last_payload:
                            self._write_sse_snapshot(next_payload)
                            last_payload = next_payload
                        else:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            except ServiceError as error:
                self._write_json(error.status, _error(error, correlation_id))

        def _write_sse_snapshot(self, payload: str) -> None:
            encoded = f"event: snapshot\ndata: {payload}\n\n".encode("utf-8")
            self.wfile.write(encoded)
            self.wfile.flush()

        def _read_json_body(self) -> tuple[dict[str, Any] | None, ServiceError | None]:
            try:
                length = int(self.headers.get("content-length") or "0")
            except ValueError:
                return None, ServiceError("invalid_request", "Content-Length must be numeric.", 400)
            if length > MAX_BODY_BYTES:
                return None, ServiceError("request_too_large", "Request body is too large.", 413)
            if length == 0:
                return None, None
            try:
                decoded = self.rfile.read(length).decode("utf-8")
                payload = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, ServiceError("invalid_json", "Request body must be valid JSON.", 400)
            if not isinstance(payload, dict):
                return None, ServiceError("invalid_request", "Request body must be a JSON object.", 400)
            return payload, None

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status, HTTPStatus(status).phrase)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.send_header("connection", "close")
            self._write_cors_headers()
            self.end_headers()
            self.wfile.write(encoded)
            self.close_connection = True

        def _write_cors_headers(self) -> None:
            origin = self.headers.get("origin")
            allowed_origin = origin if _browser_origin_allowed(origin) else "http://127.0.0.1:5173"
            self.send_header("access-control-allow-origin", allowed_origin)
            self.send_header("vary", "Origin")
            self.send_header("access-control-allow-methods", "GET, POST, DELETE, PATCH, PUT, OPTIONS")
            self.send_header(
                "access-control-allow-headers",
                "authorization, content-type, x-correlation-id",
            )

    class LocalThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

        def server_bind(self) -> None:
            # HTTPServer.server_bind performs a reverse DNS lookup for server_name,
            # which can stall local desktop startup on some macOS resolver setups.
            socketserver.TCPServer.server_bind(self)
            host, bound_port = self.server_address[:2]
            self.server_name = str(host)
            self.server_port = int(bound_port)
            _write_service_discovery(
                str(host),
                int(bound_port),
                token=token,
                db_path=resolved_db_path,
            )

        def server_close(self) -> None:
            super().server_close()
            _delete_service_discovery()

    return LocalThreadingHTTPServer((host, port), Handler)


def _browser_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.hostname in _ALLOWED_BROWSER_HOSTS


def _service_discovery_path() -> Path:
    return Path.home() / ".sarathi" / "service.json"


def _write_service_discovery(host: str, port: int, *, token: str, db_path: Path) -> None:
    try:
        discovery = _service_discovery_path()
        discovery.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "url": f"http://{host}:{port}",
                "host": host,
                "port": port,
                "auth": {"type": "bearer", "token": token},
                "db_path": str(db_path),
            },
            indent=2,
        )
        # The file holds the bearer token: create it 0600 from the start and
        # rename into place so it is never readable by others or seen partial.
        staging = discovery.with_name(discovery.name + ".tmp")
        staging.unlink(missing_ok=True)
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(staging, discovery)
        finally:
            staging.unlink(missing_ok=True)
    except Exception:
        pass


def _delete_service_discovery() -> None:
    try:
        _service_discovery_path().unlink(missing_ok=True)
    except Exception:
        pass
