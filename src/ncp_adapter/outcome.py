"""Send measured task outcomes back to NCP so it can learn which memory helped.

NCP raises or lowers the trust of chunks (and the reputation of their authors)
from recorded outcomes. Sarathi already measures each task's quality in
``harness.measure_outcome``; this module turns that measurement into one
``record_outcome`` call per task, crediting the NCP chunks the task actually
read (``fetch``/``get_context``) and wrote (``write_memory``).

Nothing here asserts quality: success and the evidence weight are derived
only from the measured ``HarnessOutcome`` and the recorded phase results.
"""
from __future__ import annotations

import threading
from typing import Any

from ._transport import NCPTransportMixin, parse_chunk_ids

__all__ = [
    "NCPOutcomeLedger",
    "NCPOutcomeReporter",
    "derive_ncp_outcome",
    "parse_chunk_ids",
]

# Bound the credited set: NCP caps chunk_ids per outcome, and a long graph run
# can touch many chunks. Most recent wins (they shaped the final result).
MAX_CREDITED_CHUNKS = 200

# Outcomes backed by a real VERIFY command count fully; outcomes resting only
# on review verdicts or phase outcomes count half (they are self-reported).
VERIFIED_WEIGHT = 1.0
SELF_REPORTED_WEIGHT = 0.5


