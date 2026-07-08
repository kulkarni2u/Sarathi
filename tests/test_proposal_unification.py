"""Tests for the file <-> SQLite policy-proposal unification.

Covers ``src/proposal_sync.py`` (the best-effort mirror) and its wiring
into ``evolve.ProposalReviewStore`` and ``src/service/proposals.py``, per
docs/IMPLEMENTATION-PLAN.md item 1.4-B.
"""

import json

from src.evolve import PolicyProposal, ProposalReviewStore
from src.policy.compiler import compile_policy_pack
from src.proposal_sync import ProposalSync
from src.service import create_app
from src.storage import Storage, connect, run_migrations


def _make_proposal(suffix: str = "") -> PolicyProposal:
    return PolicyProposal(
        title=f"Add Build failure recovery guidance{suffix}",
        policy_file="commands.md",
        rationale=f"Build recorded repeated failure signal(s){suffix}.",
        suggested_change="Add a Build recovery checklist.",
        evidence_refs=["task-1:repeated_failures:Build"],
        confidence=0.8,
        source="repeated_failures",
    )


def _bootstrap_policy_pack(tmp_path):
    workspace_root = tmp_path / "workspace"
    policy_dir = workspace_root / "policy-pack"
    policy_dir.mkdir(parents=True)
    (policy_dir / "commands.md").write_text("# Commands\n")
    return workspace_root, policy_dir


def _bootstrap_db(workspace_root):
    db_path = workspace_root / ".sarathi" / "sarathi.db"
    with connect(db_path) as conn:
        run_migrations(conn)
    return db_path


# ------------------------------------------------------------- no DB present


