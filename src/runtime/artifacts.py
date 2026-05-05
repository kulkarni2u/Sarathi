"""Artifact persistence for per-phase outputs."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ArtifactStore:
    """Stores structured per-phase artifacts separate from task summaries."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or ".sarathi/artifacts")
        self.root.mkdir(parents=True, exist_ok=True)

    def save_phase_artifacts(
        self,
        task_id: str,
        phase: str,
        artifacts: dict[str, Any],
        evidence: dict[str, Any] | None = None,
    ) -> str | None:
        """Persist artifacts for a phase and return a stable reference."""
        if not artifacts and not evidence:
            return None

        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        phase_slug = phase.lower()
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        path = task_dir / f"{phase_slug}-{timestamp}-{uuid4().hex[:8]}.json"

        payload = {
            "task_id": task_id,
            "phase": phase,
            "saved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "artifacts": artifacts,
            "evidence": evidence or {},
        }
        path.write_text(json.dumps(payload, indent=2))
        return str(path)