class NCPOutcomeLedger:
    """Chunk ids the active task consumed and produced, for outcome credit.

    One engine runs one task at a time, but graph fanout dispatches nodes on
    worker threads, so every method takes the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._task_id: str | None = None
        self._consumed: dict[str, None] = {}
        self._produced: dict[str, None] = {}

    @property
    def task_id(self) -> str | None:
        with self._lock:
            return self._task_id

    def begin(self, task_id: str) -> None:
        """Start collecting for ``task_id``; drops anything left from another task."""
        with self._lock:
            if self._task_id != task_id:
                self._consumed.clear()
                self._produced.clear()
            self._task_id = task_id

    def note_consumed(self, chunk_ids: list[str]) -> None:
        with self._lock:
            for chunk_id in chunk_ids:
                self._consumed.pop(chunk_id, None)
                self._consumed[chunk_id] = None

    def note_produced(self, chunk_id: str) -> None:
        with self._lock:
            self._produced.pop(chunk_id, None)
            self._produced[chunk_id] = None

    def snapshot(self) -> dict[str, list[str]]:
        with self._lock:
            return {"consumed": list(self._consumed), "produced": list(self._produced)}

    def drain(self) -> dict[str, list[str]]:
        """Return and clear the collected ids."""
        with self._lock:
            result = {"consumed": list(self._consumed), "produced": list(self._produced)}
            self._consumed.clear()
            self._produced.clear()
            self._task_id = None
            return result


def _phase_name(phase_result: Any) -> str:
    phase = getattr(phase_result, "phase", None)
    return str(getattr(phase, "value", phase or ""))


# Phase outcomes that make a task a failure unless policy says otherwise
# (escalation.md learn_evolve.failure_outcomes). "escalate" means the task
# needed a human, so it is not evidence that the memory it used works.
DEFAULT_FAILURE_OUTCOMES: tuple[str, ...] = ("fail", "escalate")


def derive_ncp_outcome(
    task: Any,
    outcome: Any,
    *,
    failure_outcomes: tuple[str, ...] | list[str] = DEFAULT_FAILURE_OUTCOMES,
) -> dict[str, Any]:
    """Map a measured ``HarnessOutcome`` to ``record_outcome`` arguments.

    Returns ``success``, ``weight``, ``note`` and ``ctx`` (without chunk ids).

    - Failure when any phase ended in one of ``failure_outcomes`` (default
      ``fail`` or ``escalate``), a rollback was triggered, or a measured test
      run failed. Otherwise success.
    - ``eval_source`` is ``verifier`` only when ``test_pass_rate`` was measured
      from a real VERIFY command; otherwise ``self_report`` at half weight.
    """
    phase_results = list(getattr(task, "phase_results", []) or [])
    signals: dict[str, float] = dict(getattr(outcome, "quality_signals", {}) or {})
    provenance: dict[str, str] = dict(getattr(outcome, "signal_provenance", {}) or {})

    failing = set(failure_outcomes)
    failed_phases = [
        f"{_phase_name(pr)}={getattr(pr, 'outcome', '')}"
        for pr in phase_results
        if getattr(pr, "outcome", "") in failing
    ]
    tests_measured = provenance.get("test_pass_rate") == "measured"
    tests_failed = tests_measured and signals.get("test_pass_rate", 1.0) < 1.0
    rollback = bool(getattr(outcome, "rollback_triggered", False))
    success = not failed_phases and not rollback and not tests_failed

    input_tokens = 0
    output_tokens = 0
    turns = 0
    for pr in phase_results:
        usage = (getattr(pr, "artifacts", {}) or {}).get("dispatch_usage")
        if isinstance(usage, dict):
            turns += 1
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)

    reasons: list[str] = []
    if failed_phases:
        reasons.append("failed phases: " + ",".join(failed_phases))
    if rollback:
        reasons.append("rollback triggered")
    if tests_failed:
        reasons.append("tests failed")
    task_class = getattr(getattr(outcome, "task_class", None), "value", None)
    note = f"sarathi task {getattr(outcome, 'task_id', '')}"
    note += f" ({'; '.join(reasons)})" if reasons else " (all phases passed)"

    ctx: dict[str, Any] = {
        "eval_source": "verifier" if tests_measured else "self_report",
        "turns": turns,
    }
    if task_class:
        ctx["task"] = str(task_class)
    agent = getattr(outcome, "agent_used", None)
    if agent:
        ctx["model"] = str(agent)
    if input_tokens:
        ctx["input_tokens"] = input_tokens
    if output_tokens:
        ctx["output_tokens"] = output_tokens

    return {
        "success": success,
        "weight": VERIFIED_WEIGHT if tests_measured else SELF_REPORTED_WEIGHT,
        "note": note[:500],
        "ctx": ctx,
    }


class NCPOutcomeReporter(NCPTransportMixin):
    """Records one NCP outcome per task from its measured ``HarnessOutcome``."""

    def __init__(self, *args: Any, ledger: NCPOutcomeLedger | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.outcome_ledger = ledger or NCPOutcomeLedger()

    def report(
        self,
        task: Any,
        outcome: Any,
        *,
        failure_outcomes: tuple[str, ...] | list[str] = DEFAULT_FAILURE_OUTCOMES,
    ) -> dict[str, Any]:
        """Record the outcome; never raises. Returns a summary for LEARN evidence."""
        collected = self.outcome_ledger.drain()
        # Read chunks first, then this task's own writes; keep the most recent.
        chunk_ids = list(dict.fromkeys(collected["consumed"] + collected["produced"]))
        chunk_ids = chunk_ids[-MAX_CREDITED_CHUNKS:]
        derived = derive_ncp_outcome(task, outcome, failure_outcomes=failure_outcomes)
        summary: dict[str, Any] = {
            "recorded": False,
            "success": derived["success"],
            "weight": derived["weight"],
            "eval_source": derived["ctx"]["eval_source"],
            "credited_chunks": len(chunk_ids),
            "consumed_chunks": len(collected["consumed"]),
            "produced_chunks": len(collected["produced"]),
        }
        if not chunk_ids:
            # Nothing NCP served or stored shaped this task: no trust to move.
            summary["skipped"] = "no_ncp_chunks"
            return summary
        try:
            result = self._call_record_outcome({**derived, "chunk_ids": chunk_ids})
        except Exception as exc:  # best effort: never fail LEARN over feedback
            summary["error"] = str(exc)[:300]
            return summary
        summary.update(
            recorded=bool(result.get("recorded")),
            outcome_id=result.get("outcome_id"),
            calibrated=bool(result.get("calibrated")),
        )
        if result.get("unsupported"):
            summary["error"] = str(result["unsupported"])
        return summary
