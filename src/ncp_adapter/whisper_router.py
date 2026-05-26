"""NCPWhisperRouter — optional cross-phase signaling via NCP whispers."""

from __future__ import annotations

import json
from typing import Any

from ncp_adapter._transport import NCPTransportMixin


_EMIT_TIMEOUT = 30


class NCPWhisperRouter(NCPTransportMixin):
    """Emits and polls NCP whispers for cross-phase agent coordination."""

    def emit(
        self,
        from_agent: str,
        target: str,
        whisper_type: str,
        payload: str,
        confidence: float = 0.90,
    ) -> None:
        """Emit a whisper signal to another agent."""
        if len(payload) > 600:
            raise ValueError("payload must be <= 600 characters")

        if self.mode == "direct":
            self._call_write_memory(payload, "reasoning_trace", "agent_inferred", from_agent)
        else:
            import httpx
            payload_rpc = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "ncp_emit_whisper",
                    "arguments": {
                        "from": from_agent,
                        "target": target,
                        "type": whisper_type,
                        "payload": payload,
                        "confidence": confidence,
                    },
                },
                "id": 1,
            }
            try:
                resp = httpx.post(self.endpoint, json=payload_rpc, timeout=_EMIT_TIMEOUT)
                resp.raise_for_status()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                raise RuntimeError(f"NCP MCP whisper emit failed: {e}") from e

    def poll(self, agent_id: str, max_items: int = 3) -> list[dict[str, Any]]:
        """Poll for whispers targeting this agent.

        Returns a list of parsed dicts (or empty list on fetch failure).
        """
        chunks = self._call_fetch(f"whisper:{agent_id}", k=max_items)
        results: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_text = self._reconstruct_chunk_text(chunk)
            try:
                results.append(json.loads(chunk_text))
            except (json.JSONDecodeError, KeyError):
                continue
        return results
