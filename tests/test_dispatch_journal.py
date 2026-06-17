"""Tests for the crash-safe dispatch write-ahead journal."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.engine import Complexity, Engine, PersistenceManager, TaskContext
from src.runtime.contracts import DispatchRequest, DispatchResponse
from src.runtime.dispatch_journal import DispatchJournal


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "seed"], capture_output=True, check=True)


def _request(**overrides) -> DispatchRequest:
    base = dict(
        mode="execute",
        task_id="task-journal",
        phase="Build",
        prompt="Implement the slice.",
        timeout_seconds=30,
    )
    base.update(overrides)
    return DispatchRequest(**base)


# ── begin/complete/incomplete/mark_reconciled ───────────────────────────────


def test_begin_complete_round_trip(tmp_path: Path):
    journal = DispatchJournal(tmp_path)

    journal_id = journal.begin(
        task_id="t1", phase="Build", provider="claude", prompt="do stuff", workspace_root=str(tmp_path)
    )
    assert journal_id

    assert journal.incomplete(task_id="t1") != []

    journal.complete(journal_id, success=True)
    assert journal.incomplete(task_id="t1") == []


def test_incomplete_returns_unmatched_intents(tmp_path: Path):
    journal = DispatchJournal(tmp_path)

    j1 = journal.begin(task_id="t1", phase="Build", provider="claude", prompt="a", workspace_root=str(tmp_path))
    j2 = journal.begin(task_id="t1", phase="Verify", provider="claude", prompt="b", workspace_root=str(tmp_path))
    journal.complete(j1, success=True)

    incomplete = journal.incomplete(task_id="t1")
    assert len(incomplete) == 1
    assert incomplete[0]["journal_id"] == j2


def test_mark_reconciled_removes_from_incomplete(tmp_path: Path):
    journal = DispatchJournal(tmp_path)

    journal_id = journal.begin(task_id="t1", phase="Build", provider="claude", prompt="a", workspace_root=str(tmp_path))
    assert journal.incomplete(task_id="t1") != []

    journal.mark_reconciled(journal_id)
    assert journal.incomplete(task_id="t1") == []


# ── reconcile against a real git repo ───────────────────────────────────────


def test_reconcile_safe_to_rerun_when_workspace_untouched(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    journal = DispatchJournal(tmp_path / "journal")

    journal_id = journal.begin(
        task_id="t1", phase="Build", provider="claude", prompt="a", workspace_root=str(repo)
    )
    entry = journal.incomplete(task_id="t1")[0]

    result = journal.reconcile(entry, str(repo))

    assert result["journal_id"] == journal_id
    assert result["task_id"] == "t1"
    assert result["safe_to_rerun"] is True
    assert result["workspace_delta"]["measured"] is True
    assert result["workspace_delta"]["change_count"] == 0


def test_reconcile_unsafe_when_workspace_changed(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    journal = DispatchJournal(tmp_path / "journal")

    journal_id = journal.begin(
        task_id="t1", phase="Build", provider="claude", prompt="a", workspace_root=str(repo)
    )
    entry = journal.incomplete(task_id="t1")[0]

    (repo / "new_file.txt").write_text("changed\n", encoding="utf-8")

    result = journal.reconcile(entry, str(repo))

    assert result["journal_id"] == journal_id
    assert result["safe_to_rerun"] is False
    assert result["workspace_delta"]["measured"] is True
    assert "new_file.txt" in result["workspace_delta"]["files_changed"]


# ── corrupt journal lines ───────────────────────────────────────────────────


def test_corrupt_journal_line_is_tolerated(tmp_path: Path):
    journal = DispatchJournal(tmp_path)

    journal_id = journal.begin(task_id="t1", phase="Build", provider="claude", prompt="a", workspace_root=str(tmp_path))

    # Append a corrupt line and a non-dict JSON line directly to the journal file.
    with open(journal.path, "a", encoding="utf-8") as f:
        f.write("not valid json {{{\n")
        f.write("[1, 2, 3]\n")
        f.write("\n")

    incomplete = journal.incomplete(task_id="t1")
    assert len(incomplete) == 1
    assert incomplete[0]["journal_id"] == journal_id


# ── compaction ───────────────────────────────────────────────────────────────


def test_compaction_keeps_only_recent_journal_ids(tmp_path: Path, monkeypatch):
    import src.runtime.dispatch_journal as dispatch_journal_module

    monkeypatch.setattr(dispatch_journal_module, "_COMPACT_THRESHOLD_BYTES", 1)
    monkeypatch.setattr(dispatch_journal_module, "_COMPACT_KEEP_JOURNAL_IDS", 2)

    journal = DispatchJournal(tmp_path)

    ids = []
    for i in range(5):
        jid = journal.begin(
            task_id="t1", phase="Build", provider="claude", prompt=f"prompt {i}", workspace_root=str(tmp_path)
        )
        journal.complete(jid, success=True)
        ids.append(jid)

    # Re-init to trigger compaction with the lowered threshold.
    journal2 = DispatchJournal(tmp_path)

    records = journal2._read_records()
    seen_ids = {r.get("journal_id") for r in records}
    assert seen_ids == set(ids[-2:])


# ── _HarnessAwareDispatcher integration ─────────────────────────────────────


class _StubDispatcher:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[DispatchRequest] = []

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.calls.append(request)
        if self.exc is not None:
            raise self.exc
        return self.response


def test_harness_dispatcher_journals_success(tmp_path: Path):
    from src.engine import _HarnessAwareDispatcher

    journal = DispatchJournal(tmp_path)
    base = _StubDispatcher(response=DispatchResponse(success=True, outputs={"ok": True}))
    dispatcher = _HarnessAwareDispatcher(base)
    dispatcher.journal = journal
    dispatcher.workspace_root = str(tmp_path)

    response = dispatcher.dispatch(_request(task_id="t1"))

    assert response.success is True
    assert journal.incomplete(task_id="t1") == []

    records = journal._read_records()
    types = [r["type"] for r in records]
    assert types == ["intent", "complete"]
    assert records[1]["success"] is True


def test_harness_dispatcher_journals_exception_and_reraises(tmp_path: Path):
    from src.engine import _HarnessAwareDispatcher

    journal = DispatchJournal(tmp_path)
    base = _StubDispatcher(exc=RuntimeError("boom"))
    dispatcher = _HarnessAwareDispatcher(base)
    dispatcher.journal = journal
    dispatcher.workspace_root = str(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        dispatcher.dispatch(_request(task_id="t1"))

    records = journal._read_records()
    types = [r["type"] for r in records]
    assert types == ["intent", "complete"]
    assert records[1]["success"] is False
    assert records[1]["error"] == "boom"


# ── Engine-level crash recovery on resume ───────────────────────────────────


def test_resume_task_reconciles_inflight_dispatch(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    task = TaskContext(
        task_id="crash-recovery-task",
        description="Test task",
        complexity=Complexity.LOW,
    )

    engine = Engine()
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))
    engine.dispatch_journal = DispatchJournal(tmp_path / "journal")
    engine.workspace_root = str(repo)
    engine.dispatcher.journal = engine.dispatch_journal
    engine.dispatcher.workspace_root = str(repo)

    engine.run_task(task)
    assert task.current_phase is None

    # Simulate a crashed dispatch: an intent recorded against a stale snapshot
    # (taken before a file was written to the workspace), with no matching
    # complete record.
    engine.dispatch_journal.begin(
        task_id=task.task_id,
        phase="Build",
        provider="claude",
        prompt="do something",
        workspace_root=str(repo),
    )
    (repo / "crash_artifact.txt").write_text("written mid-dispatch\n", encoding="utf-8")

    resumed = engine.resume_task(task)

    assert resumed.crash_reconciliation
    assert len(resumed.crash_reconciliation) == 1
    reconciliation = resumed.crash_reconciliation[0]
    assert reconciliation["safe_to_rerun"] is False
    assert "crash_artifact.txt" in reconciliation["workspace_delta"]["files_changed"]

    reloaded = engine.persistence.load_task(task.task_id)
    assert reloaded is not None
    assert reloaded.crash_reconciliation
    assert reloaded.crash_reconciliation[0]["safe_to_rerun"] is False
