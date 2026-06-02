"""NCPPersistenceAdapter — replaces Sarathi persistence with NCP-backed memory."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Mapping

from ._transport import NCPTransportMixin


def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """Access a field from a Mapping or object (supports subscript and getattr)."""
    try:
        return obj[field]
    except (TypeError, KeyError, IndexError):
        return getattr(obj, field, default)


def _to_jsonable(value: Any) -> Any:
    """Recursively convert enums, dataclasses, and non-serializable types to JSON-safe values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(dataclasses.asdict(value))
    if hasattr(value, "value") and not isinstance(value, (dict, list)):
        return value.value
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


class NCPPersistenceAdapter(NCPTransportMixin):
    """Adapts Sarathi persistence calls to NCP write_memory and fetch."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    _NCP_MAX_CONTENT = 2000

    def save_task(self, task: Mapping[str, Any]) -> None:
        """Serialize a task and persist it via NCP write_memory."""
        task_id = _get_field(task, "task_id")
        if not task_id:
            raise ValueError("task must have a non-empty 'task_id' field")
        phase_results = _to_jsonable(list(_get_field(task, "phase_results", [])))
        # Compact phase_results to just outcome summaries so content stays within NCP limit.
        compact_results = [
            {"phase": r.get("phase"), "outcome": r.get("outcome")}
            if isinstance(r, dict) else r
            for r in phase_results
        ]
        content = json.dumps({
            "_sarathi_type": "TaskContext",
            "task_id": task_id,
            "description": _get_field(task, "description"),
            "complexity": _to_jsonable(_get_field(task, "complexity")),
            "current_phase": _to_jsonable(_get_field(task, "current_phase")),
            "phase_results": compact_results,
        })
        if len(content) > self._NCP_MAX_CONTENT:
            content = content[: self._NCP_MAX_CONTENT - 3] + "..."
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
            "phase": _to_jsonable(phase),
            "status": _to_jsonable(status),
        })
        self._call_write_memory(
            content, "reasoning_trace", "tool_result", f"sarathi.engine.{_get_field(task, 'task_id')}",
        )

    def log_cost(
        self,
        usage_record: dict[str, Any] | None = None,
        *,
        agent_id: str = "sarathi",
        model: str = "unknown",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        pipeline_id: str | None = None,
        latency_ms: int = 0,
    ) -> None:
        """Log dispatch cost to NCP's cost log.

        Accepts a usage_record dict (from ``UsageRecord.to_artifact()``) or
        explicit keyword arguments. When *usage_record* is provided its values
        take precedence over explicit args.
        """
        if usage_record is not None:
            agent_id = usage_record.get("provider_id", agent_id) or agent_id
            input_tokens = int(usage_record.get("input_tokens", input_tokens) or input_tokens)
            output_tokens = int(usage_record.get("output_tokens", output_tokens) or output_tokens)

        if input_tokens == 0 and output_tokens == 0:
            return

        try:
            self._call_log_cost(
                agent_id=agent_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                pipeline_id=pipeline_id,
                latency_ms=latency_ms,
            )
        except RuntimeError:
            pass

    def save_learning(self, learning_record: Mapping[str, Any]) -> None:
        """Persist a learning record to semantic memory."""
        content = json.dumps(_to_jsonable(dict(learning_record)))
        self._call_write_memory(
            content, "semantic", "synthesis", "sarathi.engine.learning",
        )


