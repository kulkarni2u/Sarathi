"""Shared NCP transport layer — direct subprocess and MCP JSON-RPC."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_TRANSPORT_TIMEOUT = 30


class NCPTransportMixin:
    """Mixin providing NCP write_memory / fetch / log_cost transport methods.

    Subclasses must set ``self.mode`` (“direct” | “mcp”), ``self.endpoint``,
    and ``self.run_path`` (``Path``).
    """

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
    # Public transport
    # ------------------------------------------------------------------

    def _call_log_cost(
        self,
        *,
        agent_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        pipeline_id: str | None = None,
        latency_ms: int = 0,
    ) -> None:
        """Call NCP log_cost via direct API or MCP."""
        import uuid
        args = {
            "turn_id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
        }
        if pipeline_id is not None:
            args["pipeline_id"] = pipeline_id

        if self.mode == "direct":
            result = subprocess.run(
                [sys.executable, str(self.run_path), "log_cost", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"NCP log_cost failed: {result.stderr.strip() or result.stdout.strip()}"
                )
        else:
            import httpx
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "ncp_log_cost",
                        "arguments": args,
                    },
                    "id": 1,
                }
                resp = httpx.post(self.endpoint, json=payload, timeout=_TRANSPORT_TIMEOUT)
                resp.raise_for_status()
                result = resp.json()
                if "error" in result:
                    raise RuntimeError(f"NCP MCP log_cost failed: {result['error']}")
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                raise RuntimeError(f"NCP MCP log_cost failed: {e}") from e

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
