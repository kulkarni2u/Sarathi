"""Measured JUDGE scoring: policy-driven scorecards for FANOUT bake-offs.

Today's JUDGE node (see ``graph_executor.py``'s ``NodeType.JUDGE`` handling)
is a single vibe-based dispatch: it sees whatever context the SYNTHESIZE
fan-in node collected and picks a winner with no structured signal. This
module adds a *deterministic, policy-driven* companion to that judgment:

- :class:`JudgeScoringPolicy` parses a ``judge_scoring:`` block from a policy
  pack's ``review.md`` (see ``policy-pack/EXAMPLE/review.md`` for a documented
  example) — a mapping of measured-signal weights plus a preferred direction
  ("high" or "low" is better) for each signal.
- :func:`assemble_judge_scorecard` walks the branch nodes a JUDGE node
  depends on (directly, or through an injected SYNTHESIZE fan-in node) and
  pulls the *measured* evidence each branch's dispatch already recorded
  (provider, ``UsageRecord.cost_usd``, ``provider_duration_ms``, the workspace
  delta's ``change_count`` as a blast-radius proxy, and a test-pass signal
  when a branch's evidence happens to carry one) into one scorecard, with a
  deterministic weighted score per branch.
- :class:`BakeoffHistoryStore` persists judged-fanout outcomes (provider,
  task_class, winning score) to ``<workspace>/.sarathi/bakeoff_history.json``
  so ``src/evolve.py`` can turn repeated wins into a routing proposal — the
  same append-only, atomic-write JSON pattern as
  ``src/runtime/provider_health.py``.

The engine stays generic: absent a ``judge_scoring`` policy block, every
function here is a no-op (empty scorecard, nothing recorded) and JUDGE
dispatch is byte-for-byte what it was before this module existed.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11
    UTC = timezone.utc

# Best-effort reuse of the existing confidence_weights validator so
# judge_scoring weights are held to the same "sums to ~1.0" bar as
# conventions.md's confidence_weights (src/policy/validator.py:_weight_issues).
# This is deliberately optional: judge_scoring is parsed and consumed from
# src/runtime (dispatch-time), while validator.py lives in the policy-compile
# layer, so a missing/renamed helper there degrades to a local equivalent
# rather than breaking scoring.
try:
    from src.policy.validator import _weight_issues as _confidence_weight_issues
except ImportError:
    try:
        from policy.validator import _weight_issues as _confidence_weight_issues
    except ImportError:
        _confidence_weight_issues = None


_SIGNAL_PREFER_DEFAULT = "high"
_VALID_PREFER_DIRECTIONS = {"high", "low"}


@dataclass(frozen=True)
class JudgeScoringPolicy:
    """Parsed ``judge_scoring:`` policy from review.md.

    ``weights`` maps signal name -> non-negative weight. ``prefer`` maps the
    same signal names to ``"high"`` (bigger raw value scores better, e.g.
    ``test_pass_rate``) or ``"low"`` (smaller raw value scores better, e.g.
    ``cost_usd``, ``latency_ms``, ``blast_radius``). Signals absent from
    ``prefer`` default to ``"high"``.

    ``validation_issue`` mirrors ``conventions.md``'s confidence_weights
    check: non-``None`` when the weights don't sum to ~1.0. It is informational
    only here — a policy pack author will see it via a validator/report, but a
    slightly-off weight sum still produces a (documented) scorecard rather
    than silently disabling the feature.
    """

    weights: dict[str, float]
    prefer: dict[str, str] = field(default_factory=dict)
    validation_issue: str | None = None

    @classmethod
    def from_review(cls, review: Any) -> "JudgeScoringPolicy | None":
        """Parse a ``judge_scoring`` block out of a compiled ``review`` section.

        Returns ``None`` when the block is absent or has no usable weights —
        callers must treat ``None`` as "feature off," not "empty policy," so
        judge dispatch stays identical to today's behavior.
        """
        if not isinstance(review, dict):
            return None
        config = review.get("judge_scoring")
        if not isinstance(config, dict):
            return None

        raw_weights = config.get("weights")
        if not isinstance(raw_weights, dict) or not raw_weights:
            return None

        weights: dict[str, float] = {}
        for name, raw_value in raw_weights.items():
            if not isinstance(name, str) or not name.strip():
                continue
            weight = _non_negative_float(raw_value)
            if weight is not None:
                weights[name] = weight
        if not weights:
            return None

        raw_prefer = config.get("prefer")
        raw_prefer = raw_prefer if isinstance(raw_prefer, dict) else {}
        prefer: dict[str, str] = {}
        for name in weights:
            direction = str(raw_prefer.get(name, _SIGNAL_PREFER_DEFAULT)).strip().lower()
            prefer[name] = direction if direction in _VALID_PREFER_DIRECTIONS else _SIGNAL_PREFER_DEFAULT

        return cls(weights=weights, prefer=prefer, validation_issue=_weight_sum_issue(weights))


def _weight_sum_issue(weights: dict[str, float]) -> str | None:
    if _confidence_weight_issues is not None:
        try:
            issue = _confidence_weight_issues(weights)
            if issue:
                return issue.replace("confidence_weights", "judge_scoring.weights")
            return None
        except Exception:
            pass
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        return f"judge_scoring.weights sum to {total:.3f}, expected 1.0"
    return None


# ---------------------------------------------------------------------------
# Branch evidence extraction
# ---------------------------------------------------------------------------


def collect_branch_node_ids(node: dict[str, Any], graph: dict[str, Any] | None) -> list[str]:
    """Find the branch node ids a JUDGE node is judging.

    Honors an explicit ``pattern_config.competitor_ids`` first (the
    convention ``NCPContextAdapter._fetch_competitor_outputs`` already uses).
    Otherwise walks the JUDGE node's ``depends_on``: a dependency that is
    itself a SYNTHESIZE fan-in node (the shape ``_inject_fanout_children``
    produces) is expanded to its ``pattern_config.source_ids``; a dependency
    whose id looks like a fanout branch (``-branch-`` in the id) is used
    directly. Order is preserved, duplicates dropped.
    """
    if not isinstance(graph, dict):
        return []
    cfg = node.get("pattern_config") if isinstance(node.get("pattern_config"), dict) else {}
    explicit = cfg.get("competitor_ids")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit]

    nodes_by_id = {
        graph_node.get("id"): graph_node
        for graph_node in graph.get("nodes", [])
        if isinstance(graph_node, dict)
    }
    branch_ids: list[str] = []
    seen: set[str] = set()
    for dep_id in node.get("depends_on", []) or []:
        dep_node = nodes_by_id.get(dep_id)
        # Note: NodeType is a `str, Enum` mixin, so `str(NodeType.SYNTHESIZE)`
        # is "NodeType.SYNTHESIZE" (Enum's __str__), not "synthesize" — but
        # the member still *equals* the plain string "synthesize" via the str
        # mixin, so compare directly rather than through str().
        if isinstance(dep_node, dict) and dep_node.get("node_type") == "synthesize":
            source_ids = dep_node.get("pattern_config", {}).get("source_ids")
            if isinstance(source_ids, list):
                for branch_id in source_ids:
                    key = str(branch_id)
                    if key not in seen:
                        seen.add(key)
                        branch_ids.append(key)
        elif "-branch-" in str(dep_id):
            key = str(dep_id)
            if key not in seen:
                seen.add(key)
                branch_ids.append(key)
    return branch_ids


def branch_signals(branch_node: dict[str, Any]) -> dict[str, Any]:
    """Pull measured signals out of a completed branch node's dispatch result.

    Reads ``branch_node["last_provider_result"]`` — the same dict
    ``TaskGraphExecutor._annotate_node_result`` stamps onto every completed
    node — so this only ever sees data the executor already recorded, never
    anything fabricated for the occasion. Any signal it can't find measured
    evidence for comes back ``None`` rather than a flattering/punishing
    default; callers handle missing signals by excluding them.
    """
    last_result = branch_node.get("last_provider_result")
    last_result = last_result if isinstance(last_result, dict) else {}
    outputs = last_result.get("outputs") if isinstance(last_result.get("outputs"), dict) else {}
    artifacts = last_result.get("artifacts") if isinstance(last_result.get("artifacts"), dict) else {}
    evidence = last_result.get("evidence") if isinstance(last_result.get("evidence"), dict) else {}
    usage = last_result.get("usage") if isinstance(last_result.get("usage"), dict) else {}
    pattern_config = branch_node.get("pattern_config") if isinstance(branch_node.get("pattern_config"), dict) else {}

    provider = pattern_config.get("provider") or artifacts.get("provider") or outputs.get("provider")

    workspace_delta = evidence.get("workspace_delta") if isinstance(evidence.get("workspace_delta"), dict) else {}
    blast_radius = (
        _non_negative_float(workspace_delta.get("change_count"))
        if workspace_delta.get("measured")
        else None
    )

    return {
        "provider": str(provider) if provider else None,
        "test_pass_rate": _extract_test_pass_rate(outputs, evidence),
        "blast_radius": blast_radius,
        "cost_usd": _optional_float(usage.get("cost_usd")),
        "latency_ms": _optional_float(artifacts.get("provider_duration_ms")),
    }


def _extract_test_pass_rate(outputs: dict[str, Any], evidence: dict[str, Any]) -> float | None:
    """Best-effort test-pass signal for a branch (mirrors harness.py's VERIFY read)."""
    verification_summary = evidence.get("verification_summary")
    if isinstance(verification_summary, dict) and "command_succeeded" in verification_summary:
        return 1.0 if verification_summary.get("command_succeeded") else 0.0

    work_unit_result = outputs.get("work_unit_result") if isinstance(outputs, dict) else None
    if isinstance(work_unit_result, dict) and "test_pass_rate" in work_unit_result:
        return _optional_float(work_unit_result.get("test_pass_rate"))

    if isinstance(outputs, dict) and "test_pass_rate" in outputs:
        return _optional_float(outputs.get("test_pass_rate"))

    return None


# ---------------------------------------------------------------------------
# Scorecard assembly + deterministic weighted scoring
# ---------------------------------------------------------------------------


def build_scorecard(
    policy: JudgeScoringPolicy, branch_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute a deterministic, per-branch weighted score.

    Each declared signal is min-max normalized *across the branches in this
    bake-off* (not against some global constant) so weights stay meaningful
    regardless of a signal's raw scale (dollars vs. milliseconds vs. a 0..1
    rate). A signal missing from a branch is excluded from that branch's
    normalization and its weight is dropped from the denominator, rather than
    penalizing (or rewarding) the branch for data it never reported. When
    every branch ties on a signal, that signal contributes a neutral 0.5 to
    every branch (no information to discriminate on).
    """
    signal_names = list(policy.weights.keys())

    raw_values: dict[str, list[float]] = {name: [] for name in signal_names}
    for entry in branch_entries:
        for name in signal_names:
            value = entry.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                raw_values[name].append(float(value))

    ranges: dict[str, tuple[float, float] | None] = {}
    for name, values in raw_values.items():
        ranges[name] = (min(values), max(values)) if values else None

    scorecard: list[dict[str, Any]] = []
    for entry in branch_entries:
        signal_scores: dict[str, float] = {}
        weighted_sum = 0.0
        weight_total = 0.0
        for name in signal_names:
            value = entry.get(name)
            value_range = ranges.get(name)
            if value_range is None or not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            low, high = value_range
            normalized = (value - low) / (high - low) if high > low else 0.5
            if policy.prefer.get(name) == "low":
                normalized = 1.0 - normalized
            signal_scores[name] = round(normalized, 4)
            weight = policy.weights[name]
            weighted_sum += weight * normalized
            weight_total += weight

        weighted_score = round(weighted_sum / weight_total, 4) if weight_total > 0 else None
        scored_entry = dict(entry)
        scored_entry["signal_scores"] = signal_scores
        scored_entry["weighted_score"] = weighted_score
        scorecard.append(scored_entry)
    return scorecard


def assemble_judge_scorecard(
    policy: "JudgeScoringPolicy | None",
    node: dict[str, Any],
    graph: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Assemble the full scorecard for a JUDGE node, or ``[]`` if not applicable.

    Returns ``[]`` (never ``None``) whenever scoring can't proceed — no
    policy, no graph, or no discoverable branch nodes — so callers can treat
    "no scorecard" and "empty scorecard" identically without a null check.
    """
    if policy is None or not isinstance(graph, dict):
        return []
    branch_ids = collect_branch_node_ids(node, graph)
    if not branch_ids:
        return []

    nodes_by_id = {
        graph_node.get("id"): graph_node
        for graph_node in graph.get("nodes", [])
        if isinstance(graph_node, dict)
    }
    branch_entries: list[dict[str, Any]] = []
    for branch_id in branch_ids:
        branch_node = nodes_by_id.get(branch_id)
        if not isinstance(branch_node, dict):
            continue
        entry = {"branch": branch_id, **branch_signals(branch_node)}
        branch_entries.append(entry)

    if not branch_entries:
        return []
    return build_scorecard(policy, branch_entries)


def format_scorecard_for_prompt(scorecard: list[dict[str, Any]]) -> list[str]:
    """Render the scorecard as compact text lines for the judge's context/prompt."""
    lines: list[str] = []
    for entry in scorecard:
        score = entry.get("weighted_score")
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        details = ", ".join(
            f"{key}={entry[key]}"
            for key in ("test_pass_rate", "blast_radius", "cost_usd", "latency_ms")
            if entry.get(key) is not None
        )
        provider = entry.get("provider") or "unknown"
        line = f"Judge scorecard - branch {entry.get('branch')} (provider={provider}): weighted_score={score_text}"
        if details:
            line += f", {details}"
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Bake-off history: persisted winner-per-task-class outcomes for evolve.py
# ---------------------------------------------------------------------------


class BakeoffHistoryStore:
    """Append-only, atomically-written history of judged FANOUT outcomes.

    Persists to ``<base_dir>/bakeoff_history.json`` as a JSON list of
    records. Reads tolerate a missing or corrupt file (start fresh); writes
    are atomic (write to a temp file, then ``os.replace``) — the same pattern
    as ``src/runtime/provider_health.py``'s ``ProviderHealthStore``.
    """

    def __init__(self, base_dir: str | os.PathLike[str]):
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / "bakeoff_history.json"

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_text()
        except OSError:
            return []
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

    def record(
        self,
        *,
        task_class: str,
        judge_node_id: str,
        winner_branch: str,
        provider: str | None,
        weighted_score: float | None,
        scorecard: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append one judged-outcome record and persist atomically."""
        entry = {
            "task_class": task_class,
            "judge_node_id": judge_node_id,
            "winner_branch": winner_branch,
            "provider": provider,
            "weighted_score": weighted_score,
            "scorecard": scorecard,
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        history = self.load()
        history.append(entry)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(history, indent=2))
        os.replace(tmp_path, self.path)
        return entry


def _non_negative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed
