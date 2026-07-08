"""Tests for the GitHub issue-as-queue label sync and audit-trail PR body.

Covers docs/IMPLEMENTATION-PLAN.md item 3.3:
- POST /workspaces/{id}/github/issues/sync (label-driven, idempotent)
- src/pr_body.build_pr_body (engine-shape + service-shape task normalization)
- src/pr_body.create_pr_if_gh_available (best-effort `gh pr create` shell-out)
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from src.pr_body import build_pr_body, create_pr_if_gh_available
from src.service import create_app


def request(app, method, path, body=None, correlation_id="corr-issue-queue"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-issue-queue"):
    status, payload = response
    assert payload["ok"] is True, payload
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-issue-queue"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code
    return payload


class _FakeGithubResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class _FakeGithubOpener:
    """Records every request it serves; returns a canned issue list."""

    def __init__(self, issues):
        self.issues = issues
        self.calls: list[urllib.request.Request] = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        return _FakeGithubResponse(self.issues)


def _make_workspace_with_repo(tmp_path, remote_url="https://github.com/octo/sarathi.git"):
    app = create_app(tmp_path / "sarathi.db")
    _, workspace_data = assert_ok(
        request(app, "POST", "/api/workspaces", {"name": "Sarathi App", "root_path": str(tmp_path)})
    )
    workspace_id = workspace_data["workspace"]["id"]
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _, repo_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {"path": str(repo_path), "approved": True, "remote_url": remote_url},
        )
    )
    return app, workspace_id, repo_data["repository"]


# ---------------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------------


def test_sync_creates_task_draft_for_each_open_labeled_issue(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener(
        [
            {"number": 10, "title": "Fix the thing", "html_url": "https://github.com/octo/sarathi/issues/10"},
            {"number": 11, "title": "Add the other thing", "html_url": "https://github.com/octo/sarathi/issues/11"},
        ]
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    status, data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"})
    )

    assert status == 200
    assert data["repository"] == "octo/sarathi"
    assert data["label"] == "sarathi"
    assert len(data["created"]) == 2
    assert data["skipped"] == []
    numbers = {entry["task"]["metadata"]["github_issue"]["number"] for entry in data["created"]}
    assert numbers == {10, 11}
    for entry in data["created"]:
        task = entry["task"]
        assert task["status"] == "prd_pending"
        assert task["metadata"]["source"] == "github_issue"
        assert task["metadata"]["github_issue"]["full_name"] == "octo/sarathi"
        assert entry["approval_gate"]["name"] == "PRD/AC"
        assert len(entry["messages"]) == 2

    # Lifecycle events emitted through the normal draft-creation path.
    _, events_data = assert_ok(request(app, "GET", f"/api/events?workspace_id={workspace_id}"))
    event_types = [event["event_type"] for event in events_data["events"]]
    assert event_types.count("task.draft_created") == 2
    assert event_types.count("approval.requested") == 2

    # The request actually carried the label filter and no auth header
    # (GITHUB_TOKEN unset).
    assert len(opener.calls) == 1
    sent_request = opener.calls[0]
    assert "labels=sarathi" in sent_request.full_url
    assert "state=open" in sent_request.full_url
    assert sent_request.get_header("Authorization") is None


def test_sync_is_idempotent_on_repeat_runs(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener(
        [{"number": 42, "title": "Only issue", "html_url": "https://github.com/octo/sarathi/issues/42"}]
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    _, first = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"})
    )
    assert len(first["created"]) == 1
    first_task_id = first["created"][0]["task"]["id"]

    _, second = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"})
    )
    assert second["created"] == []
    assert second["skipped"] == [{"number": 42, "task_id": first_task_id}]

    # Still exactly one task for issue #42 in the workspace.
    _, tasks_data = assert_ok(request(app, "GET", f"/api/workspaces/{workspace_id}/tasks"))
    matching = [
        task
        for task in tasks_data["tasks"]
        if task.get("metadata", {}).get("github_issue", {}).get("number") == 42
    ]
    assert len(matching) == 1


def test_sync_does_not_duplicate_issue_already_imported_individually(tmp_path, monkeypatch):
    app, workspace_id, repository = _make_workspace_with_repo(tmp_path)

    # Import issue #7 individually first (existing single-issue import route).
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/github/issues/import",
            {"issue_url": "https://github.com/octo/sarathi/issues/7"},
        )
    )

    opener = _FakeGithubOpener(
        [{"number": 7, "title": "Same issue", "html_url": "https://github.com/octo/sarathi/issues/7"}]
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    _, data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"})
    )
    assert data["created"] == []
    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["number"] == 7


def test_sync_sends_github_token_bearer_header_when_env_set(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    monkeypatch.setenv("GITHUB_TOKEN", "s3cr3t-token")

    assert_ok(request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"}))

    assert len(opener.calls) == 1
    assert opener.calls[0].get_header("Authorization") == "Bearer s3cr3t-token"


def test_sync_respects_custom_label(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener([])
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/github/issues/sync",
            {"label": "ready-for-sarathi"},
        )
    )

    assert "labels=ready-for-sarathi" in opener.calls[0].full_url


def test_sync_requires_disambiguation_with_multiple_repositories(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    other_path = tmp_path / "other-repo"
    other_path.mkdir()
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/repositories",
            {
                "path": str(other_path),
                "approved": True,
                "remote_url": "https://github.com/octo/other.git",
            },
        )
    )

    response = request(
        app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"}
    )
    assert_error(response, status=400, code="invalid_request")


def test_sync_accepts_explicit_repository_full_name(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener(
        [{"number": 3, "title": "From another repo", "html_url": "https://github.com/acme/widgets/issues/3"}]
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    _, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/github/issues/sync",
            {"label": "sarathi", "repository": "acme/widgets"},
        )
    )
    assert data["repository"] == "acme/widgets"
    assert "repos/acme/widgets/issues" in opener.calls[0].full_url


# ---------------------------------------------------------------------------
# PR body assembly — engine shape
# ---------------------------------------------------------------------------


def _engine_task_fixture():
    return {
        "task_id": "task-123",
        "description": "Add label-driven GitHub issue sync",
        "current_phase": None,
        "budget_snapshot": {
            "enforcement": "enabled",
            "consumed_tokens": 4200,
            "max_total_tokens": 20000,
            "state": "ok",
        },
        "github_issue": {
            "url": "https://github.com/octo/sarathi/issues/42",
            "number": 42,
            "full_name": "octo/sarathi",
        },
        "phase_results": [
            {
                "phase": "route",
                "outcome": "pass",
                "decisions": ["Classified as codegen/feature"],
                "evidence": {"task_class": "codegen/feature"},
                "artifacts": {},
            },
            {
                "phase": "build",
                "outcome": "pass",
                "decisions": ["Implemented sync endpoint", "Reused existing draft path"],
                "evidence": {},
                "artifacts": {"cost_usd": 0.42, "tokens": 15230},
            },
            {
                "phase": "verify",
                "outcome": "pass",
                "decisions": [],
                "evidence": {
                    "verification_summary": {
                        "command_executed": True,
                        "command_succeeded": True,
                        "tests_count": 12,
                    },
                    "test_pass_rate": 1.0,
                },
                "artifacts": {},
            },
            {
                "phase": "review",
                "outcome": "pass",
                "decisions": ["No blocking issues found"],
                "evidence": {
                    "review_summary": {"score": 92},
                    "severity_counts": {"critical": 0, "major": 0, "minor": 1},
                },
                "artifacts": {},
            },
            {
                "phase": "learn",
                "outcome": "pass",
                "decisions": [],
                "evidence": {},
                "artifacts": {},
            },
        ],
    }


def test_build_pr_body_from_engine_shape_task():
    body = build_pr_body(_engine_task_fixture())

    assert "## Summary" in body
    assert "Add label-driven GitHub issue sync" in body
    assert "**Outcome:** completed" in body

    assert "## Phases" in body
    assert "| route | pass | Classified as codegen/feature |" in body
    assert "| build | pass | Implemented sync endpoint; Reused existing draft path |" in body
    assert "| verify | pass |" in body
    assert "| review | pass | No blocking issues found |" in body
    assert "| learn | pass |" in body

    assert "## Quality Signals" in body
    assert "**cost_usd:** 0.42" in body
    assert "**tokens:** 15230" in body
    assert "**test_pass_rate:** 1.0" in body
    assert "**consumed_tokens:** 4200" in body
    assert "**max_total_tokens:** 20000" in body

    assert "## Evidence" in body
    assert "**Verification:**" in body
    assert "succeeded=True" in body
    assert "**Review summary:**" in body
    assert "**Review severity counts:**" in body

    assert "Source issue: [#42](https://github.com/octo/sarathi/issues/42)" in body


def test_build_pr_body_from_engine_shape_with_judge_scorecard():
    task = _engine_task_fixture()
    task["phase_results"][1]["artifacts"]["judge_scorecard"] = [
        {"branch": "branch-a", "provider": "claude", "weighted_score": 0.82},
        {"branch": "branch-b", "provider": "codex", "weighted_score": 0.71},
    ]
    body = build_pr_body(task)

    assert "**Judge scorecard:**" in body
    assert "| branch-a | claude | 0.82 |" in body
    assert "| branch-b | codex | 0.71 |" in body


def test_build_pr_body_marks_failed_run():
    task = _engine_task_fixture()
    task["phase_results"][2]["outcome"] = "fail"
    body = build_pr_body(task)
    assert "**Outcome:** failed" in body


def test_build_pr_body_engine_shape_with_no_signals_says_so():
    task = {
        "task_id": "task-empty",
        "description": "Bare task with nothing recorded",
        "phase_results": [],
    }
    body = build_pr_body(task)
    assert "_No quality signals were recorded for this run._" in body
    assert "_No phase log was recorded for this run._" in body
    assert "_No additional evidence was recorded for this run._" in body


# ---------------------------------------------------------------------------
# PR body assembly — service shape
# ---------------------------------------------------------------------------


def _service_task_fixture():
    return {
        "id": "svc-task-1",
        "workspace_id": "ws-1",
        "title": "GitHub issue #42",
        "description": "https://github.com/octo/sarathi/issues/42",
        "status": "done",
        "metadata": {
            "source": "github_issue",
            "github_issue": {
                "url": "https://github.com/octo/sarathi/issues/42",
                "number": 42,
                "full_name": "octo/sarathi",
            },
        },
        "lifecycle_events": [
            {
                "event_type": "task.draft_created",
                "payload": {"object_id": "svc-task-1", "gate": "gate-1"},
            },
            {
                "event_type": "phase.completed",
                "payload": {"phase": "route", "status": "completed", "engine_task_id": "task-123"},
            },
            {
                "event_type": "phase.completed",
                "payload": {"phase": "build", "status": "completed", "engine_task_id": "task-123"},
            },
            {
                "event_type": "phase.completed",
                "payload": {
                    "phase": "verify",
                    "status": "completed",
                    "engine_task_id": "task-123",
                    "test_pass_rate": 1.0,
                    "cost_usd": 0.11,
                },
            },
            {
                "event_type": "task.completed",
                "payload": {"phase": "learn", "status": "completed", "engine_task_id": "task-123"},
            },
        ],
    }


def test_build_pr_body_from_service_shape_task():
    body = build_pr_body(_service_task_fixture())

    assert "## Summary" in body
    assert "https://github.com/octo/sarathi/issues/42" in body
    assert "**Outcome:** done" in body

    assert "## Phases" in body
    assert "| route | completed |" in body
    assert "| build | completed |" in body
    assert "| verify | completed |" in body

    assert "## Quality Signals" in body
    assert "**cost_usd:** 0.11" in body
    assert "**test_pass_rate:** 1.0" in body

    assert "Source issue: [#42](https://github.com/octo/sarathi/issues/42)" in body


def test_pr_body_route_returns_body_for_service_task(tmp_path, monkeypatch):
    app, workspace_id, _repo = _make_workspace_with_repo(tmp_path)
    opener = _FakeGithubOpener(
        [{"number": 5, "title": "Do the thing", "html_url": "https://github.com/octo/sarathi/issues/5"}]
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    _, sync_data = assert_ok(
        request(app, "POST", f"/api/workspaces/{workspace_id}/github/issues/sync", {"label": "sarathi"})
    )
    task_id = sync_data["created"][0]["task"]["id"]

    status, data = assert_ok(request(app, "GET", f"/api/tasks/{task_id}/pr-body"))
    assert status == 200
    assert "## Summary" in data["body"]
    assert "Source issue:" in data["body"]
    assert "#5" in data["body"]


# ---------------------------------------------------------------------------
# gh CLI helper
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_create_pr_if_gh_available_invokes_runner_with_expected_args(tmp_path):
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return _FakeCompletedProcess(returncode=0, stdout="https://github.com/octo/sarathi/pull/9\n")

    result = create_pr_if_gh_available(
        tmp_path,
        "My PR title",
        "My PR body",
        "feature-branch",
        runner=fake_runner,
        which=lambda name: "/usr/bin/gh" if name == "gh" else None,
    )

    assert result is not None
    assert result["returncode"] == 0
    assert "https://github.com/octo/sarathi/pull/9" in result["stdout"]
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:3] == ["gh", "pr", "create"]
    assert "--title" in command and "My PR title" in command
    assert "--body-file" in command
    assert "--head" in command and "feature-branch" in command
    assert kwargs["cwd"] == str(tmp_path)


def test_create_pr_if_gh_available_skips_silently_when_gh_absent(tmp_path):
    def fake_runner(command, **kwargs):
        raise AssertionError("runner must not be invoked when gh is absent")

    result = create_pr_if_gh_available(
        tmp_path,
        "Title",
        "Body",
        runner=fake_runner,
        which=lambda name: None,
    )

    assert result is None
