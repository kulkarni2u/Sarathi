"""Regression coverage for service backed TUI task actions."""

import urllib.error

import pytest

from src import service_client, tui_data
from src.engine import PersistenceManager, TaskContext, Complexity


def test_service_client_get_normalizes_http_and_json_errors(monkeypatch):
    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError("http://service/api/tasks", 401, "no", {}, None)

    monkeypatch.setattr(service_client.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        service_client._service_get("http://service", "/api/tasks")


def test_service_resume_does_not_require_local_policy_or_persistence(monkeypatch, tmp_path):
    class Client:
        def get_task(self, task_id):
            return {"id": task_id, "status": "awaiting_approval"}

        def resume_task(self, task_id):
            assert task_id == "service-only"
            return {"task": {"id": task_id, "status": "running"}}

    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    persistence = PersistenceManager(str(tmp_path / "empty"))
    result = tui_data.resume_task(persistence, "service-only", "/missing/policy-pack")
    assert result.task_id == "service-only"
    assert result.current_phase.value == "running"


def test_service_approve_error_is_not_retried_in_local_engine(monkeypatch, tmp_path):
    class Client:
        def get_task(self, task_id):
            return {"id": task_id, "status": "awaiting_approval"}

        def approve_task(self, task_id, **kwargs):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    persistence = PersistenceManager(str(tmp_path / "empty"))
    with pytest.raises(RuntimeError, match="service unavailable"):
        tui_data.approve_task(persistence, "service-only", "/missing/policy-pack")


def test_local_resume_still_uses_persisted_task(monkeypatch, tmp_path):
    class Client:
        def get_task(self, task_id):
            return None

    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="local", description="local", complexity=Complexity.LOW)
    persistence.save_task(task)
    monkeypatch.setattr(tui_data.Engine, "resume_task", lambda self, task, **kwargs: task)
    result = tui_data.resume_task(persistence, "local", "/unused")
    assert result.task_id == "local"


def test_observed_service_task_never_falls_back_when_service_disconnects(monkeypatch, tmp_path):
    class Client:
        def get_task(self, task_id):
            return {"id": task_id, "status": "awaiting_approval"}

    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    assert tui_data.is_service_task("service-owned", persistence)
    local = TaskContext(task_id="service-owned", description="wrong", complexity=Complexity.LOW)
    persistence.save_task(local)
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: None)
    with pytest.raises(RuntimeError, match="Service is unavailable"):
        tui_data.resume_task(persistence, "service-owned", "/unused")


def test_approve_uses_latest_gate_status_for_each_name(monkeypatch):
    client = service_client.ServiceClient({"url": "http://service"})
    calls = {}
    monkeypatch.setattr(client, "get_task", lambda _task_id: None)
    monkeypatch.setattr(client, "get_approvals", lambda _task_id: [
        {"name": "PRD/AC", "status": "pending"},
        {"name": "PRD/AC", "status": "approved"},
        {"name": "Task graph", "status": "pending"},
    ])
    monkeypatch.setattr(client, "_post", lambda path, body: calls.update({"path": path, "body": body}) or {})
    client.approve_task("task-1")
    assert calls["body"]["name"] == "Task graph"

    monkeypatch.setattr(client, "get_approvals", lambda _task_id: [
        {"name": "PRD/AC", "status": "pending"},
        {"name": "PRD/AC", "status": "approved"},
    ])
    with pytest.raises(RuntimeError, match="no pending"):
        client.approve_task("task-1")


def test_full_engine_approval_uses_engine_gate_without_approval_history(monkeypatch):
    client = service_client.ServiceClient({"url": "http://service"})
    calls = {}
    monkeypatch.setattr(client, "get_task", lambda _task_id: {
        "id": "engine-task", "metadata": {"execution_mode": "full_engine"}
    })
    monkeypatch.setattr(client, "_post", lambda path, body: calls.update({"path": path, "body": body}) or {})
    client.approve_task("engine-task")
    assert calls["body"]["name"] == "Engine approval"


