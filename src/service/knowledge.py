"""Workspace knowledge center: wiki, skills, learnings, and context bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.evolve import Evolver
from src.policy import compile_policy_pack
from src.storage import Storage

from .errors import ServiceError
from .preferences import _required_text
from .proposals import (
    _acceptance_check,
    _behavior_assets,
    _dogfood_learning_record,
    _format_dogfood_learning_section,
    _proposal_summary,
    _reviewed_proposal_decisions,
    _reviewed_proposal_ids,
    _role_mappings,
    _synthesize_learning_records,
)
from .views import (
    _builtin_workflow_templates,
    _parse_workspace_learnings,
    _playbook_saved_views_for_learning,
    _playbook_template_for_learning,
    _workspace_learning_playbooks,
    _workspace_operational_views,
    _workspace_saved_views,
)


def _dogfood_acceptance(storage: Storage, workspace: dict[str, Any]) -> dict[str, Any]:
    operations = _workspace_operational_views(storage, workspace["id"])
    tasks = storage.list_tasks_for_workspace(workspace["id"])
    completed_tasks = [task for task in tasks if task["status"] == "done"]
    graphs = [diagram for diagram in operations["diagrams"] if diagram["kind"] == "dependency_graph"]
    handoff_diagrams = [diagram for diagram in operations["diagrams"] if diagram["kind"] == "handoff"]
    approved_handoff_diagrams = [
        diagram
        for diagram in handoff_diagrams
        if diagram.get("repository_action", {}).get("status") == "approved"
    ]
    checks = [
        _acceptance_check(
            "workspace",
            "Workspace is first-class and contains persisted events.",
            bool(operations["history"]),
            [event["id"] for event in operations["history"][:3]],
        ),
        _acceptance_check(
            "prd_ac",
            "At least one task has PRD/AC metadata.",
            any(task["metadata"].get("acceptance_criteria") for task in tasks),
            [task["id"] for task in tasks if task["metadata"].get("acceptance_criteria")],
        ),
        _acceptance_check(
            "task_graph",
            "A persisted dependency graph exists.",
            bool(graphs),
            [diagram["id"] for diagram in graphs],
        ),
        _acceptance_check(
            "evidence",
            "Execution evidence exists.",
            operations["usage"]["evidence"]["total"] > 0,
            [diagram["id"] for diagram in graphs],
        ),
        _acceptance_check(
            "review_loop",
            "An approved review loop exists.",
            operations["usage"]["reviews"]["by_status"].get("approved", 0) > 0,
            [diagram["id"] for diagram in operations["diagrams"] if diagram["kind"] == "review_loop"],
        ),
        _acceptance_check(
            "handoff",
            "Final handoff and repository-action approval are recorded.",
            bool(approved_handoff_diagrams),
            [diagram["id"] for diagram in approved_handoff_diagrams],
        ),
        _acceptance_check(
            "operational_views",
            "Lifecycle, history, diagrams, and usage are service-backed.",
            bool(operations["lifecycle"]) and bool(operations["diagrams"]),
            [diagram["id"] for diagram in operations["diagrams"][:3]],
        ),
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "blocked"
    completed_task = completed_tasks[-1] if completed_tasks else (tasks[-1] if tasks else None)
    learning_record = _dogfood_learning_record(workspace, checks, completed_task, status)
    return {
        "workspace_id": workspace["id"],
        "status": status,
        "checks": checks,
        "release_dossier": {
            "title": "Built with Sarathi",
            "built_with": "Sarathi",
            "redacted": True,
            "summary": (
                f"Sarathi dogfood acceptance is {status}: "
                f"{operations['usage']['tasks']['total']} tasks, "
                f"{operations['usage']['subtasks']['total']} subtasks, "
                f"{operations['usage']['evidence']['total']} evidence artifacts, "
                f"{operations['usage']['reviews']['total']} reviews, "
                f"{operations['usage']['handoffs']['total']} handoff records."
            ),
            "validation_commands": [
                "python3 -m pytest",
                "npm --prefix desktop run build",
                "npm --prefix desktop audit --omit=dev",
                "sarathi validate ./policy-pack",
            ],
        },
        "learning_record": learning_record,
        "operations": operations,
    }


def _approve_dogfood_learning(
    storage: Storage,
    workspace: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Dogfood learning must be explicitly approved before writing learnings.md.",
            409,
        )
    acceptance = _dogfood_acceptance(storage, workspace)
    if acceptance["status"] != "passed":
        raise ServiceError(
            "acceptance_blocked",
            "Dogfood acceptance must pass before learning can be accepted.",
            409,
        )
    learning_record = dict(acceptance["learning_record"])
    learning_record["status"] = "accepted"
    workspace_root = Path(workspace["root_path"]).expanduser()
    learning_path = workspace_root / "learnings.md"
    learning_path.parent.mkdir(parents=True, exist_ok=True)
    existing = learning_path.read_text() if learning_path.exists() else "# Sarathi Workspace Learnings\n"
    section = _format_dogfood_learning_section(learning_record, acceptance)
    if "## Accepted Sarathi Dogfood Learning" not in existing:
        learning_path.write_text(existing.rstrip() + "\n\n" + section + "\n")
    elif learning_record["task_id"] not in existing:
        learning_path.write_text(existing.rstrip() + "\n\n" + section + "\n")
    learning_record["path"] = str(learning_path)
    storage.create_lifecycle_event(
        workspace_id=workspace["id"],
        event_type="learning.accepted",
        payload={
            "object_id": learning_record["id"],
            "task_id": learning_record["task_id"],
            "target_file": learning_record["target_file"],
        },
    )
    return {"learning_record": learning_record, "acceptance": acceptance}


def _workspace_knowledge_center(
    storage: Storage,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    guide_status = _repository_guide_status(workspace_root)
    wiki_pages = _list_wiki_pages(workspace_root)
    learnings_status = _learnings_status(workspace_root)
    enriched_learnings = _enrich_learnings_with_linkages(storage, workspace, learnings_status)
    skills_summary = _skills_summary(workspace_root)
    recent_contexts = _recent_context_bundles_summary(storage, workspace["id"])
    proposals_summary = _proposal_summary(storage, workspace)
    section_health = {
        "wiki": {
            "page_count": len(wiki_pages),
            "deep_links": _count_wiki_deep_links(wiki_pages),
            "last_updated": _get_most_recent_wiki_update(workspace_root),
        },
        "context": {
            "total_bundles": recent_contexts.get("total_bundles", 0),
            "recent_count": recent_contexts.get("recent_count", 0),
            "unique_tasks": _count_unique_task_contexts(storage, workspace["id"]),
        },
        "proposals": {
            "pending": proposals_summary.get("pending_count", 0),
            "accepted": proposals_summary.get("accepted_count", 0),
            "rejected": proposals_summary.get("rejected_count", 0),
            "last_reviewed": proposals_summary.get("last_reviewed_at"),
        },
        "learnings": {
            "accepted_count": len(enriched_learnings.get("accepted_learnings", [])),
            "sections": learnings_status.get("sections", 0),
        },
    }
    accepted_context_guidance = _accepted_context_proposals(workspace_root)
    return {
        "workspace_id": workspace["id"],
        "guide": guide_status,
        "wiki": wiki_pages,
        "learnings": enriched_learnings,
        "skills": skills_summary,
        "recent_contexts": recent_contexts,
        "proposals": proposals_summary,
        "section_health": section_health,
        "context_compiler_guidance": accepted_context_guidance,
    }


def _workspace_wiki(workspace: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    pages = _list_wiki_pages(workspace_root)
    return {
        "workspace_id": workspace["id"],
        "pages": pages,
    }


def _workspace_wiki_page(workspace: dict[str, Any], page: str) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    wiki_dir = workspace_root / "wiki"
    page_path = _resolve_workspace_wiki_page_path(wiki_dir, page)
    if not wiki_dir.exists():
        raise ServiceError("not_found", "Wiki directory not found.", 404)
    if not page_path.exists():
        raise ServiceError("not_found", f"Wiki page '{page}' not found.", 404)
    content = page_path.read_text(encoding="utf-8") if page_path.is_file() else ""
    return {
        "workspace_id": workspace["id"],
        "page": page,
        "content": content,
        "path": str(page_path),
    }


def _save_workspace_wiki_page(workspace: dict[str, Any], body: Mapping[str, Any] | None) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    wiki_dir = workspace_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    page = _required_text(body, "page")
    content = _required_text(body, "content")
    page_path = _resolve_workspace_wiki_page_path(wiki_dir, page)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(content, encoding="utf-8")
    return {
        "workspace_id": workspace["id"],
        "page": page,
        "content": content,
        "path": str(page_path),
    }


def _workspace_skills(storage: Storage, workspace: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    skills = _list_skills(workspace_root)
    routes = _list_skill_routes(workspace_root)
    role_mappings = _role_mappings()
    behavior_assets = _behavior_assets(workspace_root)
    skills_file = workspace_root / "policy-pack" / "skills.md"
    evolution_proposals = _filtered_evolution_proposals(storage, workspace)
    evolution_history = _reviewed_evolution_history(workspace)
    return {
        "workspace_id": workspace["id"],
        "skills": skills,
        "routes": routes,
        "role_mappings": role_mappings,
        "behavior_assets": behavior_assets,
        "evolution_proposals": evolution_proposals,
        "evolution_history": evolution_history,
        "path": str(skills_file),
        "source_content": skills_file.read_text(encoding="utf-8") if skills_file.exists() else "",
    }


def _filtered_evolution_proposals(storage: Storage, workspace: dict[str, Any]) -> list[dict[str, Any]]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        return []
    records = _synthesize_learning_records(storage, workspace["id"])
    reviewed_ids = _reviewed_proposal_ids(policy_pack_path)
    skill_relevant_kinds = {"skill_update", "routing_hint"}
    skill_relevant_files = {"skills.md", "model-routing.md"}
    proposals = [
        proposal.to_artifact()
        for proposal in Evolver().generate_policy_proposals(learning_records=records)
        if proposal.proposal_id not in reviewed_ids
        and (
            proposal.proposal_kind in skill_relevant_kinds
            or any(
                proposal.policy_file.endswith(f) or f"policy-pack/{f}" in proposal.policy_file
                for f in skill_relevant_files
            )
        )
    ]
    return proposals


def _reviewed_evolution_history(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    if not policy_pack_path.exists():
        return []
    all_decisions = _reviewed_proposal_decisions(policy_pack_path)
    skill_relevant_kinds = {"skill_update", "routing_hint"}
    skill_relevant_files = {"skills.md", "model-routing.md"}
    history: list[dict[str, Any]] = []
    for decision in all_decisions:
        if not isinstance(decision, dict):
            continue
        status = str(decision.get("status", "")).strip().lower()
        if status not in {"accepted", "rejected"}:
            continue
        title = str(decision.get("title", "")).strip()
        proposal_id = str(decision.get("id", "")).strip()
        policy_file = str(decision.get("policy_file", "")).strip()
        reviewed_at = str(decision.get("reviewed_at", "")).strip()
        reason = str(decision.get("reason", "")).strip() if status == "rejected" else ""
        source = str(decision.get("source", "")).strip()
        raw_impacted_assets = decision.get("impacted_assets", [])
        if isinstance(raw_impacted_assets, list):
            impacted_assets = [str(asset).strip() for asset in raw_impacted_assets if str(asset).strip()]
        else:
            impacted_assets_str = str(raw_impacted_assets).strip()
            impacted_assets = [a.strip() for a in impacted_assets_str.split(",")] if impacted_assets_str else []
        proposal_kind = str(decision.get("proposal_kind", "")).strip() or (
            "skill_update" if "skills.md" in policy_file.lower()
            else "routing_hint" if "model-routing" in policy_file.lower()
            else "policy_note"
        )
        if not (proposal_kind in skill_relevant_kinds or any(f in policy_file.lower() for f in skill_relevant_files)):
            continue
        history.append({
            "status": status,
            "title": title,
            "proposal_id": proposal_id,
            "policy_file": policy_file,
            "proposal_kind": proposal_kind,
            "reviewed_at": reviewed_at,
            "reason": reason,
            "source": source,
            "impacted_assets": impacted_assets,
        })
    return sorted(history, key=lambda h: h["reviewed_at"], reverse=True)


def _save_workspace_skills(storage: Storage, workspace: dict[str, Any], body: Mapping[str, Any] | None) -> dict[str, Any]:
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_dir = workspace_root / "policy-pack"
    policy_pack_dir.mkdir(parents=True, exist_ok=True)
    skills_file = policy_pack_dir / "skills.md"
    content = _required_text(body, "content")
    skills_file.write_text(content, encoding="utf-8")
    return _workspace_skills(storage, workspace)


def _workspace_context_bundles(
    storage: Storage,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    bundles = _recent_context_bundles_detail(storage, workspace["id"])
    return {
        "workspace_id": workspace["id"],
        "bundles": bundles,
    }


def _repository_guide_status(workspace_root: Path) -> dict[str, Any]:
    required_files = [
        "SARATHI.md",
        "coding-standards.md",
        "guidelines.md",
    ]
    present = [f for f in required_files if (workspace_root / f).exists()]
    return {
        "status": "complete" if len(present) == len(required_files) else "partial" if present else "not_initialized",
        "present_files": present,
        "required_files": required_files,
    }


def _list_wiki_pages(workspace_root: Path) -> list[dict[str, Any]]:
    wiki_dir = workspace_root / "wiki"
    if not wiki_dir.exists():
        return []
    pages = []
    for md_file in sorted(wiki_dir.rglob("*.md")):
        relative = md_file.relative_to(wiki_dir)
        page_name = str(relative.with_suffix("")).replace("/", " / ")
        pages.append({
            "name": page_name,
            "path": str(relative),
            "exists": True,
        })
    return pages


def _resolve_workspace_wiki_page_path(wiki_dir: Path, page: str) -> Path:
    if ".." in page or page.startswith("/"):
        raise ServiceError("invalid_request", "Invalid wiki page path.", 400)
    page_path = wiki_dir / page
    if page_path.suffix.lower() != ".md":
        page_path = wiki_dir / f"{page}.md"
    return page_path


def _learnings_status(workspace_root: Path) -> dict[str, Any]:
    learning_path = workspace_root / "learnings.md"
    if not learning_path.exists():
        return {
            "status": "empty",
            "path": str(learning_path),
            "sections": 0,
            "accepted_learnings": [],
        }
    content = learning_path.read_text(encoding="utf-8")
    sections = content.count("## ")
    learning_sections = _parse_workspace_learnings(learning_path)
    accepted_learnings = [
        {
            "title": section.get("title", ""),
            "summary": section.get("summary", ""),
            "task_id": section.get("task_id", ""),
            "tags": section.get("tags", []),
            "evidence_refs": section.get("evidence_refs", []),
            "recommended_template_id": _playbook_template_for_learning(section),
            "recommended_view_ids": _playbook_saved_views_for_learning(section),
            "source_file": str(learning_path),
            "linked_proposal_id": None,
            "linked_proposal_title": None,
            "linked_playbook_id": None,
            "linked_playbook_name": None,
        }
        for section in learning_sections
    ]
    return {
        "status": "populated",
        "path": str(learning_path),
        "sections": sections,
        "accepted_learnings": accepted_learnings,
    }


def _enrich_learnings_with_linkages(
    storage: Storage,
    workspace: dict[str, Any],
    learnings_status: dict[str, Any],
) -> dict[str, Any]:
    accepted_learnings = learnings_status.get("accepted_learnings", [])
    if not accepted_learnings:
        return learnings_status
    workspace_root = Path(workspace["root_path"]).expanduser()
    policy_pack_path = workspace_root / "policy-pack"
    accepted_proposals = _reviewed_proposal_decisions(policy_pack_path)
    accepted_proposals_by_id = {
        str(p.get("id", "")).strip(): p
        for p in accepted_proposals
        if p.get("status") == "accepted" and p.get("id")
    }
    operations = _workspace_operational_views(storage, workspace["id"])
    templates = _builtin_workflow_templates()
    saved_views = _workspace_saved_views(operations)
    playbooks_by_task_id: dict[str, dict[str, Any]] = {}
    for playbook in _workspace_learning_playbooks(
        storage,
        workspace,
        templates=templates,
        saved_views=saved_views,
    ):
        provenance = playbook.get("provenance", {})
        task_id = provenance.get("task_id")
        if task_id:
            playbooks_by_task_id[str(task_id).strip()] = playbook
    enriched_learnings = []
    for learning in accepted_learnings:
        learning_task_id = str(learning.get("task_id") or "").strip()
        linked_proposal_id = None
        linked_proposal_title = None
        if learning_task_id:
            for prop_id, prop_data in accepted_proposals_by_id.items():
                evidence_refs = prop_data.get("evidence_refs", [])
                if isinstance(evidence_refs, list):
                    for ref in evidence_refs:
                        ref_str = str(ref).strip()
                        if ref_str.startswith(learning_task_id + ":"):
                            linked_proposal_id = prop_id
                            linked_proposal_title = prop_data.get("title")
                            break
                if linked_proposal_id:
                    break
        linked_playbook = playbooks_by_task_id.get(learning_task_id)
        linked_playbook_id = linked_playbook.get("id") if linked_playbook else None
        linked_playbook_name = linked_playbook.get("name") if linked_playbook else None
        enriched_learnings.append({
            **learning,
            "linked_proposal_id": linked_proposal_id,
            "linked_proposal_title": linked_proposal_title,
            "linked_playbook_id": linked_playbook_id,
            "linked_playbook_name": linked_playbook_name,
        })
    return {
        **learnings_status,
        "accepted_learnings": enriched_learnings,
    }


def _count_wiki_deep_links(wiki_pages: list[dict[str, Any]]) -> int:
    workspace_root = Path(wiki_pages[0]["path"]).parent.parent if wiki_pages else None
    if not workspace_root:
        return 0
    wiki_dir = workspace_root / "wiki"
    if not wiki_dir.exists():
        return 0
    link_count = 0
    for md_file in wiki_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            link_count += content.count("[[") + content.count("](")
        except Exception:
            pass
    return link_count


def _get_most_recent_wiki_update(workspace_root: Path) -> str | None:
    wiki_dir = workspace_root / "wiki"
    if not wiki_dir.exists():
        return None
    most_recent = 0.0
    for md_file in wiki_dir.rglob("*.md"):
        try:
            mtime = md_file.stat().st_mtime
            if mtime > most_recent:
                most_recent = mtime
        except Exception:
            pass
    if most_recent > 0:
        from datetime import datetime
        return datetime.fromtimestamp(most_recent).isoformat()
    return None


def _count_unique_task_contexts(storage: Storage, workspace_id: str) -> int:
    try:
        dispatch_dir = storage.tasks_dir(workspace_id)
        if not dispatch_dir.exists():
            return 0
        task_ids = set()
        for task_dir in dispatch_dir.iterdir():
            if task_dir.is_dir():
                task_ids.add(task_dir.name)
        return len(task_ids)
    except Exception:
        return 0


def _accepted_context_proposals(workspace_root: Path) -> list[dict[str, Any]]:
    policy_pack_dir = workspace_root / "policy-pack"
    if not policy_pack_dir.exists():
        return []
    context_guidance: list[dict[str, Any]] = []
    for md_file in policy_pack_dir.glob("*.md"):
        if md_file.name == "commands.md":
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            import re
            yaml_match = re.search(r"```yaml\s*(.*?)\s*```", content, re.DOTALL)
            if yaml_match:
                import yaml
                parsed = yaml.safe_load(yaml_match.group(1)) or {}
                for proposal in parsed.get("accepted_proposals", []):
                    if isinstance(proposal, dict) and proposal.get("proposal_kind") == "context_update":
                        context_guidance.append({
                            "title": proposal.get("title", ""),
                            "policy_file": proposal.get("policy_file", ""),
                            "suggested_change": proposal.get("suggested_change", ""),
                            "impacted_assets": proposal.get("impacted_assets", []),
                            "reviewed_at": proposal.get("reviewed_at", ""),
                        })
        except Exception:
            pass
    return context_guidance


def _skills_summary(workspace_root: Path) -> dict[str, Any]:
    policy_pack_dir = workspace_root / "policy-pack"
    skills_file = policy_pack_dir / "skills.md"
    if not skills_file.exists():
        return {
            "status": "not_found",
            "path": str(skills_file),
            "family_count": 0,
            "skill_count": 0,
        }
    skills = _list_skills(workspace_root)
    return {
        "status": "available",
        "path": str(skills_file),
        "family_count": len({skill.get("family") for skill in skills if skill.get("family")}),
        "skill_count": len(skills),
    }


def _list_skills(workspace_root: Path) -> list[dict[str, Any]]:
    policy_pack_dir = workspace_root / "policy-pack"
    skills_file = policy_pack_dir / "skills.md"
    if not skills_file.exists():
        return []
    compiled = compile_policy_pack(str(policy_pack_dir))
    raw_skills = compiled.typed_get("skills").as_dict()
    skills: list[dict[str, Any]] = []
    for family, payload in raw_skills.items():
        if family == "task_type_to_skill" or not isinstance(payload, Mapping):
            continue
        family_description = str(payload.get("description") or "").strip()
        for skill_name in payload.get("skills", []):
            if not isinstance(skill_name, str) or not skill_name.strip():
                continue
            skills.append(
                {
                    "name": skill_name.strip(),
                    "family": str(family),
                    "source": "policy-pack/skills.md",
                    "description": family_description,
                }
            )
    return skills


def _list_skill_routes(workspace_root: Path) -> list[dict[str, Any]]:
    policy_pack_dir = workspace_root / "policy-pack"
    skills_file = policy_pack_dir / "skills.md"
    if not skills_file.exists():
        return []
    compiled = compile_policy_pack(str(policy_pack_dir))
    raw_skills = compiled.typed_get("skills").as_dict()
    task_type_mapping = raw_skills.get("task_type_to_skill")
    if not isinstance(task_type_mapping, Mapping):
        return []
    routes: list[dict[str, Any]] = []
    for task_type, config in task_type_mapping.items():
        if not isinstance(task_type, str) or not task_type.strip():
            continue
        routes.append({
            "task_type": task_type.strip(),
            "primary": str(config.get("primary") or "").strip() if isinstance(config, dict) else "",
            "secondary": _parse_secondary(config.get("secondary")) if isinstance(config, dict) else [],
            "always_invoke": bool(config.get("always_invoke", False)) if isinstance(config, dict) else False,
        })
    return routes


def _parse_secondary(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if v and str(v).strip()]
    if isinstance(value, str) and value.strip():
        if "," in value:
            return [v.strip() for v in value.split(",") if v.strip()]
        return [value.strip()]
    return []


def _recent_context_bundles_summary(
    storage: Storage,
    workspace_id: str,
) -> dict[str, Any]:
    dispatches = storage.list_dispatches_for_workspace(workspace_id)
    dispatch_with_context = [d for d in dispatches if d.get("metadata", {}).get("context_pack")]
    recent = sorted(dispatch_with_context, key=lambda d: d.get("created_at", ""), reverse=True)[:10]
    return {
        "total_bundles": len(dispatch_with_context),
        "recent_count": len(recent),
        "bundles": [
            {
                "dispatch_id": d["id"],
                "task_id": d.get("task_id"),
                "agent": d.get("agent_name"),
                "created_at": d.get("created_at"),
            }
            for d in recent
        ],
    }


def _recent_context_bundles_detail(
    storage: Storage,
    workspace_id: str,
) -> list[dict[str, Any]]:
    dispatches = storage.list_dispatches_for_workspace(workspace_id)
    bundles = []
    for d in dispatches:
        metadata = d.get("metadata", {})
        context_pack = metadata.get("context_pack")
        if context_pack:
            agent_output = metadata.get("agent_output") if isinstance(metadata.get("agent_output"), Mapping) else {}
            artifact_index = metadata.get("artifact_index") if isinstance(metadata.get("artifact_index"), Mapping) else {}
            bundles.append({
                "dispatch_id": d["id"],
                "task_id": d.get("task_id"),
                "agent": d.get("agent_name"),
                "status": d.get("status"),
                "created_at": d.get("created_at"),
                "context_pack": {
                    "role": context_pack.get("role"),
                    "phase": context_pack.get("phase"),
                    "summary": context_pack.get("summary"),
                    "agent_input": {
                        "objective": context_pack.get("agent_input", {}).get("objective"),
                        "constraints": context_pack.get("agent_input", {}).get("constraints", []),
                        "acceptance_criteria": context_pack.get("agent_input", {}).get("acceptance_criteria", []),
                        "relevant_files": context_pack.get("agent_input", {}).get("relevant_files", []),
                        "prior_findings": context_pack.get("agent_input", {}).get("prior_findings", []),
                        "available_tools": context_pack.get("agent_input", {}).get("available_tools", []),
                        "token_budget": context_pack.get("agent_input", {}).get("token_budget"),
                    },
                    "estimated_tokens": context_pack.get("compilation", {}).get("estimated_tokens"),
                    "trimmed_sections": context_pack.get("compilation", {}).get("trimmed_sections", []),
                    "source_artifacts": [
                        {"type": sa.get("type"), "ref": sa.get("ref")}
                        for sa in context_pack.get("source_artifacts", [])
                    ],
                },
                "agent_output": {
                    "status": agent_output.get("status"),
                    "summary": agent_output.get("summary"),
                    "artifacts": agent_output.get("artifacts", []),
                    "decisions": agent_output.get("decisions", []),
                    "findings": agent_output.get("findings", []),
                    "next_recommended_agent": agent_output.get("next_recommended_agent"),
                },
                "artifact_index": {
                    "files_changed": artifact_index.get("files_changed", []),
                    "tests_run": artifact_index.get("tests_run", []),
                    "known_risks": artifact_index.get("known_risks", []),
                    "review_findings": artifact_index.get("review_findings", []),
                },
                "provenance": {
                    "sources": [
                        label
                        for label, present in (
                            ("context_pack", bool(context_pack)),
                            ("agent_output", bool(agent_output)),
                            ("artifact_index", bool(artifact_index)),
                            ("response_evidence", isinstance(metadata.get("response_evidence"), Mapping)),
                        )
                        if present
                    ]
                },
            })
    return sorted(bundles, key=lambda b: b.get("created_at", ""), reverse=True)[:20]