def test_no_db_leaves_file_behavior_byte_for_byte_unchanged(tmp_path):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    proposal = _make_proposal()

    store = ProposalReviewStore(policy_dir)
    assert store._sync is None  # never activates without an existing DB

    decision = store.accept(proposal)

    assert decision["status"] == "accepted"
    assert (policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json").exists()
    # No DB ever created on behalf of a CLI-only user.
    assert not (workspace_root / ".sarathi").exists()


def test_sarathi_no_mirror_env_disables_sync_even_with_db(tmp_path, monkeypatch):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    _bootstrap_db(workspace_root)
    monkeypatch.setenv("SARATHI_NO_MIRROR", "1")

    store = ProposalReviewStore(policy_dir)

    assert store._sync is None


# ------------------------------------------------------- accept via the store


def test_accept_via_store_updates_sqlite_row_and_emits_lifecycle_event(tmp_path):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    db_path = _bootstrap_db(workspace_root)
    proposal = _make_proposal()

    store = ProposalReviewStore(policy_dir)
    assert store._sync is not None
    decision = store.accept(proposal)

    # File view (relied on by src/policy/compiler.py) is unchanged.
    json_path = policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json"
    assert json_path.exists()
    assert json.loads(json_path.read_text())["status"] == "accepted"

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspaces = storage.list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0]["root_path"] == str(workspace_root)
        workspace_id = workspaces[0]["id"]

        row = storage.get_proposal_decision(workspace_id, proposal.proposal_id)
        assert row is not None
        assert row["status"] == "accepted"
        assert row["policy_file"] == "commands.md"

        events = storage.list_events(workspace_id=workspace_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "proposal.accepted"
        assert events[0]["payload"]["proposal_id"] == proposal.proposal_id


def test_reject_via_store_updates_sqlite_row_and_emits_lifecycle_event(tmp_path):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    db_path = _bootstrap_db(workspace_root)
    proposal = _make_proposal()

    store = ProposalReviewStore(policy_dir)
    decision = store.reject(proposal, reason="Not applicable here")
    assert decision["status"] == "rejected"

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspace_id = storage.list_workspaces()[0]["id"]
        row = storage.get_proposal_decision(workspace_id, proposal.proposal_id)
        assert row["status"] == "rejected"
        assert row["reason"] == "Not applicable here"
        events = storage.list_events(workspace_id=workspace_id)
        assert events[0]["event_type"] == "proposal.rejected"


# ------------------------------------------------------------- JSON import


def test_migration_imports_existing_json_decisions_once(tmp_path):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    proposal = _make_proposal()

    # Decision recorded before the DB ever existed for this workspace.
    pre_db_store = ProposalReviewStore(policy_dir)
    assert pre_db_store._sync is None
    pre_db_store.accept(proposal)

    db_path = _bootstrap_db(workspace_root)

    # First open with the DB present -> import runs.
    store = ProposalReviewStore(policy_dir)
    assert store._sync is not None
    with connect(db_path) as conn:
        storage = Storage(conn)
        workspace_id = storage.list_workspaces()[0]["id"]
        rows = storage.list_proposal_decisions(workspace_id)
        assert len(rows) == 1
        assert rows[0]["proposal_id"] == proposal.proposal_id
        assert rows[0]["status"] == "accepted"

    # Second open (simulating a second CLI invocation) must not duplicate.
    store_again = ProposalReviewStore(policy_dir)
    assert store_again._sync is not None
    with connect(db_path) as conn:
        storage = Storage(conn)
        workspace_id = storage.list_workspaces()[0]["id"]
        rows = storage.list_proposal_decisions(workspace_id)
        assert len(rows) == 1


def test_proposal_sync_try_create_import_is_idempotent_directly(tmp_path):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    db_path = _bootstrap_db(workspace_root)
    review_dir = policy_dir / ".sarathi-proposals"
    review_dir.mkdir(parents=True, exist_ok=True)
    proposal = _make_proposal()
    decision = {
        "id": proposal.proposal_id,
        "status": "accepted",
        "policy_file": "commands.md",
        "title": proposal.title,
        "source": proposal.source,
        "reason": None,
        "reviewed_at": "2026-01-01T00:00:00Z",
    }
    (review_dir / f"{proposal.proposal_id}.json").write_text(json.dumps(decision))

    for _ in range(3):
        sync = ProposalSync.try_create(workspace_root, review_dir)
        assert sync is not None

    with connect(db_path) as conn:
        storage = Storage(conn)
        workspace_id = storage.list_workspaces()[0]["id"]
        rows = storage.list_proposal_decisions(workspace_id)
        assert len(rows) == 1


# -------------------------------------------------------- service path


def test_accept_via_service_reflects_in_json_and_learning_feedback(tmp_path):
    db_path = tmp_path / "sarathi.db"
    app = create_app(db_path)

    workspace_root = tmp_path / "workspace"
    policy_dir = workspace_root / "policy-pack"
    policy_dir.mkdir(parents=True)
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: pytest
```
"""
    )
    (policy_dir / "model-routing.md").write_text("# Model routing\n")
    (policy_dir / "escalation.md").write_text("# Escalation\n")

    status, payload = app.handle(
        "POST",
        "/api/workspaces",
        body={"name": "Unify Workspace", "root_path": str(workspace_root)},
        headers={"x-correlation-id": "corr-1"},
    )
    assert status == 201
    workspace_id = payload["data"]["workspace"]["id"]

    with connect(db_path) as conn:
        storage = Storage(conn)
        task = storage.create_task(
            workspace_id=workspace_id,
            title="Failing build",
            description=None,
            metadata={"complexity": "high"},
        )
        subtask = storage.create_subtask(
            workspace_id=workspace_id,
            task_id=task["id"],
            title="Implement scoped change",
            status="failed",
            metadata={"role": "Pravaha"},
        )
        for _ in range(2):
            storage.create_dispatch(
                workspace_id=workspace_id,
                task_id=task["id"],
                agent_name="codex",
                status="failed",
                metadata={"subtask_id": subtask["id"]},
            )

    status, payload = app.handle(
        "GET",
        f"/api/workspaces/{workspace_id}/proposals",
        body=None,
        headers={"x-correlation-id": "corr-2"},
    )
    assert status == 200
    proposals = payload["data"]["proposals"]
    proposal = next(item for item in proposals if item["policy_file"] == "commands.md")

    status, payload = app.handle(
        "POST",
        f"/api/workspaces/{workspace_id}/proposals/{proposal['id']}/accept",
        body={},
        headers={"x-correlation-id": "corr-3"},
    )
    assert status == 200
    assert payload["data"]["decision"]["status"] == "accepted"

    # JSON file reflects the service-side decision.
    json_path = policy_dir / ".sarathi-proposals" / f"{proposal['id']}.json"
    assert json_path.exists()
    assert json.loads(json_path.read_text())["status"] == "accepted"

    # And src/policy/compiler.py's learning-feedback loader (used to feed
    # accepted/rejected proposals back into policy compilation) picks it up
    # without any changes to that module.
    compiled = compile_policy_pack(str(policy_dir))
    feedback = compiled.get("learning_feedback")
    accepted_ids = {item["id"] for item in feedback["accepted_proposals"]}
    assert proposal["id"] in accepted_ids

    # SQLite row was also recorded directly by the service (not via the
    # mirror -- mirror=False is passed there to avoid a duplicate event).
    with connect(db_path) as conn:
        storage = Storage(conn)
        row = storage.get_proposal_decision(workspace_id, proposal["id"])
        assert row is not None
        assert row["status"] == "accepted"
        events = storage.list_events(workspace_id=workspace_id, task_id=None)
        proposal_events = [e for e in events if e["event_type"] == "proposal.accepted"]
        # Exactly one event for the one accept action -- no duplicate from
        # ProposalReviewStore's own mirror, since the service opts out of it.
        assert len(proposal_events) == 1


# ------------------------------------------------------------- failure injection


def test_storage_failure_during_accept_falls_back_to_file_only_behavior(tmp_path, monkeypatch):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    _bootstrap_db(workspace_root)
    proposal = _make_proposal()

    def _raise(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Storage, "upsert_proposal_decision", _raise)

    store = ProposalReviewStore(policy_dir)
    assert store._sync is not None

    # Must not raise despite every mirror write failing.
    decision = store.accept(proposal)

    assert decision["status"] == "accepted"
    json_path = policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json"
    assert json_path.exists()
    assert json.loads(json_path.read_text())["status"] == "accepted"
    # A single failure is logged but does not (yet) disable the sync.
    assert store._sync.disabled is False


def test_repeated_storage_failures_self_disable_the_sync(tmp_path, monkeypatch):
    workspace_root, policy_dir = _bootstrap_policy_pack(tmp_path)
    _bootstrap_db(workspace_root)

    def _raise(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Storage, "upsert_proposal_decision", _raise)

    store = ProposalReviewStore(policy_dir)
    assert store._sync is not None

    for index in range(5):
        # Must never raise, regardless of how many times it is called.
        store.reject(_make_proposal(suffix=f" {index}"), reason="test")

    assert store._sync.disabled is True
