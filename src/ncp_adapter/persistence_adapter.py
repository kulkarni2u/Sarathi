"""NCPPersistenceAdapter — replaces Sarathi persistence with NCP-backed memory."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ._transport import NCPTransportMixin


def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """Access a field from a Mapping or object (supports subscript and getattr)."""
    try:
        return obj[field]
    except (TypeError, KeyError, IndexError):
        return getattr(obj, field, default)


class NCPPersistenceAdapter(NCPTransportMixin):
    """Adapts Sarathi persistence calls to NCP write_memory and fetch."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_task(self, task: Mapping[str, Any]) -> None:
        """Serialize a task and persist it via NCP write_memory."""
        task_id = _get_field(task, "task_id")
        if not task_id:
            raise ValueError("task must have a non-empty 'task_id' field")
        content = json.dumps({
            "_sarathi_type": "TaskContext",
            "task_id": task_id,
            "description": _get_field(task, "description"),
            "complexity": _get_field(task, "complexity"),
            "current_phase": _get_field(task, "current_phase"),
            "phase_results": list(_get_field(task, "phase_results", [])),
        })
        self._call_write_memory(
            content, "episodic", "tool_result", f"sarathi.engine.{task_id}",
        )

    def load_task(self, task_id: str) -> dict | None:
        """Load a previously saved task by ID. Returns None when not found."""
        chunks = self._call_fetch(f"sarathi_task:{task_id}", k=1)
        if not chunks:
            return None
        # Reconstruct the JSON payload from the chunk lines
        chunk_text = self._reconstruct_chunk_text(chunks[0])
        try:
            return json.loads(chunk_text)
        except (json.JSONDecodeError, KeyError):
            return None

    def list_tasks(self) -> list[str]:
        """List all known task IDs."""
        chunks = self._call_fetch("sarathi_task:", k=20)
        task_ids: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            chunk_text = self._reconstruct_chunk_text(chunk)
            try:
                obj = json.loads(chunk_text)
                tid = obj.get("task_id")
                if tid and tid not in seen:
                    seen.add(tid)
                    task_ids.append(tid)
            except (json.JSONDecodeError, KeyError):
                continue
        return task_ids

    def save_phase_log(
        self, task: Mapping[str, Any], phase: str, status: str,
    ) -> None:
        """Persist a phase-log entry for a task."""
        content = json.dumps({
            "task_id": _get_field(task, "task_id"),
            "phase": phase,
            "status": status,
        })
        self._call_write_memory(
            content, "reasoning_trace", "tool_result", f"sarathi.engine.{_get_field(task, 'task_id')}",
        )

    def save_learning(self, learning_record: Mapping[str, Any]) -> None:
        """Persist a learning record to semantic memory."""
        content = json.dumps(learning_record)
        self._call_write_memory(
            content, "semantic", "synthesis", "sarathi.engine.learning",
        )


