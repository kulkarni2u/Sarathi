"""Tests for the OpenAPI 3.1 contract generator."""

from __future__ import annotations

from src.service import create_app
from src.service.openapi import build_openapi_spec


def test_build_openapi_spec_top_level_keys():
    spec = build_openapi_spec()

    assert spec["openapi"] == "3.1.0"
    assert "info" in spec
    assert spec["info"]["title"] == "Sarathi Service API"
    assert "version" in spec["info"]
    assert "paths" in spec


def test_known_paths_present():
    spec = build_openapi_spec()
    paths = spec["paths"]

    expected_paths = [
        "/health",
        "/workspaces",
        "/workspaces/{id}",
        "/workspaces/{id}/tasks",
        "/workspaces/{id}/task-dashboard",
        "/workspaces/{id}/operational-views",
        "/workspaces/{id}/wiki",
        "/workspaces/{id}/wiki/{page}",
        "/workspaces/{id}/proposals",
        "/workspaces/{id}/proposals/{proposal_id}",
        "/tasks/{id}",
        "/tasks/{id}/graph",
        "/tasks/{id}/messages",
        "/tasks/{id}/approve",
        "/subtasks/{id}/transition",
        "/subtasks/{id}/dispatch",
        "/brainstorm/sessions",
        "/brainstorm/{id}",
        "/chat",
        "/events",
    ]

    for path in expected_paths:
        assert path in paths, f"missing path: {path}"


def test_every_path_has_at_least_one_method():
    spec = build_openapi_spec()

    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for path, path_item in spec["paths"].items():
        methods = [key for key in path_item if key in http_methods]
        assert methods, f"path {path} has no HTTP methods defined"


def test_specific_method_coverage():
    spec = build_openapi_spec()
    paths = spec["paths"]

    assert "get" in paths["/health"]
    assert "get" in paths["/workspaces"]
    assert "post" in paths["/workspaces"]
    assert "get" in paths["/workspaces/{id}"]
    assert "patch" in paths["/workspaces/{id}"]
    assert "get" in paths["/workspaces/{id}/tasks"]
    assert "post" in paths["/workspaces/{id}/tasks"]


def test_openapi_spec_validator_if_available():
    try:
        from openapi_spec_validator import validate
    except ImportError:
        import pytest

        pytest.skip("openapi_spec_validator not installed")
        return

    spec = build_openapi_spec()
    validate(spec)


def test_openapi_json_route_returns_unwrapped_document(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, payload = app.handle(
        "GET",
        "/openapi.json",
        headers={"x-correlation-id": "corr-openapi"},
    )

    assert status == 200
    # The document must be returned as-is at the top level (not wrapped in
    # the {"ok": ..., "data": ...} success envelope) so it is a valid
    # OpenAPI document for tooling that fetches it directly.
    assert "ok" not in payload
    assert "data" not in payload
    assert payload["openapi"] == "3.1.0"
    assert "info" in payload
    assert "paths" in payload
    assert payload == build_openapi_spec()


def test_docs_route_points_at_openapi_json(tmp_path):
    app = create_app(tmp_path / "sarathi.db")

    status, payload = app.handle(
        "GET",
        "/docs",
        headers={"x-correlation-id": "corr-docs"},
    )

    assert status == 200
    assert payload["openapi_url"] == "/openapi.json"
