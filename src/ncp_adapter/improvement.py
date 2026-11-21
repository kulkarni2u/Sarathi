"""Policy proposals as NCP improvement records, with a measured post-accept check.

NCP v1.9.7 keeps an improvement history: *problems* (root-cause hypotheses)
and the *attempts* filed under them, each with rationale, status
(proposed -> applied / rejected / rolled_back) and observed results. Its
SIM-based design rests on that history being what makes continued
improvement work, not problem names alone.

Sarathi maps its learn-evolve loop onto it:

- A generated ``PolicyProposal`` becomes an attempt (kind ``manual``) under
  the problem named by its title, scoped to its policy file. A recurring
  proposal reuses its open attempt, and the problem's earlier attempts are
  attached to the proposal so a reviewer sees what was tried before and how
  it ended.
- Accept / reject / rollback in ``ProposalReviewStore`` set the attempt's
  status.
- Post-accept check: Sarathi logs each finished task's measured outcome
  (``.sarathi/ncp_outcomes.jsonl``). Once enough tasks of the proposal's task
  class have finished on both sides of the acceptance, the attempt gets the
  observed success rate (``passed``/``total``) against the pre-accept rate
  (``anchor_rate``), and a drop below ``post_accept_gate_ratio`` x that rate is
  reported as a regression with a rollback recommendation. It never rolls
  back by itself: accepting a proposal is a human decision, so is undoing it.

NCP's ``ncp refine`` gate is not used: it judges a shorter rewrite of a
single procedure chunk, while a Sarathi proposal is a note appended to a
whole policy file after human review.

Improvement records need the direct bridge (``.ncp/run.py`` version 3) and
NCP's sqlite or pgvector store. In MCP mode they are reported unsupported:
NCP exposes them over MCP only in the ``full`` tool profile.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ._transport import _TRANSPORT_TIMEOUT, _UNKNOWN_COMMAND_EXIT, NCPTransportMixin

REGISTRY_FILE = "ncp_improvements.json"
OUTCOME_LOG_FILE = "ncp_outcomes.jsonl"
# Pre-accept outcomes compared against: the most recent ones before acceptance.
ANCHOR_WINDOW = 20
_UPGRADE_HINT = ".ncp/run.py has no improvement commands; re-run `sarathi init`"


def _rate(entries: list[dict[str, Any]]) -> tuple[float | None, float, float]:
    """Weighted success rate, success weight and total weight."""
    total = sum(float(e.get("weight", 1.0)) for e in entries)
    passed = sum(float(e.get("weight", 1.0)) for e in entries if e.get("success"))
    return (passed / total if total else None), passed, total


class OutcomeLog:
    """Append-only log of measured task outcomes, one JSON object per line."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, sort_keys=True) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+b") as handle:
                # After an interrupted write the file ends mid-line; start a
                # new line so this entry is not glued onto the torn one.
                handle.seek(0, os.SEEK_END)
                if handle.tell():
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        line = "\n" + line
                handle.write(line.encode("utf-8"))

    def entries(self, task_class: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        found: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn line must not break every later check
            if isinstance(entry, dict) and entry.get("task_class") == task_class:
                found.append(entry)
        return sorted(found, key=lambda e: float(e.get("at", 0)))


class ImprovementRegistry:
    """Sarathi proposal id -> NCP attempt, plus what the post-accept check needs."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


class NCPImprovementTracker(NCPTransportMixin):
    """Files proposals as NCP attempts and checks accepted ones against outcomes."""

    def __init__(
        self,
        *args: Any,
        workspace_root: str | Path,
        min_outcomes: int = 5,
        gate_ratio: float = 0.9,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        state_dir = Path(workspace_root) / ".sarathi"
        self.registry = ImprovementRegistry(state_dir / REGISTRY_FILE)
        self.outcome_log = OutcomeLog(state_dir / OUTCOME_LOG_FILE)
        self.min_outcomes = max(1, int(min_outcomes))
        self.gate_ratio = float(gate_ratio)
        self._lock = threading.Lock()

    @classmethod
    def for_workspace(
        cls, workspace_root: str | Path, *, policy: Any = None
    ) -> "NCPImprovementTracker | None":
        """A direct-mode tracker when the workspace has an executable NCP bridge."""
        run_path = Path(workspace_root) / ".ncp" / "run.py"
        if not (run_path.is_file() and os.access(run_path, os.X_OK)):
            return None
        return cls(
            mode="direct",
            run_path=run_path,
            workspace_root=workspace_root,
            min_outcomes=getattr(policy, "post_accept_min_outcomes", 5),
            gate_ratio=getattr(policy, "post_accept_gate_ratio", 0.9),
        )

    # ── transport ──────────────────────────────────────────────────────────

    def _call_bridge(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.mode != "direct":
            return {
                "unsupported": "NCP improvement records need direct mode (.ncp/run.py)"
            }
        result = subprocess.run(
            [str(self.run_path), command, json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=_TRANSPORT_TIMEOUT,
        )
        if (
            result.returncode == _UNKNOWN_COMMAND_EXIT
            and "unknown command" in result.stderr
        ):
            return {"unsupported": _UPGRADE_HINT}
        if result.returncode != 0:
            raise RuntimeError(
                f"NCP {command} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        decoded = json.loads(result.stdout or "{}")
        return decoded if isinstance(decoded, dict) else {}

    # ── proposals ──────────────────────────────────────────────────────────

    def record_proposals(
        self, proposals: Iterable[dict[str, Any]], *, task_class: str | None
    ) -> dict[str, dict[str, Any]]:
        """File each proposal artifact as an attempt; return annotations by proposal id.

        Never raises: a failure is returned as that proposal's ``error``.
        """
        annotations: dict[str, dict[str, Any]] = {}
        with self._lock:
            registry = self.registry.load()
            for proposal in proposals:
                proposal_id = str(proposal.get("id", ""))
                if not proposal_id:
                    continue
                args: dict[str, Any] = {
                    "scope": str(proposal.get("policy_file", "")),
                    "problem_name": str(proposal.get("title", "")),
                    "what": str(proposal.get("suggested_change", "")),
                    "rationale": str(proposal.get("rationale", "")),
                    "files": list(proposal.get("impacted_assets") or []),
                    "note": (
                        f"sarathi proposal {proposal_id} (source {proposal.get('source')}"
                        + (f", task class {task_class})" if task_class else ")")
                    ),
                }
                try:
                    result = self._call_bridge("improvement_record", args)
                except Exception as exc:
                    annotations[proposal_id] = {"error": str(exc)[:300]}
                    continue
                if "unsupported" in result:
                    annotations[proposal_id] = {"error": str(result["unsupported"])}
                    continue
                attempt = result.get("attempt") or {}
                history = list(result.get("history") or [])
                same_change = [
                    h["status"]
                    for h in history
                    if " ".join(str(h.get("what", "")).split()).casefold()
                    == " ".join(args["what"].split()).casefold()
                ]
                annotations[proposal_id] = {
                    "problem_id": result.get("problem_id"),
                    "attempt_id": attempt.get("attempt_id"),
                    "reused": bool(result.get("reused")),
                    "prior_attempts": [
                        {
                            "status": h.get("status"),
                            "what": h.get("what"),
                            "passed": h.get("passed"),
                            "total": h.get("total"),
                            "note": h.get("note"),
                        }
                        for h in history
                    ],
                    # The same change was already tried and ended this way.
                    "previously": sorted(set(same_change) - {"proposed"}),
                }
                entry = registry.setdefault(proposal_id, {})
                entry.update(
                    attempt_id=attempt.get("attempt_id"),
                    problem_id=result.get("problem_id"),
                    policy_file=args["scope"],
                    status=entry.get("status", "proposed"),
                )
                if task_class and not entry.get("task_class"):
                    entry["task_class"] = task_class
            self.registry.save(registry)
        return annotations

    def record_decision(self, decision: dict[str, Any]) -> dict[str, Any] | None:
        """Mirror an accept / reject / rollback decision onto the NCP attempt."""
        status = {
            "accepted": "applied",
            "rejected": "rejected",
            "rolled_back": "rolled_back",
        }.get(str(decision.get("status")))
        proposal_id = str(decision.get("id", ""))
        if status is None or not proposal_id:
            return None
        with self._lock:
            registry = self.registry.load()
            entry = registry.get(proposal_id)
            if not entry or not entry.get("attempt_id"):
                return None  # generated before tracking, or NCP was off then
            fields: dict[str, Any] = {"status": status}
            if status == "applied":
                fields["accepted"] = True
                entry["accepted_at"] = time.time()
                entry.pop("checked_total", None)
            if decision.get("reason"):
                fields["note"] = f"{status}: {decision['reason']}"[:500]
            try:
                result = self._call_bridge(
                    "improvement_update",
                    {"attempt_id": entry["attempt_id"], "fields": fields},
                )
            except Exception as exc:
                return {"error": str(exc)[:300]}
            entry["status"] = status
            self.registry.save(registry)
            return result

    # ── outcomes and the post-accept check ─────────────────────────────────

    def record_task_outcome(
        self,
        *,
        task_id: str,
        task_class: str,
        success: bool,
        weight: float,
        output_tokens: int | None = None,
    ) -> None:
        self.outcome_log.append(
            {
                "task_id": task_id,
                "task_class": task_class,
                "success": bool(success),
                "weight": float(weight),
                "output_tokens": output_tokens,
                "at": time.time(),
            }
        )

    def check_accepted(self, task_class: str) -> list[dict[str, Any]]:
        """Post-accept check of accepted proposals for ``task_class``.

        Returns one verdict per accepted proposal of that class:
        ``pending`` (too few outcomes on either side), ``held`` or
        ``regressed``. Observed numbers are written to the NCP attempt
        whenever the post-accept sample has grown.
        """
        verdicts: list[dict[str, Any]] = []
        with self._lock:
            registry = self.registry.load()
            entries = self.outcome_log.entries(task_class)
            changed = False
            for proposal_id, entry in registry.items():
                if (
                    entry.get("status") != "applied"
                    or entry.get("task_class") != task_class
                ):
                    continue
                accepted_at = float(entry.get("accepted_at") or 0)
                before = [e for e in entries if float(e.get("at", 0)) < accepted_at][
                    -ANCHOR_WINDOW:
                ]
                after = [e for e in entries if float(e.get("at", 0)) >= accepted_at]
                verdict: dict[str, Any] = {
                    "proposal_id": proposal_id,
                    "task_class": task_class,
                    "before": len(before),
                    "after": len(after),
                }
                if len(before) < self.min_outcomes or len(after) < self.min_outcomes:
                    verdict["verdict"] = "pending"
                    verdict["needed"] = self.min_outcomes
                    verdicts.append(verdict)
                    continue
                before_rate, _, _ = _rate(before)
                after_rate, passed, total = _rate(after)
                if before_rate is None or after_rate is None:  # all weights zero
                    verdict["verdict"] = "pending"
                    verdict["needed"] = self.min_outcomes
                    verdicts.append(verdict)
                    continue
                regressed = after_rate < self.gate_ratio * before_rate
                verdict.update(
                    verdict="regressed" if regressed else "held",
                    before_rate=round(before_rate, 4),
                    after_rate=round(after_rate, 4),
                )
                if regressed:
                    verdict["recommendation"] = (
                        f"sarathi proposals --rollback {proposal_id}"
                    )
                verdicts.append(verdict)
                if entry.get("checked_total") == total:
                    continue  # nothing new since the last write
                tokens = [e["output_tokens"] for e in after if e.get("output_tokens")]
                fields: dict[str, Any] = {
                    "passed": passed,
                    "total": total,
                    "anchor_rate": before_rate,
                    "note": (
                        f"post-accept check: success {after_rate:.2f} over {len(after)} "
                        f"{task_class} tasks vs {before_rate:.2f} over {len(before)} before "
                        f"(gate {self.gate_ratio:.2f}x): "
                        + ("regressed, consider rollback" if regressed else "held")
                    ),
                }
                if tokens:
                    fields["mean_output_tokens"] = sum(tokens) / len(tokens)
                try:
                    self._call_bridge(
                        "improvement_update",
                        {"attempt_id": entry["attempt_id"], "fields": fields},
                    )
                except Exception as exc:
                    verdict["error"] = str(exc)[:300]
                    continue
                entry["checked_total"] = total
                changed = True
            if changed:
                self.registry.save(registry)
        return verdicts
