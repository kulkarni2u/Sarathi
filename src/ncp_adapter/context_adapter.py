"""NCPContextAdapter — replaces ContextCompiler with NCP-backed context assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import NCPNotAvailableError
from ._transport import NCPTransportMixin


class NCPContextAdapter(NCPTransportMixin):
    """Adapts Sarathi ContextCompiler calls to NCP ncp_get_context.

    Inherits transport primitives (fetch, write_memory) from NCPTransportMixin
    so typed-node context can pull sibling artifacts and whispers from NCP.
    """

    def __init__(
        self,
        mode: str = "direct",
        endpoint: str = "http://127.0.0.1:4242/mcp",
        run_path: str | Path = ".ncp/run.py",
    ):
        if mode not in ("direct", "mcp"):
            raise ValueError("mode must be 'direct' or 'mcp'")
        super().__init__(mode=mode, endpoint=endpoint, run_path=run_path)

    def check_available(self) -> bool:
        """Validate NCP connectivity. Returns True if reachable."""
        if self.mode == "direct":
            import subprocess
            try:
                result = subprocess.run(
                    [str(self.run_path), "status"],
                    capture_output=True, text=True, timeout=5,
                )
                return result.returncode == 0
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                return False
        else:
            import httpx
            try:
                resp = httpx.get(f"{self.endpoint.replace('/mcp', '')}/healthz", timeout=3)
                return resp.status_code == 200
            except (httpx.ConnectError, httpx.TimeoutException):
                return False

    def compile_task_tracking_context(
        self,
        *,
        task: Mapping[str, Any],
        subtask: Mapping[str, Any],
        evidence_artifacts: Iterable[Mapping[str, Any]] = (),
        review_runs: Iterable[Mapping[str, Any]] = (),
        available_tools: Iterable[str] = (),
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        """Compile a task-tracking ContextPack from NCP context."""
        task_packet = subtask.get("metadata", {}).get("task_packet", {})
        role = subtask.get("metadata", {}).get("role", "Samanvaya")
        task_id = task.get("id", "")

        args = {
            "agent_id": f"s.{role.lower()}",
            "role": "TaskTracking",
            "owns": [],
            "must_not": [],
            "task": task_id,
            "slot": "TaskTracking",
            "intent": f"track_task:{task_id}",
        }
        ctx = self._call_get_context(args)
        return self._map_to_context_pack(ctx, role, "TaskTracking", task_packet, token_budget)

    def compile_graph_node_context(
        self,
        *,
        node: Mapping[str, Any],
        graph: Mapping[str, Any] | None = None,
        phase: str = "Build",
        available_tools: Iterable[str] = (),
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        """Compile a graph-node ContextPack from NCP context."""
        role = node.get("role", "Pravaha")
        node_id = node.get("id", "")
        task_packet = node.get("task_packet", {})

        args = {
            "agent_id": f"s.{role.lower()}",
            "role": role,
            "owns": task_packet.get("review_criteria", []),
            "must_not": [],
            "task": node_id,
            "slot": phase,
            "intent": f"execute_node:{node_id}",
        }
        if token_budget is not None:
            args["token_budget"] = token_budget
        ctx = self._call_get_context(args)
        return self._map_to_context_pack(ctx, role, phase, task_packet, token_budget)

    def compile_typed_node_context(
        self,
        *,
        node: Mapping[str, Any],
        graph: Mapping[str, Any] | None = None,
        phase: str = "Build",
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        """Context pack for a typed workflow-pattern node.

        Starts from the base NCP get_context result and augments it with
        pattern-specific data fetched from NCP memory:

        - SYNTHESIZE  → fetches each source branch's saved output
        - JUDGE       → fetches each competitor's saved output
        - LOOP_GATE   → fetches previous-iteration findings from episodic memory
        - EXECUTE     → polls any whispers targeting this node (e.g. fanout/classify signals)
        """
        node_type = str(node.get("node_type", "execute")).lower()
        pattern_config = dict(node.get("pattern_config", {}))
        node_id = str(node.get("id", ""))

        # Base context via standard NCP get_context
        base = self.compile_graph_node_context(
            node=node, graph=graph, phase=phase, token_budget=token_budget
        )

        additional: list[str] = []

        if node_type == "synthesize":
            additional.extend(self._fetch_branch_outputs(pattern_config.get("source_ids", [])))

        elif node_type == "judge":
            additional.extend(self._fetch_competitor_outputs(pattern_config.get("competitor_ids", [])))

        elif node_type == "loop_gate":
            iteration = int(pattern_config.get("iteration", 1))
            if iteration > 1:
                parent_id = node_id.rsplit("-iter-", 1)[0] if "-iter-" in node_id else node_id
                additional.extend(self._fetch_loop_history(parent_id, max_items=iteration - 1))

        elif node_type == "execute":
            # Only branch nodes (fanout/classify children) receive whispers from a parent
            if "-branch-" in node_id:
                additional.extend(self._fetch_node_whispers(node_id))

        if additional:
            ai = base.setdefault("agent_input", {})
            prior = list(ai.get("prior_findings", []))
            prior.extend(additional[:6])
            ai["prior_findings"] = prior[:12]
            base.setdefault("compilation", {})["pattern_context_fetched"] = node_type

        return base

    # ------------------------------------------------------------------
    # Pattern-specific NCP fetch helpers
    # ------------------------------------------------------------------

    def _fetch_branch_outputs(self, source_ids: list[str]) -> list[str]:
        """Fetch saved outputs for each source branch (SYNTHESIZE context)."""
        findings: list[str] = []
        for src_id in source_ids:
            chunks = self._call_fetch(f"sarathi_node:{src_id}", k=2)
            for chunk in chunks:
                text = self._reconstruct_chunk_text(chunk).strip()
                if text:
                    findings.append(f"Branch {src_id}: {text[:400]}")
        return findings

    def _fetch_competitor_outputs(self, competitor_ids: list[str]) -> list[str]:
        """Fetch saved outputs for competing nodes (JUDGE context)."""
        findings: list[str] = []
        for cid in competitor_ids:
            chunks = self._call_fetch(f"sarathi_node:{cid}", k=2)
            for chunk in chunks:
                text = self._reconstruct_chunk_text(chunk).strip()
                if text:
                    findings.append(f"Competitor {cid}: {text[:400]}")
        return findings

    def _fetch_loop_history(self, parent_id: str, max_items: int) -> list[str]:
        """Fetch previous-iteration findings for a loop gate (LOOP_GATE context)."""
        chunks = self._call_fetch(f"sarathi_loop:{parent_id}", k=max_items)
        findings: list[str] = []
        for chunk in chunks:
            text = self._reconstruct_chunk_text(chunk).strip()
            if text:
                findings.append(f"Previous finding: {text[:400]}")
        return findings

    def _fetch_node_whispers(self, node_id: str) -> list[str]:
        """Poll NCP for whispers addressed to this node (fanout/classify context)."""
        chunks = self._call_fetch(f"whisper:s.{node_id}", k=3)
        findings: list[str] = []
        for chunk in chunks:
            text = self._reconstruct_chunk_text(chunk).strip()
            if text:
                try:
                    obj = json.loads(text)
                    findings.append(f"Signal: {json.dumps(obj)[:400]}")
                except json.JSONDecodeError:
                    findings.append(f"Signal: {text[:400]}")
        return findings

    # ------------------------------------------------------------------
    # Internal transport
    # ------------------------------------------------------------------

    def _call_get_context(self, args: dict) -> str:
        """Call NCP get_context via direct API or MCP."""
        import subprocess, sys
        if self.mode == "direct":
            import json as _json
            result = subprocess.run(
                [str(self.run_path), "get_context", _json.dumps(args)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise NCPNotAvailableError(f"NCP get_context failed: {result.stderr}")
            return result.stdout
        else:
            import httpx, json as _json
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "ncp_get_context", "arguments": args},
                    "id": 1,
                }
                resp = httpx.post(self.endpoint, json=payload, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                return result.get("result", {}).get("content", [{}])[0].get("text", "")
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                raise NCPNotAvailableError(f"NCP MCP get_context failed: {e}") from e

    def _map_to_context_pack(
        self,
        ctx_text: str,
        role: str,
        phase: str,
        task_packet: dict,
        token_budget: int | None,
    ) -> dict[str, Any]:
        """Map NCP pidgin output to ContextPack-like dict."""
        lines = ctx_text.strip().split("\n")
        conscious_section = {}
        subconscious_chunks = []

        current_section = None
        for line in lines:
            if line.startswith("[NCP:BUDGET]"):
                current_section = "budget"
                continue
            elif line.startswith("[NCP:CONSCIOUS]"):
                current_section = "conscious"
                continue
            elif line.startswith("[NCP:SUBCONSCIOUS]"):
                current_section = "subconscious"
                continue
            elif line.startswith("[NCP:WHISPERS]"):
                break

            if current_section == "conscious" and ":" in line:
                key, value = line.split(":", 1)
                conscious_section[key.strip()] = value.strip()
            elif current_section == "subconscious" and line.strip():
                subconscious_chunks.append(line.strip())

        prior_findings = []
        for chunk in subconscious_chunks:
            content = chunk.split("  ", 1)[-1] if "  " in chunk else chunk
            prior_findings.append(content[:200])

        objective = task_packet.get("goal", conscious_section.get("task", ""))
        constraints = task_packet.get("review_criteria", [])
        acceptance_criteria = task_packet.get("acceptance_criteria", [])

        return {
            "role": role,
            "phase": phase,
            "summary": f"NCP context for {role}/{phase}",
            "agent_input": {
                "objective": objective,
                "constraints": list(constraints) if isinstance(constraints, list) else [str(constraints)],
                "acceptance_criteria": list(acceptance_criteria) if isinstance(acceptance_criteria, list) else [],
                "relevant_files": [],
                "prior_findings": prior_findings[:8],
                "available_tools": [],
                "token_budget": token_budget if token_budget is not None else 3000,
            },
            "source_artifacts": [],
            "compilation": {
                "ncp_mode": self.mode,
                "ncp_conscious": conscious_section,
            },
        }

