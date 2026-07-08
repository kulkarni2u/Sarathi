"""Workspace evolution proposal review and dogfood learning helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from src.evolve import Evolver, ProposalReviewStore
from src.runtime import get_agent_role, list_phase_agent_roles
from src.storage import Storage

from .errors import ServiceError

logger = logging.getLogger("sarathi.service.proposals")


def _workspace_proposals(storage: Storage, workspace: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        return {"workspace_id": workspace["id"], "proposals": [], "reviewed_history": [], "status": "no_policy_pack"}
    records = _synthesize_learning_records(storage, workspace["id"])
    reviewed_history = sorted(
        _reviewed_proposal_decisions(policy_pack_path),
        key=lambda decision: str(decision.get("reviewed_at") or ""),
        reverse=True,
    )
    reviewed_ids = {
        decision.get("id")
        for decision in reviewed_history
        if isinstance(decision.get("id"), str)
    }
    proposals = [
        proposal.to_artifact()
        for proposal in Evolver().generate_policy_proposals(learning_records=records)
        if proposal.proposal_id not in reviewed_ids
    ]
    return {
        "workspace_id": workspace["id"],
        "proposals": proposals,
        "reviewed_history": reviewed_history,
        "status": "ok",
        "source": "synthesized_from_workspace_state",
    }


def _workspace_proposal_detail(
    storage: Storage,
    workspace: dict[str, Any],
    proposal_id: str,
) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        raise ServiceError("not_found", "Policy pack not found.", 404)
    target = _find_workspace_proposal(storage, workspace, proposal_id)
    if target is None:
        raise ServiceError("not_found", f"Proposal {proposal_id} not found.", 404)
    preview = ProposalReviewStore(policy_pack_path, mirror=False).preview_acceptance(target)
    return {
        "workspace_id": workspace["id"],
        "proposal": target.to_artifact(),
        "policy_preview": preview,
    }


def _accept_proposal(storage: Storage, workspace: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        raise ServiceError("not_found", "Policy pack not found.", 404)
    target = _find_workspace_proposal(storage, workspace, proposal_id)
    if target is None:
        raise ServiceError("not_found", f"Proposal {proposal_id} not found.", 404)
    store = ProposalReviewStore(policy_pack_path, mirror=False)
    decision = store.accept(target)
    _record_decision_row(storage, workspace["id"], decision)
    storage.create_lifecycle_event(
        workspace_id=workspace["id"],
        event_type="proposal.accepted",
        payload={"proposal_id": proposal_id, "title": target.title, "policy_file": target.policy_file},
    )
    return {"workspace_id": workspace["id"], "proposal_id": proposal_id, "decision": decision}


def _reject_proposal(
    storage: Storage,
    workspace: dict[str, Any],
    proposal_id: str,
    reason: str | None,
) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        raise ServiceError("not_found", "Policy pack not found.", 404)
    target = _find_workspace_proposal(storage, workspace, proposal_id)
    if target is None:
        raise ServiceError("not_found", f"Proposal {proposal_id} not found.", 404)
    store = ProposalReviewStore(policy_pack_path, mirror=False)
    decision = store.reject(target, reason=reason)
    _record_decision_row(storage, workspace["id"], decision)
    storage.create_lifecycle_event(
        workspace_id=workspace["id"],
        event_type="proposal.rejected",
        payload={"proposal_id": proposal_id, "title": target.title, "reason": reason},
    )
    return {"workspace_id": workspace["id"], "proposal_id": proposal_id, "decision": decision}


def _record_decision_row(storage: Storage, workspace_id: str, decision: dict[str, Any]) -> None:
    """Persist the decision as a queryable row, best-effort.

    The service already owns the correct ``Storage`` handle and
    ``workspace_id`` here (no path-based workspace lookup needed, unlike
    ``proposal_sync.ProposalSync``), so this writes the row directly rather
    than going through the mirror. It never raises -- a storage hiccup must
    not turn an otherwise-successful accept/reject into a user-facing error.
    """
    try:
        storage.upsert_proposal_decision(
            workspace_id=workspace_id,
            proposal_id=str(decision.get("id") or ""),
            status=str(decision.get("status") or ""),
            policy_file=decision.get("policy_file"),
            title=decision.get("title"),
            source=decision.get("source"),
            reason=decision.get("reason"),
            payload=decision,
            reviewed_at=decision.get("reviewed_at"),
        )
    except Exception:
        logger.warning("Failed to record proposal decision row", exc_info=True)


def _synthesize_learning_records(storage: Storage, workspace_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    phase_by_subtask: dict[str, str] = {}
    for task in storage.list_tasks_for_workspace(workspace_id):
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        complexity = str(task.get("metadata", {}).get("complexity") or "medium")
        generated_at = str(task.get("updated_at") or task.get("created_at") or "")
        repeated_failures: dict[str, int] = {}
        provider_failures: dict[tuple[str, str], int] = {}
        escalations: dict[str, int] = {}
        iteration_hotspots: list[dict[str, Any]] = []
        context_gaps: list[dict[str, Any]] = []

        subtasks = storage.list_subtasks_for_task(task_id)
        for subtask in subtasks:
            phase_by_subtask[subtask["id"]] = _proposal_phase_for_subtask(subtask)
        dispatches = storage.list_dispatches_for_task(task_id)
        for dispatch in dispatches:
            metadata = dispatch.get("metadata", {})
            phase = _proposal_phase_for_dispatch(metadata, phase_by_subtask)
            if dispatch.get("status") == "failed":
                repeated_failures[phase] = repeated_failures.get(phase, 0) + 1
                provider = str(dispatch.get("agent_name") or "unknown").strip() or "unknown"
                key = (phase, provider)
                provider_failures[key] = provider_failures.get(key, 0) + 1
            context_pack = metadata.get("context_pack") if isinstance(metadata.get("context_pack"), dict) else {}
            if context_pack:
                trimmed = context_pack.get("compilation", {}).get("trimmed_sections", [])
                estimated = context_pack.get("compilation", {}).get("estimated_tokens", 0)
                budget = context_pack.get("agent_input", {}).get("token_budget", 0)
                if trimmed:
                    reasons = ["trimmed_sections"]
                    if budget and estimated and estimated >= budget * 0.9:
                        reasons.append("near_budget")
                    context_gaps.append({
                        "phase": phase,
                        "count": 1,
                        "trimmed_sections": trimmed,
                        "reasons": reasons,
                        "estimated_tokens": estimated,
                        "token_budget": budget,
                    })
                elif budget and estimated and estimated >= budget * 0.9:
                    context_gaps.append({
                        "phase": phase,
                        "count": 1,
                        "trimmed_sections": [],
                        "reasons": ["near_budget"],
                        "estimated_tokens": estimated,
                        "token_budget": budget,
                    })
        reviews = storage.list_review_runs_for_task(task_id)
        rejected_reviews = [review for review in reviews if review.get("status") == "rejected"]
        if rejected_reviews:
            escalations["Review"] = len(rejected_reviews)
        if len(dispatches) > 1:
            iteration_hotspots.append({"phase": "Build", "iterations": len(dispatches)})
        has_signals = repeated_failures or provider_failures or escalations or iteration_hotspots or context_gaps
        if not has_signals:
            continue
        records.append(
            {
                "task_id": task_id,
                "complexity": complexity,
                "generated_at": generated_at,
                "summary": f"Workspace proposal synthesis for {task.get('title') or task_id}",
                "repeated_failures": [
                    {"phase": phase, "count": count}
                    for phase, count in sorted(repeated_failures.items())
                ],
                "provider_failures": [
                    {"phase": phase, "provider": provider, "count": count}
                    for (phase, provider), count in sorted(provider_failures.items())
                ],
                "escalations": [
                    {"phase": phase, "count": count}
                    for phase, count in sorted(escalations.items())
                ],
                "iteration_hotspots": iteration_hotspots,
                "context_gaps": context_gaps,
                "phase_outcomes": [],
            }
        )
    return records


def _find_workspace_proposal(storage: Storage, workspace: dict[str, Any], proposal_id: str):
    proposals = Evolver().generate_policy_proposals(
        learning_records=_synthesize_learning_records(storage, workspace["id"])
    )
    matches = [
        proposal
        for proposal in proposals
        if proposal.proposal_id == proposal_id or proposal.proposal_id.startswith(proposal_id)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _reviewed_proposal_ids(policy_pack_path: Path) -> set[str]:
    return {decision.get("id") for decision in _reviewed_proposal_decisions(policy_pack_path) if isinstance(decision.get("id"), str)}


def _reviewed_proposal_decisions(policy_pack_path: Path) -> list[dict[str, Any]]:
    review_dir = policy_pack_path / ".sarathi-proposals"
    if not review_dir.exists():
        return []
    reviewed: list[dict[str, Any]] = []
    for path in review_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            reviewed.append(payload)
    return reviewed


def _proposal_summary(storage: Storage, workspace: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        return {
            "pending_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "last_reviewed_at": None,
        }
    records = _synthesize_learning_records(storage, workspace["id"])
    reviewed_decisions = _reviewed_proposal_decisions(policy_pack_path)
    reviewed_ids = {
        decision.get("id")
        for decision in reviewed_decisions
        if isinstance(decision.get("id"), str) and str(decision.get("id")).strip()
    }
    pending_count = len(
        [
            proposal
            for proposal in Evolver().generate_policy_proposals(learning_records=records)
            if proposal.proposal_id not in reviewed_ids
        ]
    )
    accepted = [decision for decision in reviewed_decisions if decision.get("status") == "accepted"]
    rejected = [decision for decision in reviewed_decisions if decision.get("status") == "rejected"]
    reviewed_at_values = [
        str(decision.get("reviewed_at"))
        for decision in reviewed_decisions
        if isinstance(decision.get("reviewed_at"), str) and str(decision.get("reviewed_at")).strip()
    ]
    return {
        "pending_count": pending_count,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "last_reviewed_at": max(reviewed_at_values) if reviewed_at_values else None,
    }


def _proposal_phase_for_subtask(subtask: Mapping[str, Any]) -> str:
    metadata = subtask.get("metadata") if isinstance(subtask.get("metadata"), Mapping) else {}
    role = str(metadata.get("role") or "").strip()
    return {
        "Disha": "Plan",
        "Pravaha": "Build",
        "Nirnaya": "Review",
        "Samanvaya": "Review",
        "Sarathi": "Plan",
    }.get(role, "Build")


def _role_mappings() -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in list_phase_agent_roles():
        phase = str(mapping.get("phase") or "").strip()
        role_name = str(mapping.get("name") or "").strip()
        role_key = str(mapping.get("key") or "").strip()
        if not phase or not role_name or not role_key:
            continue
        identity = (phase, role_key)
        if identity in seen:
            continue
        seen.add(identity)
        role = get_agent_role(role_key)
        mappings.append(
            {
                "role": role.name,
                "phase": phase,
                "purpose": role.description,
            }
        )
    return mappings


def _behavior_assets(workspace_root: Path) -> list[dict[str, Any]]:
    candidates = [
        ("policy-pack/skills.md", "Skill routing and provider selection"),
        ("SARATHI.md", "Repository-level orientation and shared operating context"),
        ("learnings.md", "Accepted learnings and reusable execution patterns"),
        ("wiki/context-compiler.md", "Context compilation guidance and omission rules"),
    ]
    assets: list[dict[str, Any]] = []
    for relative_path, purpose in candidates:
        asset_path = workspace_root / relative_path
        assets.append(
            {
                "path": relative_path,
                "exists": asset_path.exists(),
                "purpose": purpose,
            }
        )
    return assets


def _proposal_phase_for_dispatch(
    metadata: Mapping[str, Any],
    phase_by_subtask: Mapping[str, str],
) -> str:
    subtask_id = metadata.get("subtask_id")
    if isinstance(subtask_id, str) and subtask_id in phase_by_subtask:
        return phase_by_subtask[subtask_id]
    return "Build"


def _acceptance_check(
    check_id: str,
    label: str,
    passed: bool,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "blocked",
        "evidence_refs": evidence_refs,
    }


def _dogfood_learning_record(
    workspace: dict[str, Any],
    checks: list[dict[str, Any]],
    task: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    task_id = task["id"] if task is not None else "workspace"
    return {
        "id": f"dogfood-{workspace['id']}-{task_id}",
        "status": "proposed",
        "task_id": task_id,
        "target_file": "learnings.md",
        "summary": (
            "A workspace-scoped operational snapshot can prove the full Sarathi loop "
            "without exposing private paths."
        ),
        "tags": ["dogfood-fixture", "workspace-first", "persist-before-publish"],
        "evidence_refs": [
            evidence_ref
            for check in checks
            for evidence_ref in check["evidence_refs"]
        ],
        "acceptance_status": status,
    }


def _format_dogfood_learning_section(
    learning_record: dict[str, Any],
    acceptance: dict[str, Any],
) -> str:
    checks = "\n".join(
        f"- {check['id']}: {check['status']} ({', '.join(check['evidence_refs']) or 'no refs'})"
        for check in acceptance["checks"]
    )
    tags = ", ".join(learning_record["tags"])
    return (
        "## Accepted Sarathi Dogfood Learning\n\n"
        f"- Task: {learning_record['task_id']}\n"
        f"- Status: {learning_record['acceptance_status']}\n"
        f"- Tags: {tags}\n"
        f"- Summary: {learning_record['summary']}\n"
        "- Evidence:\n"
        f"{checks}\n"
    )

