import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from .proposal_sync import ProposalSync
except ImportError:
    from proposal_sync import ProposalSync

logger = logging.getLogger("sarathi.evolve")

# Provenance weighting applied to quality-signal deltas before they can
# trigger a policy proposal. "measured" signals carry full weight; "derived"
# signals (computed from other real data, not directly observed) carry half
# weight and can never trigger a proposal on their own.
_PROVENANCE_WEIGHT: dict[str, float] = {
    "measured": 1.0,
    "derived": 0.5,
}


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
            "proposal_kind": self.proposal_kind,
            "impacted_assets": self.impacted_assets,
            "risk_level": self.risk_level,
            "rationale": self.rationale,
            "suggested_change": self.suggested_change,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "source": self.source,
            "routing_hint": self.routing_hint,
        }

    @property
    def proposal_kind(self) -> str:
        if self.source == "context_gaps":
            return "context_update"
        normalized_file = self.policy_file.strip().lower()
        if normalized_file == "skills.md":
            return "skill_update"
        if normalized_file.startswith("wiki/"):
            return "wiki_update"
        if self.routing_hint:
            return "routing_hint"
        return "policy_note"

    @property
    def impacted_assets(self) -> list[str]:
        normalized_file = self.policy_file.strip().lstrip("/")
        if normalized_file.startswith("policy-pack/") or normalized_file.startswith("wiki/"):
            return [normalized_file]
        return [f"policy-pack/{normalized_file}"]

    @property
    def risk_level(self) -> str:
        if self.proposal_kind == "routing_hint":
            return "high"
        if self.proposal_kind == "context_update":
            return "medium"
        if self.proposal_kind in {"skill_update", "wiki_update"} or self.confidence >= 0.8:
            return "medium"
        return "low"


@dataclass(frozen=True)
class EvolutionPolicy:
    """Runtime policy for learn-evolve quality-signal deviation gating.

    Mirrors the shape of ``QualityLoopPolicy.from_escalation`` in
    ``src/runtime/quality_policy.py``: values are sourced from the
    ``learn_evolve`` block of a policy pack's ``escalation.md``, falling back
    to today's hardcoded defaults (0.1 / 0.8 / 2) when absent.
    """

    deviation_threshold: float = 0.1
    pass_gate: float = 0.8
    proposal_gate: int = 2
    # Measured JUDGE routing feedback (src/runtime/judge_scoring.py's bake-off
    # history -> a model-routing.md proposal): a provider needs at least
    # `bakeoff_min_wins` judged wins for a task class, at or above
    # `bakeoff_min_win_rate` of that class's judged bake-offs, before
    # `Evolver.propose_from_bakeoff_history` proposes routing that class to it.
    bakeoff_min_wins: int = 5
    bakeoff_min_win_rate: float = 0.7

    @classmethod
    def from_escalation(cls, escalation: dict[str, Any] | None = None) -> "EvolutionPolicy":
        if not isinstance(escalation, dict):
            return cls()
        config = escalation.get("learn_evolve")
        if not isinstance(config, dict):
            return cls()
        return cls(
            deviation_threshold=_non_negative_float(
                config.get("deviation_threshold"), cls.deviation_threshold
            ),
            pass_gate=_non_negative_float(config.get("pass_gate"), cls.pass_gate),
            proposal_gate=_non_negative_int(config.get("proposal_gate"), cls.proposal_gate),
            bakeoff_min_wins=_non_negative_int(
                config.get("bakeoff_min_wins"), cls.bakeoff_min_wins
            ),
            bakeoff_min_win_rate=_non_negative_float(
                config.get("bakeoff_min_win_rate"), cls.bakeoff_min_win_rate
            ),
        )


def _non_negative_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


