"""Normalized agent-output and artifact-index helpers."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .context import AgentOutputContract
from .contracts import DispatchResponse


def build_artifact_index(response: DispatchResponse) -> dict[str, Any]:
    """Extract retrieval-friendly artifacts from provider outputs and evidence."""
    outputs = response.outputs if isinstance(response.outputs, Mapping) else {}
    evidence = response.evidence if isinstance(response.evidence, Mapping) else {}
    artifacts = response.artifacts if isinstance(response.artifacts, Mapping) else {}

    return {
        "files_changed": _unique_strings(
            _collect_string_values(
                outputs.get("files_changed"),
                evidence.get("changed_files"),
                _mapping_value(outputs.get("work_unit_result"), "files_changed"),
            )
        ),
        "tests_run": _unique_strings(
            _collect_string_values(
                outputs.get("tests_run"),
                outputs.get("tests_added"),
                outputs.get("test_results"),
                evidence.get("tests_ran"),
                _mapping_value(outputs.get("work_unit_result"), "tests_run"),
            )
        ),
        "known_risks": _unique_strings(
            _collect_string_values(
                outputs.get("known_risks"),
                outputs.get("risks"),
                _mapping_value(outputs.get("implementation_plan"), "dependencies"),
                evidence.get("known_risks"),
                artifacts.get("known_risks"),
            )
        ),
        "review_findings": _collect_review_findings(
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
        ),
    }


def normalize_agent_output(
    response: DispatchResponse,
    *,
    phase: str,
    purpose: str | None = None,
) -> AgentOutputContract:
    """Build a compact, provider-agnostic agent output contract."""
    outputs = response.outputs if isinstance(response.outputs, Mapping) else {}
    artifact_index = build_artifact_index(response)
    status = _status_for(response=response, outputs=outputs)
    summary = _summary_for(response=response, outputs=outputs, phase=phase)

    artifact_labels: list[str] = []
    if artifact_index["files_changed"]:
        artifact_labels.append(f"files_changed:{len(artifact_index['files_changed'])}")
    if artifact_index["tests_run"]:
        artifact_labels.append(f"tests_run:{len(artifact_index['tests_run'])}")
    if artifact_index["review_findings"]:
        artifact_labels.append(f"review_findings:{len(artifact_index['review_findings'])}")
    if artifact_index["known_risks"]:
        artifact_labels.append(f"known_risks:{len(artifact_index['known_risks'])}")

    decisions = _decision_trace(outputs=outputs, response=response)
    findings = _finding_messages(artifact_index)
    next_recommended_agent = _next_recommended_agent(
        outputs=outputs,
        response=response,
        purpose=purpose,
    )

    return AgentOutputContract(
        status=status,
        summary=summary,
        artifacts=artifact_labels,
        decisions=decisions,
        findings=findings,
        next_recommended_agent=next_recommended_agent,
    )


def _status_for(*, response: DispatchResponse, outputs: Mapping[str, Any]) -> str:
    work_unit_result = outputs.get("work_unit_result")
    if isinstance(work_unit_result, Mapping):
        value = work_unit_result.get("status")
        if isinstance(value, str) and value.strip():
            return value.strip()
    verdict = outputs.get("verdict")
    if isinstance(verdict, str) and verdict.strip():
        return verdict.strip()
    return "completed" if response.success else "failed"


def _summary_for(*, response: DispatchResponse, outputs: Mapping[str, Any], phase: str) -> str:
    summary = outputs.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    work_unit_result = outputs.get("work_unit_result")
    if isinstance(work_unit_result, Mapping):
        value = work_unit_result.get("summary")
        if isinstance(value, str) and value.strip():
            return value.strip()
    messages = outputs.get("messages")
    if isinstance(messages, list):
        rendered = [str(item).strip() for item in messages if str(item).strip()]
        if rendered:
            return rendered[0]
    if response.error:
        return response.error
    return f"{phase} dispatch completed" if response.success else f"{phase} dispatch failed"


def _decision_trace(*, outputs: Mapping[str, Any], response: DispatchResponse) -> list[str]:
    decisions: list[str] = []
    verdict = outputs.get("verdict")
    if isinstance(verdict, str) and verdict.strip():
        decisions.append(f"verdict:{verdict.strip()}")
    work_unit_result = outputs.get("work_unit_result")
    if isinstance(work_unit_result, Mapping):
        provider = work_unit_result.get("provider")
        if isinstance(provider, str) and provider.strip():
            decisions.append(f"provider:{provider.strip()}")
    implementation_plan = outputs.get("implementation_plan")
    if isinstance(implementation_plan, Mapping):
        approach = implementation_plan.get("approach")
        if isinstance(approach, str) and approach.strip():
            decisions.append(f"approach:{approach.strip()}")
    model = response.artifacts.get("model") if isinstance(response.artifacts, Mapping) else None
    if isinstance(model, str) and model.strip():
        decisions.append(f"model:{model.strip()}")
    return decisions[:6]


def _finding_messages(artifact_index: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    for finding in artifact_index.get("review_findings", []):
        if isinstance(finding, Mapping):
            message = finding.get("message")
            if isinstance(message, str) and message.strip():
                findings.append(message.strip())
    for risk in artifact_index.get("known_risks", []):
        if isinstance(risk, str) and risk.strip():
            findings.append(risk.strip())
    return _unique_strings(findings)[:6]


def _next_recommended_agent(
    *,
    outputs: Mapping[str, Any],
    response: DispatchResponse,
    purpose: str | None,
) -> str | None:
    explicit = outputs.get("next_recommended_agent")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if purpose == "child_task_execution" and response.success:
        return "Nirnaya"
    return None


def _collect_review_findings(
    *,
    outputs: Mapping[str, Any],
    evidence: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    findings.extend(_normalize_findings(outputs.get("findings"), source="outputs.findings"))
    findings.extend(_normalize_findings(outputs.get("review_findings"), source="outputs.review_findings"))
    findings.extend(
        _normalize_trace_items(evidence.get("review_trace"), list_key="findings", source="evidence.review_trace")
    )
    findings.extend(
        _normalize_trace_items(artifacts.get("review_trace"), list_key="findings", source="artifacts.review_trace")
    )
    findings.extend(
        _normalize_trace_items(evidence.get("diff_trace"), list_key="hunks", source="evidence.diff_trace")
    )
    findings.extend(
        _normalize_trace_items(artifacts.get("diff_trace"), list_key="hunks", source="artifacts.diff_trace")
    )
    findings.extend(
        _normalize_trace_items(evidence.get("spec_trace"), list_key="references", source="evidence.spec_trace")
    )
    findings.extend(
        _normalize_trace_items(artifacts.get("spec_trace"), list_key="references", source="artifacts.spec_trace")
    )
    return _dedupe_findings(findings)


def _normalize_trace_items(value: Any, *, list_key: str, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    default_provider = str(value.get("provider")).strip() if value.get("provider") else None
    return _normalize_findings(value.get(list_key), source=source, default_provider=default_provider)


def _normalize_findings(value: Any, *, source: str, default_provider: str | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(value, str) and value.strip():
        return [{"message": value.strip(), "source": source}]
    if not isinstance(value, list):
        return normalized
    for item in value:
        if isinstance(item, Mapping):
            message = item.get("message") or item.get("summary") or item.get("finding")
            if isinstance(message, str) and message.strip():
                normalized.append(
                    {
                        "message": message.strip(),
                        "status": str(item.get("status")).strip() if item.get("status") else None,
                        "severity": str(item.get("severity")).strip() if item.get("severity") else None,
                        "check": str(item.get("check")).strip() if item.get("check") else None,
                        "file_path": str(item.get("file_path")).strip() if item.get("file_path") else None,
                        "provider": (
                            str(item.get("provider")).strip()
                            if item.get("provider")
                            else default_provider
                        ),
                        "line_start": item.get("line_start") if isinstance(item.get("line_start"), int) else None,
                        "line_end": item.get("line_end") if isinstance(item.get("line_end"), int) else None,
                        "header": str(item.get("header")).strip() if item.get("header") else None,
                        "excerpt": str(item.get("excerpt")).strip() if item.get("excerpt") else None,
                        "category": str(item.get("category")).strip() if item.get("category") else None,
                        "suggestion": str(item.get("suggestion")).strip() if item.get("suggestion") else None,
                        "criterion": str(item.get("criterion")).strip() if item.get("criterion") else None,
                        "ac_id": str(item.get("ac_id")).strip() if item.get("ac_id") else None,
                        "confidence": round(float(item.get("confidence")), 2)
                        if isinstance(item.get("confidence"), (int, float))
                        else None,
                        "source": source,
                    }
                )
        elif isinstance(item, str) and item.strip():
            normalized.append({"message": item.strip(), "source": source})
    return normalized


def _dedupe_findings(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str, str, str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for item in findings:
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        key = (
            message,
            str(item.get("status") or "").strip(),
            str(item.get("severity") or "").strip(),
            str(item.get("check") or "").strip(),
            str(item.get("file_path") or "").strip(),
            str(item.get("line_start") or "").strip(),
            str(item.get("line_end") or "").strip(),
            str(item.get("ac_id") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "message": message,
                **({"status": item["status"]} if item.get("status") else {}),
                **({"severity": item["severity"]} if item.get("severity") else {}),
                **({"check": item["check"]} if item.get("check") else {}),
                **({"file_path": item["file_path"]} if item.get("file_path") else {}),
                **({"provider": item["provider"]} if item.get("provider") else {}),
                **({"line_start": item["line_start"]} if item.get("line_start") is not None else {}),
                **({"line_end": item["line_end"]} if item.get("line_end") is not None else {}),
                **({"header": item["header"]} if item.get("header") else {}),
                **({"excerpt": item["excerpt"]} if item.get("excerpt") else {}),
                **({"category": item["category"]} if item.get("category") else {}),
                **({"suggestion": item["suggestion"]} if item.get("suggestion") else {}),
                **({"criterion": item["criterion"]} if item.get("criterion") else {}),
                **({"ac_id": item["ac_id"]} if item.get("ac_id") else {}),
                **({"confidence": item["confidence"]} if item.get("confidence") is not None else {}),
                **({"source": item["source"]} if item.get("source") else {}),
            }
        )
    return normalized


def _mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return None


def _collect_string_values(*values: Any) -> list[str]:
    collected: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            collected.append(value.strip())
        elif isinstance(value, list):
            collected.extend(str(item).strip() for item in value if str(item).strip())
    return collected


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique
