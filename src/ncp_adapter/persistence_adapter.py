"""NCPPersistenceAdapter — replaces Sarathi persistence with NCP-backed memory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """Access a field from a Mapping or object (supports subscript and getattr)."""
    try:
        return obj[field]
    except (TypeError, KeyError, IndexError):
        return getattr(obj, field, default)


_TRANSPORT_TIMEOUT = 30


class NCPPersistenceAdapter:
    """Adapts Sarathi persistence calls to NCP write_memory and fetch."""

    def __init__(
        self,
        mode: str = "direct",
        endpoint: str = "http://127.0.0.1:4242/mcp",
        run_path: str | Path = ".ncp/run.py",
    ):
        if mode not in ("direct", "mcp"):
            raise ValueError("mode must be 'direct' or 'mcp'")
        self.mode = mode
        self.endpoint = endpoint
        self.run_path = Path(run_path)

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

    # ------------------------------------------------------------------
    # Internal transport
    # ------------------------------------------------------------------

    def _call_write_memory(
        self, content: str, layer: str, src: str, written_by: str,
    ) -> None:
        """Call NCP write_memory via direct API or MCP."""
        args = {
            "content": content,
            "layer": layer,
            "src": src,
            "written_by": written_by,
        }
        if self.mode == "direct":
            result = subprocess.run(
                [sys.executable, str(self.run_path), "write_memory", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"NCP write_memory failed: {result.stderr.strip() or result.stdout.strip()}"
                )
        else:
            import httpx
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "ncp_write_memory",
                        "arguments": args,
                    },
                    "id": 1,
                }
                resp = httpx.post(self.endpoint, json=payload, timeout=_TRANSPORT_TIMEOUT)
                resp.raise_for_status()
                result = resp.json()
                if "error" in result:
                    raise RuntimeError(f"NCP MCP write_memory failed: {result['error']}")
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                raise RuntimeError(f"NCP MCP write_memory failed: {e}") from e

    def _call_fetch(self, query: str, k: int = 3) -> list[str]:
        """Call NCP fetch via direct API or MCP."""
        args = {"query": query, "k": k}
        if self.mode == "direct":
            result = subprocess.run(
                [sys.executable, str(self.run_path), "fetch", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                return []
            return self._parse_fetch_output(result.stdout)
        else:
            import httpx
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "ncp_fetch",
                        "arguments": args,
                    },
                    "id": 1,
                }
                resp = httpx.post(self.endpoint, json=payload, timeout=_TRANSPORT_TIMEOUT)
                resp.raise_for_status()
                result = resp.json()
                content_items = (
                    result.get("result", {}).get("content", [])
                )
                return [item.get("text", "") for item in content_items]
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
                return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_fetch_output(stdout: str) -> list[str]:
        """Parse the pidgin fetch output into chunk strings."""
        chunks: list[str] = []
        current: list[str] = []
        for line in stdout.split("\n"):
            if line.startswith("chunk:"):
                if current:
                    chunks.append("\n".join(current))
                current = [line]
            elif line.startswith("  ") and current:
                current.append(line.strip())
        if current:
            chunks.append("\n".join(current))
        return chunks

    @staticmethod
    def _reconstruct_chunk_text(chunk: str) -> str:
        """Strip the leading 'chunk:' prefix line, keeping rest as JSON."""
        lines = chunk.split("\n", 1)
        if len(lines) > 1:
            return lines[1]
        return chunk