class Evolver:
    PASS_GATE = 0.8
    PROPOSAL_GATE = 2

    def __init__(self, policy: EvolutionPolicy | None = None):
        self.policy = policy or EvolutionPolicy()
        # Instance attributes shadow the class constants above so existing
        # references to self.PASS_GATE / self.PROPOSAL_GATE stay correct
        # while remaining tunable via policy without touching call sites.
        self.PASS_GATE = self.policy.pass_gate
        self.PROPOSAL_GATE = self.policy.proposal_gate
        self.BAKEOFF_MIN_WINS = self.policy.bakeoff_min_wins
        self.BAKEOFF_MIN_WIN_RATE = self.policy.bakeoff_min_win_rate

    def ingest_harness_outcome(self, outcome: Any) -> list[PolicyProposal]:
        """
        Score a HarnessOutcome against the per-TaskClass baseline.
        Generates proposals when quality signals deviate by more than 10%,
        weighted by signal provenance.

        Provenance weighting: "measured" signals count fully (1.0), "derived"
        signals (computed from other real data, not directly observed) count
        at half weight (0.5). Unknown/absent provenance (legacy outcomes
        persisted before signal_provenance existed) is treated as "measured"
        for backward compatibility.

        A proposal batch only fires when at least one of the deviating
        signals is measured-provenance — derived-only evidence is held back
        (and logged at debug level) rather than triggering a proposal.
        """
        proposals: list[PolicyProposal] = []
        baseline = self._get_or_create_baseline(outcome.task_class.value)
        provenance_map = getattr(outcome, "signal_provenance", {}) or {}

        deviations: list[tuple[str, float, float, str]] = []
        for signal_name, measured_value in outcome.quality_signals.items():
            expected = baseline.get(signal_name)
            if expected is None:
                baseline[signal_name] = measured_value
                continue
            delta = measured_value - expected
            provenance = provenance_map.get(signal_name, "measured")
            weight = _PROVENANCE_WEIGHT.get(provenance, 1.0)
            if abs(delta * weight) > self.policy.deviation_threshold:
                deviations.append((signal_name, delta, weight, provenance))

        if not deviations:
            return proposals

        if not any(provenance == "measured" for _, _, _, provenance in deviations):
            logger.debug(
                "Holding back %d quality-signal deviation(s) for task class %s: "
                "all derived-provenance, no measured signal among contributors (%s).",
                len(deviations),
                outcome.task_class.value,
                ", ".join(name for name, _, _, _ in deviations),
            )
            return proposals

        for signal_name, delta, weight, provenance in deviations:
            proposals.extend(
                self._proposals_for_quality_deviation(outcome, signal_name, delta, provenance, weight)
            )

        return proposals

    def _get_or_create_baseline(self, task_class_value: str) -> dict[str, float]:
        if not hasattr(self, "_harness_baselines"):
            self._harness_baselines: dict[str, dict[str, float]] = {}
        return self._harness_baselines.setdefault(task_class_value, {})

    def _proposals_for_quality_deviation(
        self,
        outcome: Any,
        signal_name: str,
        delta: float,
        provenance: str = "measured",
        weight: float = 1.0,
    ) -> list[PolicyProposal]:
        direction = "degraded" if delta < 0 else "improved"
        task_class_value = outcome.task_class.value
        return [
            PolicyProposal(
                title=f"Quality signal '{signal_name}' {direction} for {task_class_value}",
                policy_file="wiki/harness-quality.md",
                rationale=(
                    f"Signal '{signal_name}' deviated by {delta:+.2f} from baseline "
                    f"for task class {task_class_value} "
                    f"(harness {outcome.harness_id}, task {outcome.task_id}). "
                    f"Evidence provenance: {provenance} (weight {weight:.1f})."
                ),
                suggested_change=(
                    f"Review {'assembly defaults' if delta < 0 else 'routing strategy'} for "
                    f"{task_class_value} tasks, focusing on {signal_name} optimization."
                ),
                evidence_refs=[f"{outcome.task_id}:quality:{signal_name}:{provenance}"],
                confidence=min(1.0, 0.5 + abs(delta)),
                source="harness_outcome",
            )
        ]

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
        bakeoff_history: list[dict[str, Any]] | None = None,
    ) -> list[PolicyProposal]:
        """Generate policy proposals without applying them to policy files."""
        proposals = self.propose_from_learning_records(learning_records or [])
        proposals.extend(self.propose_from_patterns(patterns or []))
        proposals.extend(self.propose_from_bakeoff_history(bakeoff_history))
        return proposals

    def propose_from_bakeoff_history(
        self,
        history: list[dict[str, Any]] | None,
        *,
        min_wins: int | None = None,
        min_win_rate: float | None = None,
    ) -> list[PolicyProposal]:
        """Turn repeated measured JUDGE wins into a model-routing.md proposal.

        Reads records written by ``TaskGraphExecutor._record_bakeoff_outcome``
        via ``src/runtime/judge_scoring.py``'s ``BakeoffHistoryStore``
        (``{"task_class", "provider", "weighted_score", ...}`` per judged
        fan-out). When one provider has won at least ``min_wins`` (default
        from policy, itself defaulting to 5) judged bake-offs for a task
        class, at or above ``min_win_rate`` (default from policy, itself
        defaulting to 0.7) of that class's judged bake-offs, this proposes
        routing that task class to the winning provider — closing the loop
        from measured bake-off evidence back into ``model-routing.md``.

        Absent history (``None`` or empty), returns ``[]`` — this is a pure
        additive extension, so ``generate_policy_proposals`` behaves exactly
        as before when no bake-off history is supplied.
        """
        if not history:
            return []
        resolved_min_wins = self.BAKEOFF_MIN_WINS if min_wins is None else min_wins
        resolved_min_win_rate = self.BAKEOFF_MIN_WIN_RATE if min_win_rate is None else min_win_rate

        totals: dict[str, dict[str, Any]] = {}
        for record in history:
            if not isinstance(record, dict):
                continue
            provider = record.get("provider")
            if not provider:
                continue
            task_class = str(record.get("task_class") or "unknown")
            bucket = totals.setdefault(task_class, {"total": 0, "wins": {}, "scores": {}})
            bucket["total"] += 1
            wins = bucket["wins"]
            wins[str(provider)] = wins.get(str(provider), 0) + 1
            score = record.get("weighted_score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                bucket["scores"].setdefault(str(provider), []).append(float(score))

        proposals: list[PolicyProposal] = []
        for task_class, data in sorted(totals.items()):
            total = data["total"]
            for provider, wins in sorted(data["wins"].items()):
                if wins < resolved_min_wins:
                    continue
                win_rate = wins / total if total else 0.0
                if win_rate < resolved_min_win_rate:
                    continue
                scores = data["scores"].get(provider, [])
                avg_score = sum(scores) / len(scores) if scores else None
                avg_score_text = f"{avg_score:.2f}" if avg_score is not None else "n/a"
                proposals.append(
                    PolicyProposal(
                        title=f"Route {task_class} to {provider}",
                        policy_file="model-routing.md",
                        rationale=(
                            f"{provider} won {wins} of {total} judged bake-off(s) "
                            f"({win_rate:.0%} win rate) for task class {task_class}, "
                            f"avg weighted score {avg_score_text}."
                        ),
                        suggested_change=(
                            f"Route {task_class} tasks to {provider} (e.g. via a "
                            f"phase_providers/task_class override in model-routing.md) instead "
                            "of the current default."
                        ),
                        evidence_refs=[f"bakeoff:{task_class}:{provider}:{wins}/{total}"],
                        confidence=min(1.0, win_rate),
                        source="bakeoff_history",
                        routing_hint={
                            "task_class": task_class,
                            "preferred_provider": provider,
                            "wins": wins,
                            "total": total,
                            "win_rate": round(win_rate, 3),
                        },
                    )
                )
        return proposals

    def propose_from_learning_records(self, records: list[Any]) -> list[PolicyProposal]:
        failures: dict[str, dict[str, Any]] = {}
        provider_failures: dict[tuple[str, str], dict[str, Any]] = {}
        escalations: dict[str, dict[str, Any]] = {}
        hotspots: dict[str, dict[str, Any]] = {}
        context_gaps: dict[str, dict[str, Any]] = {}

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
            self._accumulate_context_signal(
                context_gaps,
                self._record_value(record, "context_gaps", []),
                task_id,
            )

        proposals: list[PolicyProposal] = []
        proposals.extend(self._proposals_for_repeated_failures(failures))
        proposals.extend(self._proposals_for_provider_failures(provider_failures))
        proposals.extend(self._proposals_for_escalations(escalations))
        proposals.extend(self._proposals_for_iteration_hotspots(hotspots))
        proposals.extend(self._proposals_for_context_gaps(context_gaps))
        return sorted(proposals, key=lambda proposal: (proposal.policy_file, proposal.title))

    def propose_from_patterns(self, patterns: list[Pattern]) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for pattern in sorted(patterns, key=lambda item: item.name):
            if not self.should_promote(pattern):
                continue
            proposals.append(
                PolicyProposal(
                    title=f"Promote learned pattern: {pattern.name}",
                    policy_file="skills.md",
                    rationale=(
                        f"Pattern '{pattern.name}' met the promotion gate with "
                        f"{pattern.pass_rate:.0%} pass rate."
                    ),
                    suggested_change=(
                        f"Capture '{pattern.name}' as a reusable skill or routing hint, including "
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

    def _accumulate_context_signal(
        self,
        bucket: dict[str, dict[str, Any]],
        items: Any,
        task_id: str,
    ) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            phase = str(item.get("phase", "unknown"))
            value = self._positive_int(item.get("count", 1))
            trimmed = item.get("trimmed_sections") if isinstance(item.get("trimmed_sections"), list) else []
            reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
            estimated = self._positive_int(item.get("estimated_tokens", 0))
            budget = self._positive_int(item.get("token_budget", 0))
            entry = bucket.setdefault(
                phase,
                {"total": 0, "evidence_refs": [], "trimmed_sections": set(), "reasons": set(), "estimated_tokens": 0, "token_budget": 0},
            )
            entry["total"] += value
            entry["evidence_refs"].append(f"{task_id}:context_gaps:{phase}")
            entry["trimmed_sections"].update(str(section) for section in trimmed if str(section).strip())
            entry["reasons"].update(str(reason) for reason in reasons if str(reason).strip())
            if estimated > entry["estimated_tokens"]:
                entry["estimated_tokens"] = estimated
            if budget > entry["token_budget"]:
                entry["token_budget"] = budget

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
                    title=f"Capture {phase} escalation playbook",
                    policy_file="wiki/review-loop.md",
                    rationale=f"{phase} recorded {total} escalation signal(s).",
                    suggested_change=(
                        f"Document a reusable {phase} escalation playbook with stop conditions, "
                        "handoff cues, and reviewer expectations before another escalation loop."
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
                    title=f"Add {phase} iteration guard skill",
                    policy_file="skills.md",
                    rationale=f"{phase} accumulated {total} iteration hotspot signal(s).",
                    suggested_change=(
                        f"Add a reusable {phase} pre-check or routing skill hint to reduce "
                        "avoidable iteration loops before another full execution pass."
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="iteration_hotspots",
                )
            )
        return proposals

    def _proposals_for_context_gaps(
        self, context_gaps: dict[str, dict[str, Any]]
    ) -> list[PolicyProposal]:
        proposals: list[PolicyProposal] = []
        for phase, data in context_gaps.items():
            total = data["total"]
            if total < self.PROPOSAL_GATE:
                continue
            trimmed_sections = sorted(str(item) for item in data.get("trimmed_sections", set()) if str(item).strip())
            reasons = sorted(str(item) for item in data.get("reasons", set()) if str(item).strip())
            detail_bits: list[str] = []
            estimated = data.get("estimated_tokens", 0)
            budget = data.get("token_budget", 0)
            if trimmed_sections:
                detail_bits.append("trimmed sections: " + ", ".join(trimmed_sections[:3]))
            if "near_budget" in reasons and estimated and budget:
                detail_bits.append(f"near budget: {estimated}/{budget} tokens")
            detail = f" Context pressure: {'; '.join(detail_bits)}." if detail_bits else ""
            has_trimmed = "trimmed_sections" in reasons
            title_verb = "Reduce" if has_trimmed else "Optimize"
            proposals.append(
                PolicyProposal(
                    title=f"{title_verb} {phase} context omission risk" if has_trimmed else f"{title_verb} {phase} context budget pressure",
                    policy_file="wiki/context-compiler.md",
                    rationale=(
                        f"{phase} recorded {total} context-pressure signal(s)."
                        f"{detail} Consider documenting which sections can be safely prioritized or when to expand retrieval."
                    ),
                    suggested_change=(
                        f"Add {phase} context-compilation guidance to wiki/context-compiler.md. "
                        + (f"Specifically address: {', '.join(trimmed_sections[:2])}." if trimmed_sections else "Document token budget allocation strategy.")
                    ),
                    evidence_refs=data["evidence_refs"],
                    confidence=self._confidence(total),
                    source="context_gaps",
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
    """Human review/apply workflow for generated policy proposals.

    Decisions are always persisted to ``.sarathi-proposals/<id>.json`` under
    the policy pack -- that file layout is relied on directly by
    ``src/policy/compiler.py`` (``_load_learning_feedback``) and must keep
    working unmodified regardless of anything below.

    When the owning workspace already has a ``.sarathi/sarathi.db`` (i.e. it
    has been bootstrapped for the service / web cockpit at some point), each
    decision is additionally mirrored into that database -- a durable,
    queryable row plus a ``proposal.accepted``/``proposal.rejected``
    lifecycle event -- via ``proposal_sync.ProposalSync``. See that module's
    docstring for the full design. Pass ``mirror=False`` when the caller
    already owns a ``Storage`` handle for the right workspace and will record
    the SQLite side itself (this is what ``src/service/proposals.py`` does,
    to avoid emitting the lifecycle event twice for a single action).
    """

    def __init__(self, policy_pack_path: str | Path, mirror: bool = True):
        self.policy_pack_path = Path(policy_pack_path)
        self.workspace_root = self.policy_pack_path.parent
        self.review_dir = self.policy_pack_path / ".sarathi-proposals"
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self._sync: ProposalSync | None = None
        if mirror:
            try:
                self._sync = ProposalSync.try_create(self.workspace_root, self.review_dir)
            except Exception:  # best-effort by contract: never break store construction
                logger.warning("proposal_sync activation failed", exc_info=True)
                self._sync = None

    def accept(self, proposal: PolicyProposal) -> dict[str, Any]:
        policy_file = self._resolve_target_path(proposal)
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        marker = f"proposal-id: {proposal.proposal_id}"
        current = policy_file.read_text() if policy_file.exists() else ""
        after_text = self._apply_to_policy_text(current, proposal)
        if marker not in current:
            policy_file.write_text(after_text)
        decision = self._decision(
            "accepted", proposal, before_text=current, after_text=after_text
        )
        self._write_decision(decision)
        if self._sync is not None:
            self._sync.record_decision(decision)
        return decision

    def reject(self, proposal: PolicyProposal, reason: str | None = None) -> dict[str, Any]:
        decision = self._decision("rejected", proposal, reason=reason)
        self._write_decision(decision)
        if self._sync is not None:
            self._sync.record_decision(decision)
        return decision

    def rollback(self, proposal_id: str, force: bool = False) -> dict[str, Any]:
        """Undo a previously accepted proposal by restoring its pre-accept text.

        Reads the original acceptance decision from ``.sarathi-proposals/<id>.json``,
        verifies the target file still matches what the acceptance wrote (unless
        ``force``), restores ``before_text``, and records a new ``rolled_back``
        decision so the rollback itself is snapshotted and reversible the same way.
        """
        decision_path = self.review_dir / f"{proposal_id}.json"
        if not decision_path.exists():
            raise ValueError(f"No recorded decision for proposal '{proposal_id}'")
        decision = self._read_decision(decision_path)
        if decision.get("status") != "accepted":
            raise ValueError(
                f"Proposal '{proposal_id}' is not in an 'accepted' state "
                f"(status={decision.get('status')!r}); nothing to roll back"
            )
        before_text = decision.get("before_text")
        after_text = decision.get("after_text")
        if before_text is None:
            raise ValueError(
                f"Decision for proposal '{proposal_id}' has no recorded snapshot "
                "(it predates rollback support); rollback is not available"
            )
        # Resolve using the same rule accept() used, without needing the original
        # PolicyProposal object -- decision.policy_file already holds the raw target.
        policy_file = self._resolve_stored_path(decision["policy_file"])
        current = policy_file.read_text() if policy_file.exists() else ""
        if not force and after_text is not None and current != after_text:
            raise ValueError(
                f"'{policy_file}' has changed since proposal '{proposal_id}' was "
                "accepted; pass force=True to overwrite anyway"
            )
        policy_file.write_text(before_text)
        rollback_decision = dict(decision)
        rollback_decision.update(
            {
                "status": "rolled_back",
                "before_text": after_text,
                "after_text": before_text,
                "reason": None,
                "reviewed_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        rollback_path = (
            self.review_dir
            / f"{proposal_id}.rollback-{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.json"
        )
        self._write_decision(rollback_decision, path=rollback_path)
        if self._sync is not None:
            self._sync.record_decision(rollback_decision)
        return rollback_decision

    def preview_acceptance(self, proposal: PolicyProposal) -> dict[str, Any]:
        policy_file = self._resolve_target_path(proposal)
        if not policy_file.exists():
            return {
                "path": str(policy_file),
                "exists": False,
                "current_content": "",
                "accepted_preview": self._apply_to_policy_text("", proposal),
            }
        current = policy_file.read_text()
        return {
            "path": str(policy_file),
            "exists": True,
            "current_content": current,
            "accepted_preview": self._apply_to_policy_text(current, proposal),
        }

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
                "proposal_kind": proposal.proposal_kind,
                "impacted_assets": proposal.impacted_assets,
                "risk_level": proposal.risk_level,
                "confidence": proposal.confidence,
                "suggested_change": proposal.suggested_change,
                "evidence_refs": proposal.evidence_refs,
                "routing_hint": proposal.routing_hint,
            }
        )
        replacement = "```yaml\n" + yaml.safe_dump(parsed, sort_keys=False).rstrip() + "\n```"
        return current[: yaml_match.start()] + replacement + current[yaml_match.end():]

    def _resolve_target_path(self, proposal: PolicyProposal) -> Path:
        return self._resolve_stored_path(proposal.policy_file)

    def _resolve_stored_path(self, policy_file: str) -> Path:
        target = policy_file.strip().lstrip("/")
        if target.startswith("wiki/") or target in {"SARATHI.md", "learnings.md"}:
            return self.workspace_root / target
        return self.policy_pack_path / target

    def _decision(
        self,
        status: str,
        proposal: PolicyProposal,
        reason: str | None = None,
        before_text: str | None = None,
        after_text: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": proposal.proposal_id,
            "status": status,
            "policy_file": proposal.policy_file,
            "title": proposal.title,
            "source": proposal.source,
            "proposal_kind": proposal.proposal_kind,
            "impacted_assets": proposal.impacted_assets,
            "risk_level": proposal.risk_level,
            "confidence": proposal.confidence,
            "suggested_change": proposal.suggested_change,
            "evidence_refs": proposal.evidence_refs,
            "routing_hint": proposal.routing_hint,
            "reason": reason,
            "reviewed_at": datetime.utcnow().isoformat() + "Z",
            "before_text": before_text,
            "after_text": after_text,
        }

    def _write_decision(self, decision: dict[str, Any], path: Path | None = None) -> None:
        import json

        target = path if path is not None else self.review_dir / f"{decision['id']}.json"
        target.write_text(json.dumps(decision, indent=2))

    def _read_decision(self, path: Path) -> dict[str, Any]:
        import json

        return json.loads(path.read_text())
