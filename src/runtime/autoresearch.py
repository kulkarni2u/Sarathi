"""Append-only autoresearch experiment records."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class EvidenceTier(str, Enum):
    """Evidence tiers for an autoresearch experiment."""

    MINE = "MINE"
    MICRO = "MICRO"
    FULL = "FULL"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AutoresearchEvidence:
    """Evidence attached to a pre-registered autoresearch experiment."""

    evidence_id: str
    experiment_id: str
    summary: str
    uri: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    recorded_by: str = "sarathi"
    recorded_at: str = field(default_factory=_utcnow)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": self.evidence_id,
            "experiment_id": self.experiment_id,
            "summary": self.summary,
            "uri": self.uri,
            "metrics": self.metrics,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at,
        }


@dataclass
class AutoresearchVerdict:
    """Final or interim verdict for an autoresearch experiment."""

    verdict: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    recorded_by: str = "sarathi"
    recorded_at: str = field(default_factory=_utcnow)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "evidence_refs": self.evidence_refs,
            "cost_usd": self.cost_usd,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at,
        }


@dataclass
class AutoresearchExperiment:
    """Pre-registered hypothesis plus evidence and verdict."""

    experiment_id: str
    hypothesis: str
    prediction: str
    tier: EvidenceTier
    method: str
    quality_gate: str
    created_by: str = "sarathi"
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    status: str = "registered"
    evidence: list[AutoresearchEvidence] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    verdict: AutoresearchVerdict | None = None

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "prediction": self.prediction,
            "tier": self.tier.value,
            "method": self.method,
            "quality_gate": self.quality_gate,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "evidence": [item.to_artifact() for item in self.evidence],
            "evidence_refs": list(self.evidence_refs),
            "verdict": self.verdict.to_artifact() if self.verdict else None,
        }


class AutoresearchStore:
    """Append-only JSONL store for autoresearch experiment logs."""

    def __init__(self, base_dir: str | Path = ".sarathi") -> None:
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / "autoresearch.jsonl"
        self._experiments = self._load()

    def register(
        self,
        *,
        hypothesis: str,
        prediction: str,
        tier: EvidenceTier | str,
        method: str,
        quality_gate: str,
        created_by: str = "sarathi",
    ) -> AutoresearchExperiment:
        experiment = AutoresearchExperiment(
            experiment_id=_new_id("exp"),
            hypothesis=hypothesis,
            prediction=prediction,
            tier=_tier(tier),
            method=method,
            quality_gate=quality_gate,
            created_by=created_by,
        )
        self._experiments[experiment.experiment_id] = experiment
        self._append("registered", experiment.to_artifact())
        return experiment

    def append_evidence(
        self,
        experiment_id: str,
        *,
        summary: str,
        uri: str | None = None,
        metrics: dict[str, Any] | None = None,
        recorded_by: str = "sarathi",
    ) -> AutoresearchEvidence:
        experiment = self._require(experiment_id)
        evidence = AutoresearchEvidence(
            evidence_id=_new_id("ev"),
            experiment_id=experiment.experiment_id,
            summary=summary,
            uri=uri,
            metrics=metrics or {},
            recorded_by=recorded_by,
        )
        experiment.evidence.append(evidence)
        experiment.updated_at = evidence.recorded_at
        if evidence.evidence_id not in experiment.evidence_refs:
            experiment.evidence_refs.append(evidence.evidence_id)
        self._append("evidence", evidence.to_artifact())
        return evidence

    def record_verdict(
        self,
        experiment_id: str,
        *,
        verdict: str,
        summary: str,
        evidence_refs: list[str] | None = None,
        cost_usd: float = 0.0,
        recorded_by: str = "sarathi",
    ) -> AutoresearchVerdict:
        experiment = self._require(experiment_id)
        resolved_evidence_refs = (
            list(evidence_refs)
            if evidence_refs is not None
            else list(experiment.evidence_refs)
        )
        result = AutoresearchVerdict(
            verdict=verdict,
            summary=summary,
            evidence_refs=resolved_evidence_refs,
            cost_usd=cost_usd,
            recorded_by=recorded_by,
        )
        experiment.verdict = result
        experiment.status = verdict
        experiment.updated_at = result.recorded_at
        experiment.evidence_refs = list(result.evidence_refs)
        self._append(
            "verdict",
            {"experiment_id": experiment.experiment_id, **result.to_artifact()},
        )
        return result

    def get(self, experiment_id: str) -> AutoresearchExperiment | None:
        return self._experiments.get(experiment_id)

    def list(self, *, status: str | None = None) -> list[AutoresearchExperiment]:
        records = sorted(self._experiments.values(), key=lambda item: item.created_at)
        if status is not None:
            records = [item for item in records if item.status == status]
        return records

    def _require(self, experiment_id: str) -> AutoresearchExperiment:
        experiment = self.get(experiment_id)
        if experiment is None:
            raise KeyError(f"Unknown autoresearch experiment: {experiment_id}")
        return experiment

    def _append(self, event: str, payload: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        record = {"event": event, "payload": payload, "recorded_at": _utcnow()}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _load(self) -> dict[str, AutoresearchExperiment]:
        experiments: dict[str, AutoresearchExperiment] = {}
        if not self.path.exists():
            return experiments
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            _apply_event(experiments, event.get("event"), event.get("payload") or {})
        return experiments


def _apply_event(experiments: dict[str, AutoresearchExperiment], event: str, payload: dict[str, Any]) -> None:
    if event == "registered":
        experiment_id = str(payload["id"])
        experiments[experiment_id] = AutoresearchExperiment(
            experiment_id=experiment_id,
            hypothesis=str(payload["hypothesis"]),
            prediction=str(payload["prediction"]),
            tier=_tier(payload["tier"]),
            method=str(payload["method"]),
            quality_gate=str(payload["quality_gate"]),
            created_by=str(payload.get("created_by") or "sarathi"),
            created_at=str(payload.get("created_at") or _utcnow()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _utcnow()),
            status=str(payload.get("status") or "registered"),
        )
    elif event == "evidence":
        experiment = experiments.get(str(payload.get("experiment_id")))
        if experiment is None:
            return
        evidence = AutoresearchEvidence(
            evidence_id=str(payload["id"]),
            experiment_id=experiment.experiment_id,
            summary=str(payload["summary"]),
            uri=payload.get("uri"),
            metrics=dict(payload.get("metrics") or {}),
            recorded_by=str(payload.get("recorded_by") or "sarathi"),
            recorded_at=str(payload.get("recorded_at") or _utcnow()),
        )
        experiment.evidence.append(evidence)
        experiment.updated_at = evidence.recorded_at
        if evidence.evidence_id not in experiment.evidence_refs:
            experiment.evidence_refs.append(evidence.evidence_id)
    elif event == "verdict":
        experiment = experiments.get(str(payload.get("experiment_id")))
        if experiment is None:
            return
        verdict = AutoresearchVerdict(
            verdict=str(payload["verdict"]),
            summary=str(payload["summary"]),
            evidence_refs=list(payload.get("evidence_refs") or []),
            cost_usd=float(payload.get("cost_usd") or 0.0),
            recorded_by=str(payload.get("recorded_by") or "sarathi"),
            recorded_at=str(payload.get("recorded_at") or _utcnow()),
        )
        experiment.verdict = verdict
        experiment.status = verdict.verdict
        experiment.evidence_refs = list(verdict.evidence_refs)
        experiment.updated_at = verdict.recorded_at


def _tier(value: EvidenceTier | str) -> EvidenceTier:
    if isinstance(value, EvidenceTier):
        return value
    return EvidenceTier(str(value).strip().upper())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
