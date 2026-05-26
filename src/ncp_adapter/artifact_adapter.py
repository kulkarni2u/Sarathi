"""NCPArtifactAdapter — persists and retrieves phase-level artifacts via NCP."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


_TRANSPORT_TIMEOUT = 30


class NCPArtifactAdapter:
    """Stores and loads structured phase artifacts through NCP write_memory/fetch."""

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