def test_known_service_task_get_failure_never_falls_back_to_local(monkeypatch, tmp_path):
    class Client:
        def get_task_strict(self, _task_id):
            raise RuntimeError("Service request failed (HTTP 401).")

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="known-service", description="local collision", complexity=Complexity.LOW)
    persistence.save_task(task)
    persistence._service_task_ids = {"known-service"}
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    with pytest.raises(RuntimeError, match="HTTP 401"):
        tui_data.resume_task(persistence, "known-service", "/unused")


def test_known_service_task_genuine_404_never_falls_back_to_local_resume(monkeypatch, tmp_path):
    """A remembered service task_id colliding with a same-ID local context
    file must report a service-not-found error, not silently resume the
    unrelated local context -- even when the service lookup is a clean 404
    (get_task_strict returning None) rather than a raised error."""

    class Client:
        def get_task_strict(self, _task_id):
            return None

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="known-service", description="local collision", complexity=Complexity.LOW)
    persistence.save_task(task)
    persistence._service_task_ids = {"known-service"}
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    with pytest.raises(RuntimeError, match="not found on the service"):
        tui_data.resume_task(persistence, "known-service", "/unused")


def test_known_service_task_genuine_404_never_falls_back_to_local_approve(monkeypatch, tmp_path):
    class Client:
        def get_task_strict(self, _task_id):
            return None

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="known-service", description="local collision", complexity=Complexity.LOW)
    persistence.save_task(task)
    persistence._service_task_ids = {"known-service"}
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    with pytest.raises(RuntimeError, match="not found on the service"):
        tui_data.approve_task(persistence, "known-service", "/unused")


def test_never_service_local_task_still_resumes_locally(monkeypatch, tmp_path):
    """A task_id that was never observed as service-origin (not remembered,
    and the current lookup finds nothing) is a legitimate local-only task and
    must keep working through the local engine."""

    class Client:
        def get_task_strict(self, _task_id):
            return None

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="local-only", description="local", complexity=Complexity.LOW)
    persistence.save_task(task)
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    monkeypatch.setattr(tui_data.Engine, "resume_task", lambda self, task, **kwargs: task)
    result = tui_data.resume_task(persistence, "local-only", "/unused")
    assert result.task_id == "local-only"


def test_ordinary_gate_approval_does_not_claim_running_or_resumed(monkeypatch, tmp_path):
    """An ordinary (non full-Engine) gate approval that didn't trigger
    auto-schedule returns only {"approval_gate": ...} -- no task status at
    all. The result must reflect that nothing was actually resumed instead
    of defaulting to "running"."""

    class Client:
        def get_task_strict(self, task_id):
            return {"id": task_id, "status": "waiting_human", "metadata": {}}

        def get_task(self, task_id):
            return {"id": task_id, "status": "waiting_human"}

        def approve_task(self, task_id, **kwargs):
            return {"approval_gate": {"id": "g1", "name": "PRD/AC", "status": "approved"}}

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    result = tui_data.approve_task(persistence, "svc-task", "/unused")
    assert result.current_phase.value != "running"
    assert result.execution_scheduled is False


def test_ordinary_gate_approval_with_auto_schedule_reports_scheduled(monkeypatch, tmp_path):
    """When approving the Task graph gate does trigger auto-schedule, the
    result must reflect that real execution was scheduled."""

    class Client:
        def get_task_strict(self, task_id):
            return {"id": task_id, "status": "waiting_human", "metadata": {}}

        def approve_task(self, task_id, **kwargs):
            return {
                "approval_gate": {"id": "g1", "name": "Task graph", "status": "approved"},
                "auto_schedule": {
                    "task": {"id": task_id, "status": "in_progress"},
                    "scheduled": [{"id": "sub-1"}],
                },
            }

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    monkeypatch.setattr(tui_data, "_try_service_client", lambda: Client())
    result = tui_data.approve_task(persistence, "svc-task", "/unused")
    assert result.execution_scheduled is True
    assert result.current_phase.value == "in_progress"
