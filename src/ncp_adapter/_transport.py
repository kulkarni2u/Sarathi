"""Shared NCP transport layer — direct subprocess and MCP JSON-RPC."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


_TRANSPORT_TIMEOUT = 30

# `.ncp/run.py` exits 2 for an unknown command. Bridges written by older
# `sarathi init` releases have no `record_outcome` and print no write status.
_UNKNOWN_COMMAND_EXIT = 2


# Chunk headers in NCP's pidgin output (`fetch` and `get_context`) start a line
# with ``chunk:<id>``, optionally followed by space-separated attributes.
_CHUNK_HEADER = re.compile(r"^chunk:(\S+)", re.MULTILINE)


def parse_chunk_ids(text: str) -> list[str]:
    """Return the chunk ids named in NCP pidgin output, in order, de-duplicated."""
    return list(dict.fromkeys(_CHUNK_HEADER.findall(text or "")))


def _mcp_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    """Decode an MCP ``tools/call`` result whose first content item is JSON text."""
    content = (response.get("result") or {}).get("content") or [{}]
    text = content[0].get("text", "") if isinstance(content[0], dict) else ""
    try:
        decoded = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


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
        # Optional NCPOutcomeLedger (see outcome.py), shared by the engine's
        # adapters so a task's outcome credits the chunks it read and wrote.
        self.outcome_ledger: Any = None

    def _note_consumed(self, chunk_ids: list[str]) -> None:
        if self.outcome_ledger is not None and chunk_ids:
            self.outcome_ledger.note_consumed(chunk_ids)

    def _note_produced(self, chunk_id: str) -> None:
        if self.outcome_ledger is not None and chunk_id:
            self.outcome_ledger.note_produced(chunk_id)

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
                [str(self.run_path), "log_cost", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"NCP log_cost failed: {result.stderr.strip() or result.stdout.strip()}"
                )
        else:
            import httpx
            try:
                # NCP's MCP server has no ncp_log_cost; cost is recorded with
                # ncp_post_turn. Explicit empty ack/retrieved lists keep it from
                # acknowledging the session's pending whispers.
                post_turn_args: dict[str, Any] = {
                    "agent_id": agent_id,
                    "role": "sarathi",
                    "task": pipeline_id or "sarathi",
                    "slot": "dispatch",
                    "intent": "log_cost",
                    "turn_id": args["turn_id"],
                    "result_summary": f"sarathi dispatch cost ({model})",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "ack_whisper_ids": [],
                    "retrieved_chunk_ids": [],
                }
                if pipeline_id is not None:
                    post_turn_args["pipeline_id"] = pipeline_id
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "ncp_post_turn",
                        "arguments": post_turn_args,
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
        """Call NCP write_memory via direct API or MCP.

        Sarathi names the chunk itself so the task's outcome can credit it,
        but only once NCP confirms the write (a near-duplicate is skipped and
        creates no chunk).
        """
        chunk_id = f"sub_{uuid.uuid4().hex[:12]}"
        args = {
            "content": content,
            "layer": layer,
            "src": src,
            "written_by": written_by,
            "chunk_id": chunk_id,
        }
        if self.mode == "direct":
            result = subprocess.run(
                [str(self.run_path), "write_memory", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"NCP write_memory failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            # Bridge v2 prints "written:<id>"; older bridges print nothing and
            # ignore chunk_id, so there is no id to credit.
            if f"written:{chunk_id}" in (result.stdout or ""):
                self._note_produced(chunk_id)
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
                written = _mcp_tool_result(result)
                if written.get("written") and written.get("chunk_id"):
                    self._note_produced(str(written["chunk_id"]))
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                raise RuntimeError(f"NCP MCP write_memory failed: {e}") from e

    def _call_fetch(self, query: str, k: int = 3) -> list[str]:
        """Call NCP fetch via direct API or MCP."""
        args = {"query": query, "k": k}
        if self.mode == "direct":
            result = subprocess.run(
                [str(self.run_path), "fetch", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode != 0:
                return []
            chunks = self._parse_fetch_output(result.stdout)
            self._note_consumed(parse_chunk_ids("\n".join(chunks)))
            return chunks
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
                # ncp_fetch returns {"result": "<pidgin chunk blocks>"}.
                encoded = _mcp_tool_result(result).get("result", "")
                chunks = self._parse_fetch_output(encoded if isinstance(encoded, str) else "")
                self._note_consumed(parse_chunk_ids("\n".join(chunks)))
                return chunks
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
                return []

    # ------------------------------------------------------------------
    # Whispers: targeted, pipeline-scoped signals between graph nodes
    # ------------------------------------------------------------------

    def _run_bridge_json(self, command: str, args: dict[str, Any]) -> Any:
        """Run a JSON-printing bridge command; None when the bridge predates it."""
        result = subprocess.run(
            [str(self.run_path), command, json.dumps(args)],
            capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
        )
        if result.returncode == _UNKNOWN_COMMAND_EXIT and "unknown command" in result.stderr:
            return None
        if result.returncode != 0:
            raise RuntimeError(
                f"NCP {command} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return json.loads(result.stdout or "null")

    def _call_emit_whisper(
        self,
        *,
        from_agent: str,
        target: str,
        payload: str,
        pipeline_id: str | None,
        whisper_type: str = "nudge",
        confidence: float = 0.9,
    ) -> str | None:
        """Queue a whisper for ``target`` in ``pipeline_id``; return its id."""
        if self.mode == "direct":
            result = self._run_bridge_json(
                "emit_whisper",
                {
                    "from_agent": from_agent,
                    "target": target,
                    "whisper_type": whisper_type,
                    "payload": payload,
                    "confidence": confidence,
                    "pipeline_id": pipeline_id,
                },
            )
            if result is None:
                raise RuntimeError(".ncp/run.py has no emit_whisper; re-run `sarathi init`")
            return result.get("whisper_id") if isinstance(result, dict) else None

        import httpx
        arguments: dict[str, Any] = {
            "from": from_agent,
            "target": target,
            "type": whisper_type,
            "payload": payload,
            "confidence": confidence,
        }
        if pipeline_id is not None:
            arguments["pipeline_id"] = pipeline_id
        try:
            resp = httpx.post(
                self.endpoint,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "ncp_emit_whisper", "arguments": arguments},
                    "id": 1,
                },
                timeout=_TRANSPORT_TIMEOUT,
            )
            resp.raise_for_status()
            response = resp.json()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"NCP MCP whisper emit failed: {e}") from e
        if "error" in response:
            raise RuntimeError(f"NCP MCP whisper emit failed: {response['error']}")
        return _mcp_tool_result(response).get("whisper_id")

    def _call_peek_whispers(
        self, *, agent_id: str, pipeline_id: str | None, max_items: int = 3
    ) -> list[dict[str, Any]]:
        """Whispers queued for ``agent_id`` in ``pipeline_id``, not consumed.

        Only real, targeted whispers are returned -- never search results.
        MCP mode returns none: NCP's MCP surface delivers whisper payloads
        only inside ``ncp_get_context``'s display block.
        """
        if self.mode != "direct":
            return []
        try:
            result = self._run_bridge_json(
                "peek_whispers",
                {"agent_id": agent_id, "pipeline_id": pipeline_id, "max_items": max_items},
            )
        except (RuntimeError, json.JSONDecodeError, subprocess.SubprocessError, OSError):
            return []
        return [w for w in result if isinstance(w, dict)] if isinstance(result, list) else []

    def _call_ack_whispers(self, *, agent_id: str, whisper_ids: list[str]) -> int:
        """Acknowledge (delete) delivered whispers; 0 when unsupported."""
        if self.mode != "direct" or not whisper_ids:
            return 0
        result = self._run_bridge_json(
            "ack_whispers", {"agent_id": agent_id, "whisper_ids": list(whisper_ids)}
        )
        return int(result.get("acknowledged", 0)) if isinstance(result, dict) else 0

    def _call_record_outcome(self, args: dict[str, Any]) -> dict[str, Any]:
        """Call NCP record_outcome via direct API or MCP.

        Returns ``{"recorded", "outcome_id", "calibrated"}``, or
        ``{"recorded": False, "unsupported": <reason>}`` when the workspace's
        bridge predates ``record_outcome``.
        """
        if self.mode == "direct":
            result = subprocess.run(
                [str(self.run_path), "record_outcome", json.dumps(args)],
                capture_output=True, text=True, timeout=_TRANSPORT_TIMEOUT,
            )
            if result.returncode == _UNKNOWN_COMMAND_EXIT and "unknown command" in result.stderr:
                return {
                    "recorded": False,
                    "unsupported": ".ncp/run.py has no record_outcome; re-run `sarathi init`",
                }
            if result.returncode != 0:
                raise RuntimeError(
                    f"NCP record_outcome failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            try:
                decoded = json.loads(result.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"NCP record_outcome returned non-JSON: {exc}") from exc
            return decoded if isinstance(decoded, dict) else {}

        import httpx
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "ncp_record_outcome", "arguments": args},
                "id": 1,
            }
            resp = httpx.post(self.endpoint, json=payload, timeout=_TRANSPORT_TIMEOUT)
            resp.raise_for_status()
            response = resp.json()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"NCP MCP record_outcome failed: {e}") from e
        if "error" in response:
            raise RuntimeError(f"NCP MCP record_outcome failed: {response['error']}")
        return _mcp_tool_result(response)

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
