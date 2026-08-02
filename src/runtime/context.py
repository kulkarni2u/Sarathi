"""Context-pack contracts and compiler helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from math import ceil
import re
from typing import Any, Iterable, Mapping

from src.repo_index import format_symbol_hint, query_repo_index
from src.storage import SLACK_EXTERNAL_INPUT_SOURCE, SLACK_EXTERNAL_INPUT_TRUST

MAX_EXTERNAL_INPUTS = 5
_SLACK_VALIDATION_VERSION = "slack-input-v1"
_SLACK_INPUT_MAX_LENGTH = 4000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _estimate_tokens(payload: Any) -> int:
    try:
        serialized = json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        serialized = str(payload)
    return max(1, ceil(len(serialized) / 4))


@dataclass(frozen=True)
class AgentInputContract:
    """Compact, role-specific input contract for one agent dispatch."""

    objective: str
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    prior_findings: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    external_inputs: list[dict[str, Any]] = field(default_factory=list)
    token_budget: int = 3000

    def to_artifact(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "relevant_files": list(self.relevant_files),
            "prior_findings": list(self.prior_findings),
            "available_tools": list(self.available_tools),
            "external_inputs": [dict(item) for item in self.external_inputs],
            "token_budget": self.token_budget,
        }


@dataclass(frozen=True)
class AgentOutputContract:
    """Normalized output contract target for agent responses."""

    status: str
    summary: str
    artifacts: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    next_recommended_agent: str | None = None

    def to_artifact(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "decisions": list(self.decisions),
            "findings": list(self.findings),
            "next_recommended_agent": self.next_recommended_agent,
        }


@dataclass(frozen=True)
class ContextPack:
    """Compiled context bundle passed to an agent instead of raw history."""

    role: str
    phase: str
    summary: str
    agent_input: AgentInputContract
    source_artifacts: list[dict[str, Any]] = field(default_factory=list)
    compilation: dict[str, Any] = field(default_factory=dict)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "phase": self.phase,
            "summary": self.summary,
            "agent_input": self.agent_input.to_artifact(),
            "source_artifacts": list(self.source_artifacts),
            "compilation": dict(self.compilation),
        }


class ContextCompiler:
    """Build compact, role-specific context packs from persisted task truth."""

    DEFAULT_TOKEN_BUDGETS: dict[str, int] = {
        "Disha": 2400,
        "Pravaha": 3200,
        "Nirnaya": 2800,
        "Samanvaya": 2200,
        "Sarathi": 2600,
    }

    def compile_task_tracking_context(
        self,
        *,
        task: Mapping[str, Any],
        subtask: Mapping[str, Any],
        evidence_artifacts: Iterable[Mapping[str, Any]] = (),
        review_runs: Iterable[Mapping[str, Any]] = (),
        external_inputs: Iterable[Mapping[str, Any]] = (),
        available_tools: Iterable[str] = (),
        token_budget: int | None = None,
        repo_index_root: str | None = None,
    ) -> ContextPack:
        raw_metadata = subtask.get("metadata")
        metadata: Mapping[str, Any] = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        task_metadata = task.get("metadata") if isinstance(task.get("metadata"), Mapping) else {}
        task_packet = metadata.get("task_packet") if isinstance(metadata.get("task_packet"), Mapping) else {}
        role = str(metadata.get("role") or "Sarathi")
        resolved_budget = int(token_budget or self.DEFAULT_TOKEN_BUDGETS.get(role, 2600))

        objective = str(task_packet.get("goal") or subtask.get("title") or task.get("title") or "Complete the assigned work").strip()
        summary = (
            f"Task '{task.get('title') or task.get('id')}' -> "
            f"subtask '{subtask.get('title') or subtask.get('id')}' for role {role}."
        )

        constraints = self._constraints_for(task=task, subtask=subtask)
        acceptance_criteria = self._acceptance_criteria_for(task_metadata=task_metadata, task_packet=task_packet)
        relevant_files = self._relevant_files_for(task_metadata=task_metadata, evidence_artifacts=evidence_artifacts)
        relevant_files = self._with_repo_index_hints(
            objective=objective, relevant_files=relevant_files, repo_index_root=repo_index_root
        )
        prior_findings = self._prior_findings_for(review_runs=review_runs)
        source_artifacts = self._source_artifacts_for(evidence_artifacts=evidence_artifacts, review_runs=review_runs)
        typed_external_inputs = self._external_inputs_for(
            external_inputs=external_inputs, subtask_id=str(subtask.get("id") or "")
        )

        contract = AgentInputContract(
            objective=objective,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            relevant_files=relevant_files,
            prior_findings=prior_findings,
            available_tools=[str(item) for item in available_tools if str(item).strip()],
            external_inputs=typed_external_inputs,
            token_budget=resolved_budget,
        )
        trimmed_sections: list[str] = []
        summary, contract, trimmed_sections, estimated_tokens = self._fit_to_budget(
            summary=summary,
            contract=contract,
            budget=resolved_budget,
        )

        return ContextPack(
            role=role,
            phase="TaskTracking",
            summary=summary,
            agent_input=contract,
            source_artifacts=source_artifacts,
            compilation={
                "estimated_tokens": estimated_tokens,
                "token_budget": resolved_budget,
                "full_history_excluded": True,
                "trimmed_sections": trimmed_sections,
            },
        )

    def compile_graph_node_context(
        self,
        *,
        node: Mapping[str, Any],
        graph: Mapping[str, Any] | None = None,
        phase: str = "Build",
        available_tools: Iterable[str] = (),
        token_budget: int | None = None,
        repo_index_root: str | None = None,
    ) -> ContextPack:
        role = str(node.get("role") or "Pravaha")
        resolved_budget = int(token_budget or self.DEFAULT_TOKEN_BUDGETS.get(role, 2600))
        blockers = node.get("needs_from") if isinstance(node.get("needs_from"), list) else node.get("depends_on", [])
        child_ids = node.get("child_task_ids") if isinstance(node.get("child_task_ids"), list) else []
        summary = (
            f"Graph node '{node.get('title') or node.get('id')}' in phase {phase}"
            f" with {len(blockers or [])} dependency hint(s)."
        )
        constraints = [
            f"Node status: {node.get('status', 'pending')}",
            f"Progress state: {node.get('progress_state', 'unknown')}",
        ]
        if blockers:
            constraints.append("Needs from: " + ", ".join(str(item) for item in blockers))
        if child_ids:
            constraints.append("Downstream children: " + ", ".join(str(item) for item in child_ids))
        constraints.append("Use the compiled context pack instead of reconstructing execution history.")

        packet = node.get("task_packet") if isinstance(node.get("task_packet"), Mapping) else {}
        acceptance_criteria = []
        review_criteria = packet.get("review_criteria")
        if isinstance(review_criteria, list):
            acceptance_criteria = [str(item) for item in review_criteria if str(item).strip()]
        relevant_files = []
        raw_files = node.get("relevant_files")
        if isinstance(raw_files, list):
            relevant_files = [str(item) for item in raw_files if str(item).strip()]
        objective_text = str(packet.get("goal") or node.get("title") or node.get("id") or "")
        relevant_files = self._with_repo_index_hints(
            objective=objective_text, relevant_files=relevant_files, repo_index_root=repo_index_root
        )

        prior_findings: list[str] = []
        if isinstance(graph, Mapping):
            for graph_node in graph.get("nodes", []):
                if not isinstance(graph_node, Mapping) or graph_node.get("id") == node.get("id"):
                    continue
                if graph_node.get("status") == "failed" and isinstance(graph_node.get("last_error"), str):
                    prior_findings.append(str(graph_node["last_error"]))

        contract = AgentInputContract(
            objective=str(packet.get("goal") or node.get("title") or node.get("id") or "Complete graph node").strip(),
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            relevant_files=relevant_files,
            prior_findings=prior_findings[:6],
            available_tools=[str(item) for item in available_tools if str(item).strip()],
            token_budget=resolved_budget,
        )
        summary, contract, trimmed_sections, estimated_tokens = self._fit_to_budget(
            summary=summary,
            contract=contract,
            budget=resolved_budget,
        )
        return ContextPack(
            role=role,
            phase=phase,
            summary=summary,
            agent_input=contract,
            source_artifacts=[],
            compilation={
                "estimated_tokens": estimated_tokens,
                "token_budget": resolved_budget,
                "full_history_excluded": True,
                "trimmed_sections": trimmed_sections,
            },
        )

    def _with_repo_index_hints(
        self,
        *,
        objective: str,
        relevant_files: list[str],
        repo_index_root: str | None,
        limit: int = 5,
    ) -> list[str]:
        """Append ranked "file:line symbol (kind)" hints from the repo index.

        Lets a dispatched agent jump straight to likely-relevant code instead
        of re-discovering it with Glob/Grep every phase. Best-effort: an
        unindexed workspace or a query with no matches leaves relevant_files
        untouched, and any lookup failure is swallowed since this is an
        enrichment, not a required input.
        """
        if not repo_index_root or not objective.strip():
            return relevant_files
        try:
            matches = query_repo_index(repo_index_root, objective, limit=limit)
        except Exception:
            return relevant_files
        hints = [format_symbol_hint(entry) for entry in matches]
        merged = list(relevant_files)
        for hint in hints:
            if hint not in merged:
                merged.append(hint)
        return merged

    def _constraints_for(self, *, task: Mapping[str, Any], subtask: Mapping[str, Any]) -> list[str]:
        metadata = subtask.get("metadata") if isinstance(subtask.get("metadata"), Mapping) else {}
        evidence_required = metadata.get("evidence_required") if isinstance(metadata.get("evidence_required"), list) else []
        blocked_by = metadata.get("blocked_by") if isinstance(metadata.get("blocked_by"), list) else []
        constraints = [
            f"Task status: {task.get('status', 'unknown')}",
            f"Subtask status: {subtask.get('status', 'unknown')}",
            f"Provider lane: {metadata.get('provider', 'unspecified')}",
        ]
        if evidence_required:
            constraints.append("Required evidence: " + ", ".join(str(item) for item in evidence_required))
        if blocked_by:
            constraints.append("Depends on completed blockers: " + ", ".join(str(item) for item in blocked_by))
        constraints.append("Do not request full chat history unless the context pack is insufficient.")
        return constraints

    def _acceptance_criteria_for(
        self,
        *,
        task_metadata: Mapping[str, Any],
        task_packet: Mapping[str, Any],
    ) -> list[str]:
        criteria = task_packet.get("review_criteria")
        if isinstance(criteria, list) and criteria:
            return [str(item) for item in criteria if str(item).strip()]
        task_criteria = task_metadata.get("acceptance_criteria")
        if isinstance(task_criteria, list):
            return [str(item) for item in task_criteria if str(item).strip()]
        return []

    def _relevant_files_for(
        self,
        *,
        task_metadata: Mapping[str, Any],
        evidence_artifacts: Iterable[Mapping[str, Any]],
    ) -> list[str]:
        values: list[str] = []
        raw_files = task_metadata.get("relevant_files")
        if isinstance(raw_files, list):
            values.extend(str(item) for item in raw_files if str(item).strip())
        repository = task_metadata.get("repository")
        if isinstance(repository, Mapping):
            for key in ("path", "root_path"):
                value = repository.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
        for artifact in evidence_artifacts:
            metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), Mapping) else {}
            artifact_index = metadata.get("artifact_index") if isinstance(metadata.get("artifact_index"), Mapping) else {}
            changed_files = artifact_index.get("files_changed")
            if not isinstance(changed_files, list):
                response_evidence = metadata.get("response_evidence") if isinstance(metadata.get("response_evidence"), Mapping) else {}
                changed_files = response_evidence.get("changed_files")
            if isinstance(changed_files, list):
                values.extend(str(item) for item in changed_files if str(item).strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    def _prior_findings_for(self, *, review_runs: Iterable[Mapping[str, Any]]) -> list[str]:
        findings: list[str] = []
        for review in review_runs:
            summary = review.get("summary")
            if isinstance(summary, str) and summary.strip():
                findings.append(summary.strip())
            metadata = review.get("metadata") if isinstance(review.get("metadata"), Mapping) else {}
            raw_findings = metadata.get("findings")
            if isinstance(raw_findings, list):
                for item in raw_findings:
                    if isinstance(item, Mapping):
                        message = item.get("message")
                        if isinstance(message, str) and message.strip():
                            findings.append(message.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for finding in findings:
            if finding not in seen:
                seen.add(finding)
                deduped.append(finding)
        return deduped[:8]

    def _external_inputs_for(
        self,
        *,
        external_inputs: Iterable[Mapping[str, Any]],
        subtask_id: str,
    ) -> list[dict[str, Any]]:
        """Return canonical assigned external-input projections only.

        Only entries written by the storage assign+resume transaction (carrying
        the canonical source, trust, validation version, and envelope id) are
        trusted as typed external data. Everything else is ignored so arbitrary
        subtask metadata can never be promoted into the agent context.
        """
        items: list[dict[str, Any]] = []
        for item in external_inputs:
            if not isinstance(item, Mapping):
                continue
            if item.get("source") != SLACK_EXTERNAL_INPUT_SOURCE:
                continue
            if item.get("trust") != SLACK_EXTERNAL_INPUT_TRUST:
                continue
            if item.get("status") != "assigned" or item.get("subtask_id") != subtask_id:
                continue
            envelope_id = item.get("envelope_id")
            validation_version = item.get("validation_version")
            text = item.get("text")
            if not isinstance(envelope_id, str) or not envelope_id:
                continue
            if validation_version != _SLACK_VALIDATION_VERSION:
                continue
            if not isinstance(text, str) or not text or len(text) > _SLACK_INPUT_MAX_LENGTH:
                continue
            digest = item.get("digest")
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                continue
            items.append(
                {
                    "source": SLACK_EXTERNAL_INPUT_SOURCE,
                    "trust": SLACK_EXTERNAL_INPUT_TRUST,
                    "text": text,
                    "validation_version": validation_version,
                    "digest": digest,
                    "envelope_id": envelope_id,
                    "actor_id": str(item.get("actor_id") or ""),
                    "channel_id": str(item.get("channel_id") or ""),
                }
            )
        return items

    def _source_artifacts_for(
        self,
        *,
        evidence_artifacts: Iterable[Mapping[str, Any]],
        review_runs: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for artifact in evidence_artifacts:
            refs.append(
                {
                    "kind": str(artifact.get("artifact_type") or "evidence"),
                    "uri": str(artifact.get("uri") or ""),
                    "id": str(artifact.get("id") or ""),
                }
            )
        for review in review_runs:
            refs.append(
                {
                    "kind": "review_run",
                    "uri": f"sarathi://reviews/{review.get('id')}",
                    "id": str(review.get("id") or ""),
                }
            )
        return refs[:12]

    def _fit_to_budget(
        self,
        *,
        summary: str,
        contract: AgentInputContract,
        budget: int,
    ) -> tuple[str, AgentInputContract, list[str], int]:
        trimmed_sections: list[str] = []
        summary_text = summary
        working = contract

        while True:
            # External inputs carry a hard ceiling (MAX_EXTERNAL_INPUTS) that
            # applies before any budget accounting: even a generous token
            # budget must never let more than the cap through the early
            # return, so human text can never displace instructions.
            if len(working.external_inputs) > MAX_EXTERNAL_INPUTS:
                trimmed_sections.append("external_inputs")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs[:MAX_EXTERNAL_INPUTS]),
                    token_budget=working.token_budget,
                )
                continue
            payload = {
                "summary": summary_text,
                "agent_input": working.to_artifact(),
            }
            estimated = _estimate_tokens(payload)
            if estimated <= budget:
                return summary_text, working, trimmed_sections, estimated

            # Under budget pressure, external inputs are the lowest-priority
            # section: shed the oldest entries one at a time before any other
            # section is trimmed.
            if working.external_inputs:
                trimmed_sections.append("external_inputs")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs[:-1]),
                    token_budget=working.token_budget,
                )
                continue
            if working.prior_findings:
                trimmed_sections.append("prior_findings")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings[:-1]),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(working.relevant_files) > 4:
                trimmed_sections.append("relevant_files")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files[:4]),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if working.relevant_files:
                trimmed_sections.append("relevant_files")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=[],
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(working.acceptance_criteria) > 4:
                trimmed_sections.append("acceptance_criteria")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria[:4]),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if working.acceptance_criteria:
                trimmed_sections.append("acceptance_criteria")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=[],
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(summary_text) > 180:
                trimmed_sections.append("summary")
                summary_text = summary_text[:177].rstrip() + "..."
                continue
            if len(working.constraints) > 4:
                trimmed_sections.append("constraints")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints[:4]),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(summary_text) > 96:
                trimmed_sections.append("summary")
                summary_text = summary_text[:93].rstrip() + "..."
                continue
            if len(summary_text) > 48:
                trimmed_sections.append("summary")
                summary_text = summary_text[:45].rstrip() + "..."
                continue
            if len(working.available_tools) > 2:
                trimmed_sections.append("available_tools")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools[:2]),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if working.available_tools:
                trimmed_sections.append("available_tools")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=[],
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(working.constraints) > 2:
                trimmed_sections.append("constraints")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=list(working.constraints[:2]),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if working.constraints:
                trimmed_sections.append("constraints")
                working = AgentInputContract(
                    objective=working.objective,
                    constraints=[],
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            if len(working.objective) > 64:
                trimmed_sections.append("objective")
                working = AgentInputContract(
                    objective=working.objective[:61].rstrip() + "...",
                    constraints=list(working.constraints),
                    acceptance_criteria=list(working.acceptance_criteria),
                    relevant_files=list(working.relevant_files),
                    prior_findings=list(working.prior_findings),
                    available_tools=list(working.available_tools),
                    external_inputs=list(working.external_inputs),
                    token_budget=working.token_budget,
                )
                continue
            return summary_text, working, trimmed_sections, estimated
