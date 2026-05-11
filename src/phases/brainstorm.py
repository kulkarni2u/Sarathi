"""Brainstorm phase — structured provider-driven dialogue driver."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.engine import Phase, PhaseResult, TaskContext


_EVIDENCE_WEIGHTS: dict[str, float] = {
    "alternative_approaches_considered": 0.3,
    "risks_identified": 0.3,
    "success_criteria_defined": 0.2,
    "reversibility_assessed": 0.2,
}

_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "alternative_approaches_considered": ["approach", "option", "alternative", "instead", "versus", "vs"],
    "risks_identified": ["risk", "concern", "caveat", "danger", "break", "regression"],
    "success_criteria_defined": ["success", "goal", "criterion", "criteria", "done when", "acceptance"],
    "reversibility_assessed": ["revert", "rollback", "undo", "reversible", "migration", "backward"],
}


class BrainstormHandler:
    """Handler for the BRAINSTORM phase — drives a structured dialogue session."""

    def __init__(self, policy_pack, dispatcher=None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: "TaskContext", phase: "Phase") -> "PhaseResult":
        from src.engine import PhaseResult

        session = self._get_or_create_session(task)
        self._dispatch_research_agents(task, session)
        result = self._wait_for_approval(task, session)
        coverage = self._check_evidence_coverage(result.get("spec_content") or "")
        confidence = sum(
            _EVIDENCE_WEIGHTS[dim] for dim, covered in coverage.items() if covered
        )

        return PhaseResult(
            phase=phase,
            outcome="pass" if confidence >= 0.9 else "escalate",
            evidence=coverage,
            artifacts={
                "spec_path": result.get("spec_path"),
                "session_id": session.get("id"),
                "task_id": result.get("task_id"),
                "confidence": confidence,
            },
        )

    def _get_or_create_session(self, task: "TaskContext") -> dict[str, Any]:
        existing_id = task.metadata.get("brainstorm_session_id") if task.metadata else None
        if existing_id:
            session = self._get_session(task, existing_id)
            if session and session["status"] == "active":
                return session
        return self._create_session(task)

    def _create_session(self, task: "TaskContext") -> dict[str, Any]:
        import json as _json
        import urllib.request
        base_url = self._base_url(task)
        token = self._token(task)
        payload = _json.dumps({
            "workspace_id": getattr(task, "workspace_id", ""),
            "title": getattr(task, "description", task.task_id)[:80],
            "project_id": (task.metadata or {}).get("project_id"),
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/sessions",
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            return data["data"]["session"]
        except Exception:
            return {"id": "offline", "status": "active", "spec_content": None, "spec_path": None, "task_id": None}

    def _get_session(self, task: "TaskContext", session_id: str) -> dict[str, Any] | None:
        import json as _json
        import urllib.request
        base_url = self._base_url(task)
        token = self._token(task)
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/{session_id}",
            headers={**({"authorization": f"Bearer {token}"} if token else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            return data["data"]["session"]
        except Exception:
            return None

    def _dispatch_research_agents(self, task: "TaskContext", session: dict[str, Any]) -> None:
        if session.get("id") == "offline":
            return
        findings: list[dict[str, Any]] = []
        complexity = getattr(task, "complexity", None)
        complexity_label = complexity.value if complexity else "medium"
        findings.append({
            "agent": "Marga",
            "type": "pattern",
            "summary": f"Task classified as {complexity_label} complexity",
            "refs": [],
        })
        for finding in findings:
            self._post_research(task, session["id"], finding)

    def _post_research(self, task: "TaskContext", session_id: str, finding: dict[str, Any]) -> None:
        import json as _json
        import urllib.request
        base_url = self._base_url(task)
        token = self._token(task)
        payload = _json.dumps(finding).encode()
        req = urllib.request.Request(
            f"{base_url}/api/brainstorm/{session_id}/research",
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    def _wait_for_approval(self, task: "TaskContext", session: dict[str, Any]) -> dict[str, Any]:
        if session.get("id") == "offline":
            return {"spec_content": "", "spec_path": None, "task_id": None}
        timeout_seconds = 3600
        poll_interval = 5
        elapsed = 0
        while elapsed < timeout_seconds:
            current = self._get_session(task, session["id"])
            if current and current["status"] == "approved":
                return current
            time.sleep(poll_interval)
            elapsed += poll_interval
        return {"spec_content": "", "spec_path": None, "task_id": None}

    def _check_evidence_coverage(self, spec: str) -> dict[str, bool]:
        spec_lower = spec.lower()
        return {
            dim: any(kw in spec_lower for kw in keywords)
            for dim, keywords in _EVIDENCE_KEYWORDS.items()
        }

    def _base_url(self, task: "TaskContext") -> str:
        config = getattr(task, "config", {}) or {}
        return str(config.get("service_url", "http://127.0.0.1:8765"))

    def _token(self, task: "TaskContext") -> str | None:
        config = getattr(task, "config", {}) or {}
        return config.get("service_token")
