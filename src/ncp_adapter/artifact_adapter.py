"""NCPArtifactAdapter — persists and retrieves phase-level artifacts via NCP."""

from __future__ import annotations

import json
from typing import Any

from ncp_adapter._transport import NCPTransportMixin


class NCPArtifactAdapter(NCPTransportMixin):
    """Stores and loads structured phase artifacts through NCP write_memory/fetch."""

    def save_phase_artifacts(
        self, task_id: str, phase: str, artifacts: dict[str, Any], evidence: Any = None,
    ) -> str | None:
        """Persist phase-level artifacts and return a resource URI.

        Returns None when both *artifacts* and *evidence* are empty/falsy.
        """
        if not artifacts and not evidence:
            return None
        content = json.dumps({
            "_sarathi_type": "PhaseArtifact",
            "task_id": task_id,
            "phase": phase,
            "artifacts": artifacts,
            "evidence": evidence,
        })
        self._call_write_memory(content, "semantic", "tool_result", f"sarathi.{task_id}.{phase}")
        return f"ncp://{task_id}/{phase}"

    def load_artifacts(self, task_id: str, phase: str) -> list[dict[str, Any]]:
        """Load artifact dicts for a given task + phase."""
        chunks = self._call_fetch(f"sarathi_task:{task_id} sarathi_phase:{phase}", k=5)
        results: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_text = self._reconstruct_chunk_text(chunk)
            try:
                obj = json.loads(chunk_text)
            except (json.JSONDecodeError, KeyError):
                continue
            if obj.get("_sarathi_type") == "PhaseArtifact":
                results.append(obj.get("artifacts", {}))
        return results

    def list_phases(self, task_id: str) -> list[str]:
        """Return sorted unique phase names for a task."""
        chunks = self._call_fetch(f"sarathi_task:{task_id}", k=20)
        seen: set[str] = set()
        phases: list[str] = []
        for chunk in chunks:
            chunk_text = self._reconstruct_chunk_text(chunk)
            try:
                obj = json.loads(chunk_text)
            except (json.JSONDecodeError, KeyError):
                continue
            if obj.get("_sarathi_type") == "PhaseArtifact":
                phase = obj.get("phase")
                if phase and phase not in seen:
                    seen.add(phase)
                    phases.append(phase)
        return phases


