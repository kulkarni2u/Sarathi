import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Pattern:
    name: str
    first_seen: datetime
    validated_in: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    best_seen: str | None = None
    trend: str = "stable"
    evidence_refs: list[str] = field(default_factory=list)
    promotion_date: datetime | None = None


@dataclass
class EvolveBaseline:
    patterns: list[Pattern] = field(default_factory=list)
    total_patterns: int = 0
    promoted_this_month: int = 0
    deprecated_this_month: int = 0


@dataclass
class PolicyProposal:
    title: str
    policy_file: str
    rationale: str
    suggested_change: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "learning"
    routing_hint: dict[str, Any] = field(default_factory=dict)

    @property
    def proposal_id(self) -> str:
        raw = "|".join(
            [
                self.title,
                self.policy_file,
                self.rationale,
                self.suggested_change,
                self.source,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": self.proposal_id,
            "title": self.title,
            "policy_file": self.policy_file,
            "rationale": self.rationale,
            "suggested_change": self.suggested_change,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "source": self.source,
            "routing_hint": self.routing_hint,
        }


class Evolver:
    PASS_GATE = 0.8
    PROPOSAL_GATE = 2

    def detect_pattern(self, baseline: EvolveBaseline, pattern_name: str) -> Pattern | None:
        for pattern in baseline.patterns:
            if pattern.name == pattern_name:
                return pattern
        return None

    def should_promote(self, pattern: Pattern) -> bool:
        return pattern.pass_rate >= self.PASS_GATE

    def apply_evolution(self, baseline: EvolveBaseline, pattern: Pattern) -> EvolveBaseline:
        baseline.patterns.append(pattern)
        baseline.total_patterns = len(baseline.patterns)
        return baseline

    def generate_policy_proposals(
        self,
        learning_records: list[Any] | None = None,
        patterns: list[Pattern] | None = None,
    ) -> list[PolicyProposal]:
        """Generate policy proposals without applying them to policy files."""
        proposals = self.propose_from_learning_records(learning_records or [])
        proposals.extend(self.propose_from_patterns(patterns or []))
        return proposals

    def propose_from_learning_records(self, records: list[Any]) -> list[PolicyProposal]:
        failures: dict[str, dict[str, Any]] = {}
        provider_failures: dict[tuple[str, str], dict[str, Any]] = {}
        escalations: dict[str, dict[str, Any]] = {}
        hotspots: dict[str, dict[str, Any]] = {}

        for record in records:
            task_id = str(self._record_value(record, "task_id", "unknown"))
            self._accumulate_signal(
                failures,
                self._record_value(record, "repeated_failures", []),
                task_id,
                "repeated_failures",
                "count",
            )
            self._accumulate_provider_signal(
                provider_failures,
                self._record_value(record, "provider_failures", []),
                task_id,
            )
            self._accumulate_signal(
                escalations,
                self._record_value(record, "escalations", []),
                task_id,
                "escalations",
                "count",
            )
            self._accumulate_signal(
                hotspots,
                self._record_value(record, "iteration_hotspots", []),
                task_id,
                "iteration_hotspots",
                "iterations",
            )

        proposals: list[PolicyProposal] = []
        proposals.extend(self._proposals_for_repeated_failures(failures))
        proposals.extend(self._proposals_for_provider_failures(provider_failures))
        proposals.extend(self._proposals_for_escalations(escalations))
        proposals.extend(self._proposals_for_iteration_hotspots(hotspots))
        return sorted(proposals, key=lambda proposal: (proposal.policy_file, proposal.title))

    def propose_from_patterns(self, patterns: list[Pattern]) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for pattern in sorted(patterns, key=lambda item: item.name):
            if not self.should_promote(pattern):
                continue
            proposals.append(
                PolicyProposal(
                    title=f"Promote learned pattern: {pattern.name}",
                    policy_file="conventions.md",
                    rationale=(
                        f"Pattern '{pattern.name}' met the promotion gate with "
                        f"{pattern.pass_rate:.0%} pass rate."
                    ),
                    suggested_change=(
                        f"Document '{pattern.name}' as a reusable convention, including "
                        "the evidence needed before applying it by default."
                    ),
                    evidence_refs=list(pattern.evidence_refs),
                    confidence=pattern.pass_rate,
                    source="pattern",
                )
            )
        return proposals

    def _accumulate_signal(
        self,
        bucket: dict[str, dict[str, Any]],
        items: Any,
        task_id: str,
        signal_name: str,
        value_key: str,
    ) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            phase = str(item.get("phase", "unknown"))
            value = self._positive_int(item.get(value_key, 1))
            entry = bucket.setdefault(phase, {"total": 0, "evidence_refs": []})
            entry["total"] += value
            entry["evidence_refs"].append(f"{task_id}:{signal_name}:{phase}")

    def _accumulate_provider_signal(
        self,
        bucket: dict[tuple[str, str], dict[str, Any]],
        items: Any,
        task_id: str,
    ) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            phase = str(item.get("phase", "unknown"))
            provider = str(item.get("provider", "unknown"))
            if not provider:
                continue
            value = self._positive_int(item.get("count", 1))
            entry = bucket.setdefault((phase, provider), {"total": 0, "evidence_refs": []})
            entry["total"] += value
            entry["evidence_refs"].append(f"{task_id}:provider_failures:{phase}:{provider}")

    def _proposals_for_repeated_failures(
        self, failures: dict[str, dict[str, Any]]
    ) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for phase, data in failures.items():
            total = data["total"]
            if total < self.PROPOSAL_GATE:
                continue
            proposals.append(
                PolicyProposal(
                    title=f"Add {phase} failure recovery guidance",
                    policy_file=self._policy_file_for_phase(phase),
                    rationale=f"{phase} recorded {total} repeated failure signal(s).",
                    suggested_change=(
                        f"Add a {phase}-phase recovery checklist that requires root-cause "
                        "capture before retrying the same approach."
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="repeated_failures",
                )
            )
        return proposals

    def _proposals_for_escalations(
        self, escalations: dict[str, dict[str, Any]]
    ) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for phase, data in escalations.items():
            total = data["total"]
            if total < self.PROPOSAL_GATE:
                continue
            proposals.append(
                PolicyProposal(
                    title=f"Tighten {phase} escalation criteria",
                    policy_file="escalation.md",
                    rationale=f"{phase} recorded {total} escalation signal(s).",
                    suggested_change=(
                        f"Clarify when {phase} should reduce scope, request help, "
                        "or stop for user input before another escalation."
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="escalations",
                )
            )
        return proposals

    def _proposals_for_provider_failures(
        self, provider_failures: dict[tuple[str, str], dict[str, Any]]
    ) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for (phase, provider), data in provider_failures.items():
            total = data["total"]
            if total < self.PROPOSAL_GATE or provider.lower() == "local":
                continue
            fallback_provider = "local"
            proposals.append(
                PolicyProposal(
                    title=f"Reroute {phase} away from {provider}",
                    policy_file="model-routing.md",
                    rationale=(
                        f"{provider} recorded {total} failure signal(s) during {phase}, "
                        "suggesting the default route should prefer a safer fallback."
                    ),
                    suggested_change=(
                        f"Prefer {fallback_provider} for {phase} when no explicit provider is requested, "
                        f"and avoid defaulting to {provider} for that phase until the failure pattern is resolved."
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="provider_failures",
                    routing_hint={
                        "phase": phase,
                        "preferred_provider": fallback_provider,
                        "deprioritize_provider": provider,
                    },
                )
            )
        return proposals

    def _proposals_for_iteration_hotspots(
        self, hotspots: dict[str, dict[str, Any]]
    ) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for phase, data in hotspots.items():
            total = data["total"]
            if total < self.PROPOSAL_GATE:
                continue
            proposals.append(
                PolicyProposal(
                    title=f"Reduce {phase} iteration hotspot",
                    policy_file=self._policy_file_for_phase(phase),
                    rationale=f"{phase} accumulated {total} iteration hotspot signal(s).",
                    suggested_change=(
                        f"Add a reusable {phase} optimization or pre-check to reduce "
                        "avoidable iteration loops."
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="iteration_hotspots",
                )
            )
        return proposals

    def _policy_file_for_phase(self, phase: str) -> str:
        normalized = phase.lower()
        if normalized in {"verify", "build"}:
            return "commands.md"
        if normalized in {"review", "riskcheck"}:
            return "review.md"
        if normalized in {"tasktracking", "plan", "brainstorm", "planningadvisor"}:
            return "task-tracking.md"
        return "conventions.md"

    def _record_value(self, record: Any, key: str, default: Any) -> Any:
        if isinstance(record, dict):
            return record.get(key, default)
        return getattr(record, key, default)

    def _positive_int(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 1
        return max(number, 1)

    def _confidence(self, signal_count: int) -> float:
        return min(1.0, 0.5 + (signal_count * 0.1))


class ProposalReviewStore:
    """Human review/apply workflow for generated policy proposals."""

    def __init__(self, policy_pack_path: str | Path):
        self.policy_pack_path = Path(policy_pack_path)
        self.review_dir = self.policy_pack_path / ".sarathi-proposals"
        self.review_dir.mkdir(parents=True, exist_ok=True)

    def accept(self, proposal: PolicyProposal) -> dict[str, Any]:
        policy_file = self.policy_pack_path / proposal.policy_file
        if not policy_file.exists():
            raise FileNotFoundError(f"Policy file not found: {policy_file}")
        marker = f"proposal-id: {proposal.proposal_id}"
        current = policy_file.read_text()
        if marker not in current:
            policy_file.write_text(self._apply_to_policy_text(current, proposal))
        decision = self._decision("accepted", proposal)
        self._write_decision(decision)
        return decision

    def reject(self, proposal: PolicyProposal, reason: str | None = None) -> dict[str, Any]:
        decision = self._decision("rejected", proposal, reason=reason)
        self._write_decision(decision)
        return decision

    def _accepted_section(self, proposal: PolicyProposal) -> str:
        evidence = "\n".join(f"- {ref}" for ref in proposal.evidence_refs) or "- none"
        return "\n".join(
            [
                "## Accepted Sarathi Proposal",
                "",
                f"<!-- proposal-id: {proposal.proposal_id} -->",
                f"Title: {proposal.title}",
                f"Source: {proposal.source}",
                f"Confidence: {proposal.confidence:.2f}",
                "",
                "Rationale:",
                proposal.rationale,
                "",
                "Suggested change:",
                proposal.suggested_change,
                "",
                "Evidence:",
                evidence,
            ]
        )

    def _apply_to_policy_text(self, current: str, proposal: PolicyProposal) -> str:
        yaml_match = re.search(r"```yaml\s*(.*?)\s*```", current, re.DOTALL)
        if not yaml_match:
            return current.rstrip() + "\n\n" + self._accepted_section(proposal) + "\n"

        try:
            parsed = yaml.safe_load(yaml_match.group(1)) or {}
        except yaml.YAMLError:
            return current.rstrip() + "\n\n" + self._accepted_section(proposal) + "\n"
        if not isinstance(parsed, dict):
            return current.rstrip() + "\n\n" + self._accepted_section(proposal) + "\n"

        accepted = parsed.setdefault("accepted_proposals", [])
        if not isinstance(accepted, list):
            accepted = []
            parsed["accepted_proposals"] = accepted
        accepted.append(
            {
                "id": proposal.proposal_id,
                "title": proposal.title,
                "source": proposal.source,
                "confidence": proposal.confidence,
                "suggested_change": proposal.suggested_change,
                "evidence_refs": proposal.evidence_refs,
                "routing_hint": proposal.routing_hint,
            }
        )
        replacement = "```yaml\n" + yaml.safe_dump(parsed, sort_keys=False).rstrip() + "\n```"
        return current[: yaml_match.start()] + replacement + current[yaml_match.end():]

    def _decision(
        self,
        status: str,
        proposal: PolicyProposal,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": proposal.proposal_id,
            "status": status,
            "policy_file": proposal.policy_file,
            "title": proposal.title,
            "source": proposal.source,
            "routing_hint": proposal.routing_hint,
            "reason": reason,
            "reviewed_at": datetime.utcnow().isoformat() + "Z",
        }

    def _write_decision(self, decision: dict[str, Any]) -> None:
        import json

        path = self.review_dir / f"{decision['id']}.json"
        path.write_text(json.dumps(decision, indent=2))
