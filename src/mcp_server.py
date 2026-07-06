"""MCP (Model Context Protocol) stdio server for Sarathi.

This module exposes Sarathi's task lifecycle, status inspection, history
browsing, and policy-proposal review as MCP tools so that any MCP client
(Claude Code, Codex, etc.) can drive Sarathi natively.

The plain functions in this module are MCP-independent: they return
JSON-serializable dicts and never raise. ``create_server()`` wraps them as
MCP tools using the optional ``mcp`` package (FastMCP). The ``mcp`` package
is an OPTIONAL dependency -- core Sarathi imports and tests cleanly without
it. Install it with ``pip install 'sarathi-ai[mcp]'``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .cli import calculate_complexity, discover_policy_pack
    from .engine import (
        Complexity,
        Engine,
        Phase,
        PHASE_TRANSITIONS,
        PersistenceManager,
        TaskContext,
    )
    from .evolve import Evolver, ProposalReviewStore
    from .validate import PolicyValidator
except ImportError:  # pragma: no cover - direct execution fallback
    from cli import calculate_complexity, discover_policy_pack
    from engine import (
        Complexity,
        Engine,
        Phase,
        PHASE_TRANSITIONS,
        PersistenceManager,
        TaskContext,
    )
    from evolve import Evolver, ProposalReviewStore
    from validate import PolicyValidator


_COMPLEXITY_MAP = {
    "low": Complexity.LOW,
    "medium": Complexity.MEDIUM,
    "high": Complexity.HIGH,
}


def _resolve_policy_pack(policy_pack: str | None) -> tuple[str | None, str | None]:
    """Resolve a policy-pack path, auto-discovering when not provided.

    Returns (resolved_path, error). On error, resolved_path is None.
    """
    if policy_pack:
        path = str(Path(policy_pack).resolve())
        if not Path(path).exists():
            return None, f"Policy pack not found: {path}"
        return path, None

    discovered = discover_policy_pack()
    if not discovered:
        return None, "No policy pack found. Run 'sarathi init' first or pass policy_pack explicitly."
    return discovered, None


def _gate_status_label(result: Any) -> str:
    """Return a Gate column label for a phase result (mirrors cli._gate_status_label)."""
    gate = result.artifacts.get("gate_result")
    if not isinstance(gate, dict):
        return "-"
    retry = result.artifacts.get("gate_retry")
    if isinstance(retry, dict):
        chosen_passed = gate.get("passed", False)
        if chosen_passed:
            return "retry"
        return "advisory"
    return "ok" if gate.get("passed", False) else "advisory"


def _phase_summary(result: Any) -> dict[str, Any]:
    """Render a compact per-phase summary dict, including gate label when present."""
    summary: dict[str, Any] = {
        "phase": result.phase.value,
        "outcome": result.outcome,
        "iterations": result.iterations,
    }
    gate_label = _gate_status_label(result)
    if gate_label != "-":
        summary["gate"] = gate_label
    if result.error:
        summary["error"] = result.error
    return summary


def _budget_snapshot(task: TaskContext) -> dict[str, Any] | None:
    """Return the policy-enforced per-task budget snapshot, if any."""
    snapshot = getattr(task, "budget_snapshot", None)
    if isinstance(snapshot, dict):
        return snapshot
    for pr in reversed(task.phase_results):
        exhausted = pr.artifacts.get("budget_exhausted")
        if isinstance(exhausted, dict):
            return exhausted
    return None


def _crash_reconciliation_summary(task: TaskContext) -> dict[str, Any] | None:
    """Summarize any in-flight dispatches reconciled on resume."""
    reconciliations = getattr(task, "crash_reconciliation", None)
    if not reconciliations:
        return None
    changed = any(not r.get("safe_to_rerun") for r in reconciliations)
    return {
        "count": len(reconciliations),
        "workspace_changes_detected": changed,
        "reconciliations": reconciliations,
    }


# ============================================================================
# Plain tool functions
# ============================================================================

def run_task(
    description: str,
    policy_pack: str | None = None,
    complexity: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a task through the Sarathi lifecycle, or preview the phase plan.

    Runs the full 12-phase lifecycle (Route -> Brainstorm -> ... -> Learn) for
    the given task description, persisting progress so it can be resumed
    later. Use ``dry_run=True`` to preview the planned phase sequence without
    executing anything (no engine/persistence side effects).
    """
    try:
        resolved_pack, error = _resolve_policy_pack(policy_pack)
        if error:
            return {"ok": False, "error": error}

        if complexity:
            complexity_key = complexity.strip().lower()
            if complexity_key not in _COMPLEXITY_MAP and complexity_key != "auto":
                return {
                    "ok": False,
                    "error": f"Invalid complexity: {complexity!r}. Expected one of low, medium, high, auto.",
                }
            resolved_complexity = (
                calculate_complexity(description)
                if complexity_key == "auto"
                else _COMPLEXITY_MAP[complexity_key]
            )
        else:
            resolved_complexity = calculate_complexity(description)

        if dry_run:
            phases: list[str] = []
            phase = Phase.ROUTE
            while phase != Phase.LEARN:
                phases.append(phase.value)
                phase = PHASE_TRANSITIONS.get(phase, Phase.LEARN)
            phases.append(Phase.LEARN.value)
            planned = []
            for p in phases:
                entry: dict[str, Any] = {"phase": p}
                if p == "PlanningAdvisor" and resolved_complexity != Complexity.HIGH:
                    entry["skip"] = True
                planned.append(entry)
            return {
                "ok": True,
                "dry_run": True,
                "policy_pack": resolved_pack,
                "complexity": resolved_complexity.value,
                "planned_phases": planned,
            }

        engine = Engine(policy_pack_path=resolved_pack, enforce_preflight=True, ncp_enabled=False)
        engine.persistence = PersistenceManager()
        task = TaskContext(
            task_id=engine.generate_task_id(description),
            description=description,
            complexity=resolved_complexity,
        )

        preflight = engine.preflight_validate_policy(task.task_id)
        task.preflight_validation = preflight
        if preflight.get("blocking", False):
            return {
                "ok": True,
                "task_id": task.task_id,
                "policy_pack": resolved_pack,
                "complexity": resolved_complexity.value,
                "preflight": preflight,
                "blocked": True,
                "phases": [],
                "final_status": "blocked_on_preflight",
            }

        result = engine.run_task(task)

        phases = [_phase_summary(pr) for pr in result.phase_results]
        response: dict[str, Any] = {
            "ok": True,
            "task_id": result.task_id,
            "policy_pack": resolved_pack,
            "complexity": resolved_complexity.value,
            "preflight": preflight,
            "blocked": False,
            "phases": phases,
            "current_phase": result.current_phase.value if result.current_phase else None,
            "final_status": "completed" if result.current_phase is None else "paused",
        }
        budget = _budget_snapshot(result)
        if budget is not None:
            response["budget"] = budget
        return response
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def task_status(task_id: str) -> dict[str, Any]:
    """Return a status snapshot for a previously run/saved task.

    Looks up the task by ID in Sarathi's persisted task store and reports the
    current phase, a summary of each recorded phase's outcome, the token
    budget snapshot (if policy-enforced budgets are configured), and any
    crash-reconciliation summary recorded on resume. Use this to check
    whether a task completed, is paused awaiting resume, or needs attention.
    """
    try:
        persistence = PersistenceManager()
        task = persistence.load_task(task_id)
        if task is None:
            return {
                "ok": False,
                "error": f"Task {task_id} not found.",
                "available_tasks": persistence.list_tasks(),
            }

        response: dict[str, Any] = {
            "ok": True,
            "task_id": task.task_id,
            "description": task.description,
            "complexity": task.complexity.value,
            "current_phase": task.current_phase.value if task.current_phase else None,
            "status": "completed" if task.current_phase is None else "paused",
            "phases": [_phase_summary(pr) for pr in task.phase_results],
        }
        if task.preflight_validation:
            response["preflight"] = task.preflight_validation
        budget = _budget_snapshot(task)
        if budget is not None:
            response["budget"] = budget
        crash_summary = _crash_reconciliation_summary(task)
        if crash_summary is not None:
            response["crash_reconciliation"] = crash_summary
        return response
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def resume_task(task_id: str, policy_pack: str | None = None) -> dict[str, Any]:
    """Resume a previously paused/saved task from its next unresolved phase.

    Loads the task from Sarathi's persisted task store, re-attaches the
    engine (using ``policy_pack`` if given, otherwise auto-discovering it the
    same way ``sarathi resume`` does), and continues lifecycle execution from
    where it left off. Returns the resulting phase summary and final status
    (completed or paused again).
    """
    try:
        persistence = PersistenceManager()
        task = persistence.load_task(task_id)
        if task is None:
            return {
                "ok": False,
                "error": f"Task {task_id} not found.",
                "available_tasks": persistence.list_tasks(),
            }

        resolved_pack, error = _resolve_policy_pack(policy_pack)
        if error:
            return {"ok": False, "error": error}

        engine = Engine(policy_pack_path=resolved_pack, enforce_preflight=True, ncp_enabled=False)
        engine.persistence = persistence

        result = engine.resume_task(task)

        response: dict[str, Any] = {
            "ok": True,
            "task_id": result.task_id,
            "policy_pack": resolved_pack,
            "phases": [_phase_summary(pr) for pr in result.phase_results],
            "current_phase": result.current_phase.value if result.current_phase else None,
            "final_status": "completed" if result.current_phase is None else "paused",
        }
        stop_reason = getattr(result, "stop_reason", None)
        if stop_reason:
            response["stop_reason"] = stop_reason
            if stop_reason in ("approval_required", "rejected"):
                response["final_status"] = "awaiting_approval" if stop_reason == "approval_required" else "rejected"
        budget = _budget_snapshot(result)
        if budget is not None:
            response["budget"] = budget
        crash_summary = _crash_reconciliation_summary(result)
        if crash_summary is not None:
            response["crash_reconciliation"] = crash_summary
        return response
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def approve_task(task_id: str, note: str | None = None, reject: bool = False, policy_pack: str | None = None) -> dict[str, Any]:
    """Approve or reject a task paused on a human-attention escalation, then resume it.

    Loads the task from Sarathi's persisted task store and requires its most
    recent phase result to be an approval-flavored pause (a graph node
    exhausted its retry budget and needs a human decision -- see
    ``task_log`` for the escalation detail). Records an ``approval`` artifact
    with ``approved_by`` set to ``"mcp"`` (and the optional ``note``). When
    ``reject`` is False (default), the approval is recorded and the task is
    immediately resumed via the same path as ``resume_task``. When ``reject``
    is True, the escalation is recorded as rejected and the task is left
    paused -- it will not auto-advance until a fresh approval is recorded.
    """
    try:
        persistence = PersistenceManager()
        task = persistence.load_task(task_id)
        if task is None:
            return {
                "ok": False,
                "error": f"Task {task_id} not found.",
                "available_tasks": persistence.list_tasks(),
            }

        resolved_pack, error = _resolve_policy_pack(policy_pack)
        if error:
            return {"ok": False, "error": error}

        engine = Engine(policy_pack_path=resolved_pack, enforce_preflight=True, ncp_enabled=False)
        engine.persistence = persistence

        try:
            task = engine.record_approval(task, approved_by="mcp", approve=not reject, note=note)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        if reject:
            return {
                "ok": True,
                "task_id": task.task_id,
                "policy_pack": resolved_pack,
                "decision": "rejected",
                "current_phase": task.current_phase.value if task.current_phase else None,
                "final_status": "rejected",
            }

        result = engine.resume_task(task)
        response: dict[str, Any] = {
            "ok": True,
            "task_id": result.task_id,
            "policy_pack": resolved_pack,
            "decision": "approved",
            "phases": [_phase_summary(pr) for pr in result.phase_results],
            "current_phase": result.current_phase.value if result.current_phase else None,
            "final_status": "completed" if result.current_phase is None else "paused",
        }
        stop_reason = getattr(result, "stop_reason", None)
        if stop_reason:
            response["stop_reason"] = stop_reason
            if stop_reason in ("approval_required", "rejected"):
                response["final_status"] = "awaiting_approval" if stop_reason == "approval_required" else "rejected"
        return response
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def list_tasks(limit: int = 20) -> dict[str, Any]:
    """List recently saved Sarathi task IDs.

    Returns up to ``limit`` task IDs (sorted, most recent task IDs tend to
    sort last since they embed a timestamp) from the local persisted task
    store. Use this to discover task IDs for ``task_status``, ``resume_task``,
    or ``task_log``.
    """
    try:
        persistence = PersistenceManager()
        ids = sorted(persistence.list_tasks())
        if limit is not None and limit >= 0:
            ids = ids[-limit:] if limit else []
        return {
            "ok": True,
            "task_ids": ids,
            "total": len(persistence.list_tasks()),
            "storage_path": str(persistence.storage_path),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def task_log(task_id: str) -> dict[str, Any]:
    """Return the detailed phase-by-phase log for a saved task.

    Includes per-phase outcome, iteration counts, evidence summaries, errors,
    and escalation bundles (if any), plus the raw phase-transition log lines
    if a ``<task_id>_phases.log`` file exists. Use this for a deeper view than
    ``task_status`` when investigating why a task escalated or failed.
    """
    try:
        persistence = PersistenceManager()
        task = persistence.load_task(task_id)
        if task is None:
            return {
                "ok": False,
                "error": f"Task {task_id} not found.",
                "available_tasks": persistence.list_tasks(),
            }

        phases = []
        for pr in task.phase_results:
            entry: dict[str, Any] = _phase_summary(pr)
            evidence_summary = {
                k: v for k, v in pr.evidence.items() if isinstance(v, (str, int, bool))
            }
            if evidence_summary:
                entry["evidence"] = evidence_summary
            bundle = pr.artifacts.get("escalation_bundle")
            if isinstance(bundle, dict):
                entry["escalation_bundle"] = bundle
            phases.append(entry)

        response: dict[str, Any] = {
            "ok": True,
            "task_id": task.task_id,
            "description": task.description,
            "complexity": task.complexity.value,
            "current_phase": task.current_phase.value if task.current_phase else None,
            "phases": phases,
        }

        log_file = persistence.storage_path / f"{task_id}_phases.log"
        if log_file.exists():
            try:
                response["phase_transition_log"] = log_file.read_text().splitlines()
            except Exception as exc:  # noqa: BLE001
                response["phase_transition_log_error"] = str(exc)

        return response
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def list_proposals(policy_pack: str | None = None) -> dict[str, Any]:
    """List policy proposals derived from persisted Learn-phase learnings.

    Scans all saved tasks for ``learning_record`` artifacts produced by the
    Learn phase, then generates candidate policy proposals from them (e.g.
    "tighten this gate threshold"). Each proposal includes an ``id`` usable
    with ``accept_proposal``/``reject_proposal``. ``policy_pack`` is accepted
    for symmetry with the accept/reject tools but is not required to list
    proposals.
    """
    try:
        persistence = PersistenceManager()
        records = []
        for task_id in persistence.list_tasks():
            task = persistence.load_task(task_id)
            if task is None:
                continue
            for result in task.phase_results:
                record = result.artifacts.get("learning_record")
                if isinstance(record, dict):
                    records.append(record)

        proposals = Evolver().generate_policy_proposals(learning_records=records)
        return {
            "ok": True,
            "proposals": [proposal.to_artifact() for proposal in proposals],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _find_proposal(proposals, proposal_id: str):
    matches = [
        proposal for proposal in proposals
        if proposal.proposal_id == proposal_id or proposal.proposal_id.startswith(proposal_id)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _load_proposals_and_find(proposal_id: str):
    persistence = PersistenceManager()
    records = []
    for task_id in persistence.list_tasks():
        task = persistence.load_task(task_id)
        if task is None:
            continue
        for result in task.phase_results:
            record = result.artifacts.get("learning_record")
            if isinstance(record, dict):
                records.append(record)

    proposals = Evolver().generate_policy_proposals(learning_records=records)
    return _find_proposal(proposals, proposal_id)


def accept_proposal(proposal_id: str, policy_pack: str | None = None) -> dict[str, Any]:
    """Accept a policy proposal and append it to the relevant policy file.

    ``proposal_id`` is the (possibly truncated) ID returned by
    ``list_proposals``. The proposal text is appended to its target policy
    file under the given (or auto-discovered) policy pack, marked with the
    proposal's ID so re-acceptance is idempotent.
    """
    try:
        proposal = _load_proposals_and_find(proposal_id)
        if proposal is None:
            return {"ok": False, "error": f"Proposal not found: {proposal_id}"}

        resolved_pack, error = _resolve_policy_pack(policy_pack)
        if error:
            return {"ok": False, "error": error}

        store = ProposalReviewStore(resolved_pack)
        decision = store.accept(proposal)
        return {"ok": True, "decision": decision}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def reject_proposal(proposal_id: str, reason: str | None = None, policy_pack: str | None = None) -> dict[str, Any]:
    """Reject a policy proposal and record the decision (with optional reason).

    ``proposal_id`` is the (possibly truncated) ID returned by
    ``list_proposals``. The rejection (and optional ``reason``) is recorded
    against the given (or auto-discovered) policy pack so the proposal is not
    suggested again without new evidence.
    """
    try:
        proposal = _load_proposals_and_find(proposal_id)
        if proposal is None:
            return {"ok": False, "error": f"Proposal not found: {proposal_id}"}

        resolved_pack, error = _resolve_policy_pack(policy_pack)
        if error:
            return {"ok": False, "error": error}

        store = ProposalReviewStore(resolved_pack)
        decision = store.reject(proposal, reason=reason)
        return {"ok": True, "decision": decision}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def validate_policy_pack(path: str | None = None) -> dict[str, Any]:
    """Validate a policy pack against Sarathi's required-input checklist.

    Checks each lifecycle phase's required policy inputs against the policy
    pack's compiled sections, classifying every checked item as PASS (claim
    satisfied), DRIFT (claim conflicts with or fails to parse from policy
    content), or TODO (claim not addressed). If ``path`` is omitted, the
    policy pack is auto-discovered the same way ``sarathi run`` does.
    Returns summary counts plus a per-item breakdown.
    """
    try:
        resolved_pack, error = _resolve_policy_pack(path)
        if error:
            return {"ok": False, "error": error}

        validator = PolicyValidator(engine_path="engine", policy_pack_path=resolved_pack)
        results = validator.validate()

        passed = sum(1 for r in results if r.status.value == "PASS")
        drifted = sum(1 for r in results if r.status.value == "DRIFT")
        todo = sum(1 for r in results if r.status.value == "TODO")

        items = [
            {
                "status": r.status.value,
                "phase": r.phase,
                "required_input": r.required_input,
                "policy_file": r.policy_file,
                "issue": r.issue,
            }
            for r in results
        ]

        return {
            "ok": True,
            "policy_pack": resolved_pack,
            "summary": {"pass": passed, "drift": drifted, "todo": todo, "total": len(results)},
            "items": items,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ============================================================================
# MCP server wiring
# ============================================================================

def create_server():
    """Build and return a FastMCP server with all Sarathi tools registered.

    Lazily imports ``mcp.server.fastmcp.FastMCP``. Raises ``ImportError`` with
    a clear message if the optional ``mcp`` package is not installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised when mcp absent
        raise ImportError(
            "The 'mcp' package is required to run the Sarathi MCP server. "
            "Install it with: pip install 'sarathi-ai[mcp]'"
        ) from exc

    server = FastMCP("sarathi")

    server.add_tool(
        run_task,
        name="run_task",
        description=(
            "Run a Sarathi task through its full policy-driven lifecycle "
            "(Route -> Brainstorm -> ... -> Learn), or preview the planned "
            "phase sequence with dry_run=True without executing anything. "
            "Use this to kick off new work. Returns the task_id, per-phase "
            "outcomes (with gate labels where applicable), any token-budget "
            "snapshot, and whether the task completed or paused awaiting "
            "resume."
        ),
    )
    server.add_tool(
        task_status,
        name="task_status",
        description=(
            "Get a status snapshot for a previously run task by task_id: "
            "current phase, per-phase outcome summary, token budget "
            "snapshot (if policy-enforced budgets are configured), and any "
            "crash-reconciliation summary from a prior resume. Use this to "
            "check whether a task is completed, paused, or needs attention."
        ),
    )
    server.add_tool(
        resume_task,
        name="resume_task",
        description=(
            "Resume a previously paused/saved task by task_id, continuing "
            "lifecycle execution from its next unresolved phase. Pass "
            "policy_pack to specify the policy pack explicitly; otherwise it "
            "is auto-discovered the same way `sarathi resume` does. Returns "
            "the updated phase outcomes and whether the task is now "
            "completed or paused again."
        ),
    )
    server.add_tool(
        approve_task,
        name="approve_task",
        description=(
            "Approve (or, with reject=True, reject) a task paused on a "
            "human-attention escalation -- a graph node that exhausted its "
            "retry budget and needs a human decision (see task_log for the "
            "escalation detail). Approving records the decision and "
            "immediately resumes the task via the same path as resume_task. "
            "Rejecting records the decision and leaves the task paused: it "
            "will not auto-advance again until a fresh approval is "
            "recorded. Ordinary resumable pauses (e.g. an incomplete task "
            "graph with more nodes to run) are unaffected -- use "
            "resume_task for those."
        ),
    )
    server.add_tool(
        list_tasks,
        name="list_tasks",
        description=(
            "List recently saved Sarathi task IDs (most recent last), up to "
            "'limit' entries. Use this to discover task IDs to pass to "
            "task_status, resume_task, or task_log."
        ),
    )
    server.add_tool(
        task_log,
        name="task_log",
        description=(
            "Get the detailed phase-by-phase log for a saved task by "
            "task_id, including evidence summaries, errors, escalation "
            "bundles, and the raw phase-transition log. Use this for deeper "
            "investigation than task_status, e.g. to understand why a task "
            "escalated or failed."
        ),
    )
    server.add_tool(
        list_proposals,
        name="list_proposals",
        description=(
            "List policy-pack improvement proposals generated from "
            "persisted Learn-phase learnings across saved tasks. Each "
            "proposal has an id usable with accept_proposal/reject_proposal, "
            "a target policy_file, rationale, and confidence score."
        ),
    )
    server.add_tool(
        accept_proposal,
        name="accept_proposal",
        description=(
            "Accept a policy proposal (by id from list_proposals) and "
            "append its suggested change to the relevant policy file in the "
            "given or auto-discovered policy pack. Idempotent: re-accepting "
            "the same proposal id is a no-op if already applied."
        ),
    )
    server.add_tool(
        reject_proposal,
        name="reject_proposal",
        description=(
            "Reject a policy proposal (by id from list_proposals), "
            "optionally recording a reason, against the given or "
            "auto-discovered policy pack so it is not re-suggested without "
            "new evidence."
        ),
    )
    server.add_tool(
        validate_policy_pack,
        name="validate_policy_pack",
        description=(
            "Validate a policy pack (path optional, auto-discovered like "
            "`sarathi validate`) against Sarathi's required-input checklist "
            "for each lifecycle phase. Returns PASS/DRIFT/TODO counts and a "
            "per-item breakdown. Use this before running tasks to catch "
            "policy-pack gaps."
        ),
    )

    return server


def main() -> int:
    """Entry point for the `sarathi-mcp` console script: run the stdio MCP server."""
    try:
        server = create_server()
    except ImportError as exc:
        print(str(exc))
        return 1

    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
