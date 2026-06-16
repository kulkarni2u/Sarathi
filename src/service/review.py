"""Review run helpers: handoffs, checkpoints, evidence findings, and review verdicts."""

from __future__ import annotations

from typing import Any, Mapping

from src.storage import Storage

from .errors import ServiceError
from .preferences import (
    _REPOSITORY_ACTION_MODES,
    _effective_repository_action_preference,
    _optional_text,
)
from .scheduling import _graph_for_task
from .views import _latest_or_none, _unique_ordered


def _build_normalized_completion_context(
    dispatches: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build normalized completion context from dispatches and evidence.

    Prefers normalized agent_output and artifact_index over raw response_evidence
    to enable later resumes without needing to parse raw provider blobs first.
    """
    all_files_changed: list[str] = []
    all_tests_run: list[str] = []
    all_findings: list[str] = []
    all_risks: list[str] = []
    summaries: list[str] = []
    decisions: list[str] = []

    for dispatch in dispatches:
        dispatch_metadata = dispatch.get("metadata", {})
        agent_output = dispatch_metadata.get("agent_output")
        artifact_index = dispatch_metadata.get("artifact_index")
        response_evidence = dispatch_metadata.get("response_evidence", {})

        if isinstance(agent_output, Mapping):
            summary = agent_output.get("summary")
            if isinstance(summary, str) and summary.strip():
                summaries.append(summary.strip())
            findings = agent_output.get("findings", [])
            if isinstance(findings, list):
                all_findings.extend(str(f).strip() for f in findings if str(f).strip())
            dispatch_decisions = agent_output.get("decisions", [])
            if isinstance(dispatch_decisions, list):
                decisions.extend(str(d).strip() for d in dispatch_decisions if str(d).strip())

        if isinstance(artifact_index, Mapping):
            files = artifact_index.get("files_changed", [])
            if isinstance(files, list):
                all_files_changed.extend(str(f).strip() for f in files if str(f).strip())
            tests = artifact_index.get("tests_run", [])
            if isinstance(tests, list):
                all_tests_run.extend(str(t).strip() for t in tests if str(t).strip())
            risks = artifact_index.get("known_risks", [])
            if isinstance(risks, list):
                all_risks.extend(str(r).strip() for r in risks if str(r).strip())

        if not artifact_index and isinstance(response_evidence, Mapping):
            changed_files = response_evidence.get("changed_files", [])
            if isinstance(changed_files, list):
                all_files_changed.extend(str(f).strip() for f in changed_files if str(f).strip())

    return {
        "files_changed": _unique_ordered(all_files_changed),
        "tests_run": _unique_ordered(all_tests_run),
        "findings": _unique_ordered(all_findings[:20]),
        "risks": _unique_ordered(all_risks[:10]),
        "summaries": summaries[-3:],
        "decisions": decisions[-6:],
    }


def _create_task_handoff(storage: Storage, task: dict[str, Any]) -> dict[str, Any]:
    reviews = storage.list_review_runs_for_task(task["id"])
    approved_reviews = [review for review in reviews if review["status"] == "approved"]
    if not approved_reviews:
        raise ServiceError(
            "approval_required",
            "An approved review is required before final handoff.",
            409,
        )
    graph = _graph_for_task(storage, task)
    evidence = storage.list_evidence_artifacts_for_task(task["id"])
    dispatches = storage.list_dispatches_for_task(task["id"])
    latest_review = approved_reviews[-1]
    ac_coverage = latest_review["metadata"].get("ac_coverage", [])
    workspace = storage.get_workspace(task["workspace_id"])
    repository_action_preference = _effective_repository_action_preference(task, workspace)
    summary = (
        f"Sarathi handoff for {task['title']}: "
        f"{len([node for node in graph['nodes'] if node['status'] == 'complete'])}/"
        f"{len(graph['nodes'])} units complete, {len(evidence)} evidence artifacts, "
        f"{len(approved_reviews)} approved reviews."
    )

    normalized_completion_context = _build_normalized_completion_context(dispatches, evidence)

    handoff = storage.create_handoff(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        from_agent="Sarathi",
        to_agent="User",
        summary=summary,
        metadata={
            "task_title": task["title"],
            "completed_units": [node["id"] for node in graph["nodes"] if node["status"] == "complete"],
            "open_units": [node["id"] for node in graph["nodes"] if node["status"] != "complete"],
            "evidence_ids": [item["id"] for item in evidence],
            "dispatch_ids": [item["id"] for item in dispatches],
            "review_ids": [item["id"] for item in approved_reviews],
            "ac_coverage": ac_coverage,
            "repository_action_preference": repository_action_preference,
            "repository_action": {
                "status": "pending",
                "action": None,
                "mode": repository_action_preference["mode"],
            },
            "normalized_completion_context": normalized_completion_context,
        },
    )
    gate = storage.create_approval_gate(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        name="Repository action",
        status="pending",
        metadata={
            "requires_human": True,
            "handoff_id": handoff["id"],
            "allowed_actions": list(_REPOSITORY_ACTION_MODES),
            "default_action": repository_action_preference["mode"],
        },
    )
    task_metadata = dict(task["metadata"])
    task_metadata["phase"] = "repository_action_pending"
    storage.update_task(task["id"], status="repository_action_pending", metadata=task_metadata)
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="handoff.created",
        payload={"object_id": handoff["id"], "repository_action_gate": gate["id"]},
    )
    checkpoint = _create_task_checkpoint(
        storage,
        task,
        handoff,
        approved_reviews,
        next_start_point="Start from the handoff summary and approved review context.",
    )
    return {"handoff": handoff, "repository_action_gate": gate, "checkpoint": checkpoint}


def _record_repository_action(
    storage: Storage,
    task: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Repository actions require explicit approval.",
            409,
        )
    action = _optional_text(body, "action") or "no_action"
    if action not in _REPOSITORY_ACTION_MODES:
        raise ServiceError("invalid_request", "Unsupported repository action.", 400)
    handoff = _latest_or_none(storage.list_handoffs_for_task(task["id"]))
    if handoff is None:
        raise ServiceError("not_found", "Create handoff before repository action.", 404)
    approved_reviews = [
        review
        for review in storage.list_review_runs_for_task(task["id"])
        if review["status"] == "approved"
    ]
    metadata = dict(handoff["metadata"])
    repository_action = {
        "status": "approved",
        "action": action,
        "mode": action,
        "note": _optional_text(body, "note"),
    }
    metadata["repository_action"] = repository_action
    updated_handoff = storage.create_handoff(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        from_agent="Sarathi",
        to_agent="User",
        summary=handoff["summary"],
        metadata=metadata,
    )
    gate = storage.create_approval_gate(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        name="Repository action",
        status="approved",
        metadata={
            "handoff_id": updated_handoff["id"],
            "action": action,
            "requires_human": True,
        },
    )
    task_metadata = dict(task["metadata"])
    task_metadata["phase"] = "done"
    storage.update_task(task["id"], status="done", metadata=task_metadata)
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="repository_action.approved",
        payload={"object_id": updated_handoff["id"], "action": action, "approval_gate": gate["id"]},
    )
    checkpoint = _create_task_checkpoint(
        storage,
        task,
        updated_handoff,
        approved_reviews,
        next_start_point="Start from the completed handoff summary and repository-action result.",
    )
    return {
        "handoff": updated_handoff,
        "repository_action": repository_action,
        "approval_gate": gate,
        "checkpoint": checkpoint,
    }


def _create_task_checkpoint(
    storage: Storage,
    task: dict[str, Any],
    handoff: dict[str, Any],
    approved_reviews: list[dict[str, Any]],
    *,
    next_start_point: str,
) -> dict[str, Any]:
    workspace = storage.get_workspace(task["workspace_id"])
    if workspace is None:
        raise ServiceError("not_found", "Workspace not found.", 404)
    handoff_metadata = handoff.get("metadata") or {}
    repository_action_preference = handoff_metadata.get("repository_action_preference")
    if repository_action_preference is None:
        repository_action_preference = _effective_repository_action_preference(task, workspace)
    evidence_refs = handoff_metadata.get("evidence_ids")
    if not isinstance(evidence_refs, list):
        evidence_refs = [item["id"] for item in storage.list_evidence_artifacts_for_task(task["id"])]
    key_decisions = [
        review["summary"]
        for review in approved_reviews
        if review.get("summary")
    ][:3]
    if not key_decisions and handoff["summary"]:
        key_decisions = [handoff["summary"]]
    return storage.create_checkpoint_capsule(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        project_id=task["metadata"].get("project_id"),
        summary=handoff["summary"],
        key_decisions=key_decisions,
        evidence_refs=evidence_refs,
        repository_action_preference=repository_action_preference,
        next_start_point=next_start_point,
        created_by="Sarathi",
    )


def _run_task_review(
    storage: Storage,
    task: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    review_type = _optional_text(body, "review_type") or "code"
    subtasks = storage.list_subtasks_for_task(task["id"])
    evidence = storage.list_evidence_artifacts_for_task(task["id"])
    evidence_by_id = {item["id"]: item for item in evidence}
    evidenced_subtask_ids = {
        str(item["metadata"].get("subtask_id"))
        for item in evidence
        if item["metadata"].get("subtask_id")
    }
    review_units = [subtask for subtask in subtasks if subtask["status"] == "review"]
    if not review_units:
        review_units = [
            subtask
            for subtask in subtasks
            if subtask["status"] in {"complete", "done"} and subtask["id"] in evidenced_subtask_ids
        ]
    missing_evidence = [
        subtask["id"] for subtask in review_units if subtask["id"] not in evidenced_subtask_ids
    ]
    ac_coverage = _acceptance_coverage(task, evidence)
    reviewed_evidence = [
        item
        for item in evidence
        if str(item["metadata"].get("subtask_id")) in {subtask["id"] for subtask in review_units}
    ]
    diff_summary = _review_diff_summary(reviewed_evidence)
    findings = _approved_review_findings(reviewed_evidence)
    coverage_gaps = _coverage_gap_ids(ac_coverage)
    if diff_summary.get("provider_spec_references", 0):
        findings.extend(_coverage_gap_findings(ac_coverage))
    blocking_findings = _blocking_review_findings(findings)

    if review_units and not missing_evidence and not blocking_findings and not coverage_gaps:
        completed = [
            subtask
            if subtask["status"] in {"complete", "done"}
            else storage.update_subtask(subtask["id"], status="complete")
            for subtask in review_units
        ]
        review = storage.create_review_run(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            status="approved",
            summary="Review approved with dispatch evidence.",
            metadata={
                "review_type": review_type,
                "reviewed_subtasks": [subtask["id"] for subtask in review_units],
                "ac_coverage": ac_coverage,
                "evidence_ids": [item["id"] for item in evidence],
                "diff_summary": diff_summary,
                "findings": findings,
            },
        )
        storage.create_lifecycle_event(
            workspace_id=task["workspace_id"],
            task_id=task["id"],
            event_type="review.completed",
            payload={
                "object_id": review["id"],
                "status": review["status"],
                "completed_subtasks": [subtask["id"] for subtask in completed],
            },
        )
        return {"review": review, "completed_subtasks": completed, "requeued_subtasks": []}

    rejection_summary = "Review rejected because evidence is missing."
    rejection_findings = _missing_evidence_findings(missing_evidence, evidence_by_id)
    rejection_subtask_ids = {
        subtask["id"] for subtask in review_units if subtask["id"] in missing_evidence
    }
    if not missing_evidence and (blocking_findings or coverage_gaps):
        rejection_summary = "Review rejected because provider evidence indicates spec drift."
        rejection_findings = findings
        rejection_subtask_ids = _review_requeue_subtask_ids(
            review_units=review_units,
            blocking_findings=blocking_findings,
            coverage_gaps=coverage_gaps,
        )

    requeued = [
        storage.update_subtask(subtask["id"], status="in_progress")
        for subtask in review_units
        if subtask["id"] in rejection_subtask_ids
    ]
    review = storage.create_review_run(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        status="rejected",
        summary=rejection_summary,
        metadata={
            "review_type": review_type,
            "reviewed_subtasks": [subtask["id"] for subtask in review_units],
            "missing_evidence": missing_evidence,
            "coverage_gaps": coverage_gaps,
            "blocking_finding_ids": [str(item.get("id")) for item in blocking_findings if item.get("id")],
            "ac_coverage": ac_coverage,
            "evidence_ids": [item["id"] for item in evidence],
            "diff_summary": diff_summary,
            "findings": rejection_findings,
        },
    )
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="review.rejected",
        payload={
            "object_id": review["id"],
            "status": review["status"],
            "missing_evidence": missing_evidence,
            "requeued_subtasks": [subtask["id"] for subtask in requeued],
        },
    )
    return {"review": review, "completed_subtasks": [], "requeued_subtasks": requeued}


def _acceptance_coverage(task: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    criteria = task["metadata"].get("acceptance_criteria", [])
    if not isinstance(criteria, list):
        criteria = []
    has_evidence = bool(evidence)
    spec_refs: list[dict[str, Any]] = []
    for item in evidence:
        for reference in _spec_references_from_evidence(item):
            spec_refs.append(
                {
                    "ac_id": str(reference.get("ac_id") or "").strip() or None,
                    "criterion": str(reference.get("criterion") or "").strip() or None,
                    "evidence_id": item["id"],
                }
            )
    has_structured_spec_refs = bool(spec_refs)
    return [
        {
            "id": f"AC-{index + 1:02d}",
            "criterion": str(criterion),
            "covered": (
                bool(_matching_spec_reference_ids(spec_refs, f"AC-{index + 1:02d}", str(criterion)))
                if has_structured_spec_refs
                else has_evidence
            ),
            "evidence_ids": (
                _matching_spec_reference_ids(spec_refs, f"AC-{index + 1:02d}", str(criterion))
                if has_structured_spec_refs
                else [item["id"] for item in evidence] if has_evidence else []
            ),
        }
        for index, criterion in enumerate(criteria)
    ]


def _review_diff_summary(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    files: list[str] = []
    provider_trace_findings = 0
    provider_trace_providers: list[str] = []
    provider_diff_hunks = 0
    provider_diff_providers: list[str] = []
    provider_diff_blockers = 0
    provider_diff_confidences: list[float] = []
    provider_diff_risk_categories: list[str] = []
    provider_diff_highlights: list[str] = []
    provider_diff_region_inputs: list[dict[str, Any]] = []
    provider_spec_references = 0
    provider_spec_providers: list[str] = []
    for item in evidence:
        changed_files = _files_changed_from_evidence(item)
        if changed_files:
            files.extend(changed_files)

        provider_trace_findings_for_item = _provider_trace_findings_from_evidence(item)
        provider_trace_findings += len(provider_trace_findings_for_item)
        provider_trace_providers.extend(
            str(finding.get("provider")).strip()
            for finding in provider_trace_findings_for_item
            if isinstance(finding.get("provider"), str) and str(finding.get("provider")).strip()
        )

        diff_hunks = _diff_hunks_from_evidence(item)
        provider_diff_hunks += len(diff_hunks)
        provider_diff_providers.extend(
            str(hunk.get("provider")).strip()
            for hunk in diff_hunks
            if isinstance(hunk.get("provider"), str) and str(hunk.get("provider")).strip()
        )
        for hunk in diff_hunks:
            if not isinstance(hunk, Mapping):
                continue
            status = str(hunk.get("status") or "").strip().lower()
            if status in {"fail", "blocked", "rejected"}:
                provider_diff_blockers += 1
            confidence = hunk.get("confidence")
            if isinstance(confidence, (int, float)):
                provider_diff_confidences.append(float(confidence))
            category = str(hunk.get("category") or "").strip()
            if category:
                provider_diff_risk_categories.append(category)
                file_path = str(hunk.get("file_path") or "").strip()
                line_start = hunk.get("line_start")
                line_end = hunk.get("line_end")
                if file_path and isinstance(line_start, int) and isinstance(line_end, int):
                    provider_diff_highlights.append(
                        f"{category} / {file_path}:{line_start}-{line_end}"
                    )
            provider_diff_region_inputs.append(
                {
                    "file_path": str(hunk.get("file_path") or "").strip() or None,
                    "category": str(hunk.get("category") or "").strip() or None,
                    "line_start": hunk.get("line_start"),
                    "line_end": hunk.get("line_end"),
                    "severity": str(hunk.get("severity") or "info"),
                    "confidence": (
                        float(hunk.get("confidence"))
                        if isinstance(hunk.get("confidence"), (int, float))
                        else None
                    ),
                }
            )

        spec_references = _spec_references_from_evidence(item)
        provider_spec_references += len(spec_references)
        provider_spec_providers.extend(
            str(reference.get("provider")).strip()
            for reference in spec_references
            if isinstance(reference.get("provider"), str) and str(reference.get("provider")).strip()
        )

    unique_files = _unique_ordered(files)
    provider_diff_regions = _cluster_diff_regions(provider_diff_region_inputs)
    provider_diff_confidence = _average_confidence(provider_diff_confidences)
    review_confidence = _review_confidence_summary(
        provider_diff_blockers=provider_diff_blockers,
        provider_diff_confidence=provider_diff_confidence,
    )
    return {
        "changed_files": len(unique_files),
        "files": unique_files,
        "provider_trace_findings": provider_trace_findings,
        "provider_trace_providers": _unique_ordered(provider_trace_providers),
        "provider_diff_hunks": provider_diff_hunks,
        "provider_diff_providers": _unique_ordered(provider_diff_providers),
        "provider_diff_blockers": provider_diff_blockers,
        "provider_diff_confidence": provider_diff_confidence,
        "provider_diff_risk_categories": _unique_ordered(provider_diff_risk_categories),
        "provider_diff_highlights": _unique_ordered(provider_diff_highlights),
        "provider_diff_regions": provider_diff_regions,
        "review_confidence_verdict": review_confidence["verdict"],
        "review_confidence_reasons": review_confidence["reasons"],
        "provider_spec_references": provider_spec_references,
        "provider_spec_providers": _unique_ordered(provider_spec_providers),
    }


def _approved_review_findings(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    index = 1
    for item in evidence:
        subtask_id = str(item["metadata"].get("subtask_id") or "")
        provider_name = str(item["metadata"].get("provider") or "") or None
        structured_findings_added = False

        for structured in _artifact_review_findings(item):
            file_path = structured.get("file_path")
            file_text = str(file_path).strip() if file_path is not None else ""
            findings.append(
                {
                    "id": f"finding-{index:02d}",
                    "check": str(structured.get("check") or "provider_trace"),
                    "status": str(structured.get("status") or "pass"),
                    "severity": str(structured.get("severity") or "info"),
                    "message": str(structured.get("message") or "Provider review evidence."),
                    "file_path": file_text or None,
                    "line_start": structured.get("line_start") if isinstance(structured.get("line_start"), int) else None,
                    "line_end": structured.get("line_end") if isinstance(structured.get("line_end"), int) else None,
                    "header": str(structured.get("header") or "").strip() or None,
                    "excerpt": str(structured.get("excerpt") or "").strip() or None,
                    "category": str(structured.get("category") or "").strip() or None,
                    "confidence": (
                        round(float(structured.get("confidence")), 2)
                        if isinstance(structured.get("confidence"), (int, float))
                        else None
                    ),
                    "suggestion": str(structured.get("suggestion") or "").strip() or None,
                    "criterion": str(structured.get("criterion") or "").strip() or None,
                    "ac_id": str(structured.get("ac_id") or "").strip() or None,
                    "subtask_id": subtask_id,
                    "evidence_id": item["id"],
                    "provider": (
                        str(structured.get("provider")).strip()
                        if isinstance(structured.get("provider"), str) and str(structured.get("provider")).strip()
                        else provider_name or None
                    ),
                }
            )
            index += 1
            structured_findings_added = True

        changed_files = _files_changed_from_evidence(item)
        if structured_findings_added or not changed_files:
            continue
        for file_path in changed_files:
            file_text = str(file_path).strip()
            if not file_text:
                continue
            findings.append(
                {
                    "id": f"finding-{index:02d}",
                    "check": "diff_file",
                    "status": "pass",
                    "severity": "info",
                    "message": f"{file_text} included in review scope.",
                    "file_path": file_text,
                    "line_start": 1,
                    "line_end": 1,
                    "subtask_id": subtask_id,
                    "evidence_id": item["id"],
                    "provider": provider_name or None,
                }
            )
            index += 1
    return findings


def _normalized_evidence_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata", {})
    artifact_index = metadata.get("artifact_index")
    agent_output = metadata.get("agent_output")
    response_evidence = metadata.get("response_evidence", {})
    if not isinstance(response_evidence, Mapping):
        response_evidence = {}
    return {
        "artifact_index": artifact_index if isinstance(artifact_index, Mapping) else {},
        "agent_output": agent_output if isinstance(agent_output, Mapping) else {},
        "response_evidence": response_evidence,
    }


def _artifact_review_findings(item: dict[str, Any]) -> list[dict[str, Any]]:
    findings = _normalized_evidence_metadata(item)["artifact_index"].get("review_findings")
    if not isinstance(findings, list):
        return []
    return [dict(finding) for finding in findings if isinstance(finding, Mapping)]


def _files_changed_from_evidence(item: dict[str, Any]) -> list[str]:
    normalized = _normalized_evidence_metadata(item)
    files = normalized["artifact_index"].get("files_changed", [])
    if isinstance(files, list) and files:
        return [str(f).strip() for f in files if str(f).strip()]
    files = normalized["response_evidence"].get("changed_files", [])
    if isinstance(files, list):
        return [str(f).strip() for f in files if str(f).strip()]
    return []


def _provider_trace_findings_from_evidence(item: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_findings = [
        finding
        for finding in _artifact_review_findings(item)
        if str(finding.get("check") or "").strip() == "provider_trace"
    ]
    if artifact_findings:
        return artifact_findings
    response_evidence = _normalized_evidence_metadata(item)["response_evidence"]
    review_trace = _provider_review_trace(response_evidence)
    if review_trace is None:
        return []
    return [
        dict(finding, provider=finding.get("provider") or review_trace.get("provider"))
        for finding in review_trace.get("findings", [])
        if isinstance(finding, Mapping)
    ]


def _diff_hunks_from_evidence(item: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_findings = [
        finding
        for finding in _artifact_review_findings(item)
        if str(finding.get("check") or "").strip() == "diff_hunk"
    ]
    if artifact_findings:
        return artifact_findings
    response_evidence = _normalized_evidence_metadata(item)["response_evidence"]
    diff_trace = _provider_diff_trace(response_evidence)
    if diff_trace is None:
        return []
    return [
        dict(hunk, provider=hunk.get("provider") or diff_trace.get("provider"))
        for hunk in diff_trace.get("hunks", [])
        if isinstance(hunk, Mapping)
    ]


def _spec_references_from_evidence(item: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_findings = [
        finding
        for finding in _artifact_review_findings(item)
        if str(finding.get("check") or "").strip() == "spec_reference"
    ]
    if artifact_findings:
        return artifact_findings
    response_evidence = _normalized_evidence_metadata(item)["response_evidence"]
    spec_trace = _provider_spec_trace(response_evidence)
    if spec_trace is None:
        return []
    return [
        dict(reference, provider=reference.get("provider") or spec_trace.get("provider"))
        for reference in spec_trace.get("references", [])
        if isinstance(reference, Mapping)
    ]


def _provider_review_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("review_trace")
    return _provider_trace_payload(value, list_key="findings")


def _provider_diff_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("diff_trace")
    return _provider_trace_payload(value, list_key="hunks")


def _provider_spec_trace(response_evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = response_evidence.get("spec_trace")
    return _provider_trace_payload(value, list_key="references")


def _provider_trace_payload(
    value: Any,
    *,
    list_key: str,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    payload_items = value.get(list_key, [])
    if not isinstance(payload_items, list):
        payload_items = []
    provider = value.get("provider")
    summary = value.get("summary")
    return {
        "provider": provider if isinstance(provider, str) else None,
        "summary": summary if isinstance(summary, str) else None,
        list_key: payload_items,
    }


def _matching_spec_reference_ids(
    references: list[dict[str, Any]],
    ac_id: str,
    criterion: str,
) -> list[str]:
    normalized_criterion = _normalize_requirement_text(criterion)
    evidence_ids: list[str] = []
    for reference in references:
        ref_ac_id = reference.get("ac_id")
        ref_criterion = reference.get("criterion")
        matches_ac_id = isinstance(ref_ac_id, str) and ref_ac_id.strip() == ac_id
        matches_criterion = (
            isinstance(ref_criterion, str)
            and _normalize_requirement_text(ref_criterion) == normalized_criterion
        )
        if matches_ac_id or matches_criterion:
            evidence_id = reference.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id.strip():
                evidence_ids.append(evidence_id)
    return _unique_ordered(evidence_ids)


def _normalize_requirement_text(value: str) -> str:
    return " ".join(value.lower().split())


def _average_confidence(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _cluster_diff_regions(hunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for hunk in hunks:
        file_path = hunk.get("file_path")
        category = hunk.get("category")
        line_start = hunk.get("line_start")
        line_end = hunk.get("line_end")
        if not isinstance(file_path, str) or not file_path.strip():
            continue
        if not isinstance(category, str) or not category.strip():
            continue
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            continue
        grouped.setdefault((file_path.strip(), category.strip()), []).append(hunk)

    regions: list[dict[str, Any]] = []
    for (file_path, category), items in grouped.items():
        sorted_items = sorted(items, key=lambda item: (int(item["line_start"]), int(item["line_end"])))
        clusters: list[list[dict[str, Any]]] = []
        current_cluster: list[dict[str, Any]] = []
        current_end = -1
        for item in sorted_items:
            item_start = int(item["line_start"])
            item_end = int(item["line_end"])
            if not current_cluster or item_start <= current_end + 1:
                current_cluster.append(item)
                current_end = max(current_end, item_end)
            else:
                clusters.append(current_cluster)
                current_cluster = [item]
                current_end = item_end
        if current_cluster:
            clusters.append(current_cluster)

        for cluster in clusters:
            severities = [str(item.get("severity") or "info") for item in cluster]
            confidences = [
                float(item["confidence"])
                for item in cluster
                if isinstance(item.get("confidence"), (int, float))
            ]
            regions.append(
                {
                    "file_path": file_path,
                    "category": category,
                    "line_start": min(int(item["line_start"]) for item in cluster),
                    "line_end": max(int(item["line_end"]) for item in cluster),
                    "hunk_count": len(cluster),
                    "highest_severity": _max_severity(severities),
                    "max_confidence": round(max(confidences), 2) if confidences else None,
                }
            )
    return sorted(regions, key=lambda item: (str(item["file_path"]), str(item["category"]), int(item["line_start"])))


def _max_severity(severities: list[str]) -> str:
    order = {"info": 0, "minor": 1, "major": 2, "critical": 3}
    return max(severities, key=lambda severity: order.get(str(severity), 0), default="info")


def _review_confidence_summary(
    *,
    provider_diff_blockers: int,
    provider_diff_confidence: float | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if provider_diff_blockers > 0:
        reasons.append(f"{provider_diff_blockers} blocking diff hunk(s) remain.")
    if provider_diff_confidence is not None and provider_diff_confidence < 0.75:
        reasons.append(f"Provider diff confidence average is {provider_diff_confidence}.")

    if provider_diff_blockers > 0:
        verdict = "low"
    elif provider_diff_confidence is None:
        verdict = "unknown"
    elif provider_diff_confidence >= 0.85:
        verdict = "high"
    elif provider_diff_confidence >= 0.75:
        verdict = "medium"
    else:
        verdict = "low"

    return {"verdict": verdict, "reasons": reasons}


def _missing_evidence_findings(
    missing_evidence: list[str],
    evidence_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    del evidence_by_id
    return [
        {
            "id": f"finding-{index + 1:02d}",
            "check": "missing_evidence",
            "status": "fail",
            "severity": "major",
            "message": "Review blocked because no dispatch evidence is attached to this subtask.",
            "file_path": None,
            "line_start": None,
            "line_end": None,
            "subtask_id": subtask_id,
            "evidence_id": None,
        }
        for index, subtask_id in enumerate(missing_evidence)
    ]


def _coverage_gap_ids(ac_coverage: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("id"))
        for item in ac_coverage
        if item.get("covered") is False and isinstance(item.get("id"), str)
    ]


def _coverage_gap_findings(ac_coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    index = 1
    for item in ac_coverage:
        if item.get("covered") is not False:
            continue
        ac_id = str(item.get("id") or "").strip() or None
        criterion = str(item.get("criterion") or "").strip() or None
        findings.append(
            {
                "id": f"coverage-gap-{index:02d}",
                "check": "acceptance_coverage",
                "status": "fail",
                "severity": "major",
                "message": "No provider-backed evidence mapped this acceptance criterion.",
                "file_path": None,
                "line_start": None,
                "line_end": None,
                "criterion": criterion,
                "ac_id": ac_id,
                "subtask_id": None,
                "evidence_id": None,
                "provider": None,
            }
        )
        index += 1
    return findings


def _blocking_review_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked_statuses = {"fail", "blocked", "rejected"}
    return [
        finding
        for finding in findings
        if str(finding.get("status") or "").strip().lower() in blocked_statuses
    ]


def _review_requeue_subtask_ids(
    *,
    review_units: list[dict[str, Any]],
    blocking_findings: list[dict[str, Any]],
    coverage_gaps: list[str],
) -> set[str]:
    subtask_ids = {
        str(finding.get("subtask_id"))
        for finding in blocking_findings
        if isinstance(finding.get("subtask_id"), str) and str(finding.get("subtask_id")).strip()
    }
    review_unit_ids = {subtask["id"] for subtask in review_units}
    matched = {subtask_id for subtask_id in subtask_ids if subtask_id in review_unit_ids}
    if matched:
        return matched
    if coverage_gaps:
        return review_unit_ids
    return matched
