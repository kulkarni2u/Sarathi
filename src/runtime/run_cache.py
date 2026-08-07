"""In-process caches shared by graph nodes within a single task run.

``ContextCompiler`` and ``NCPContextAdapter`` (see ``src/runtime/context.py``,
``src/ncp_adapter/context_adapter.py``) both compile a fresh context pack from
scratch on every phase/node dispatch. Two pieces of that recompilation are
pure waste when repeated across many nodes of the *same* run:

- the repo index (``.sarathi/index/symbols.json``) is read cold from disk on
  every single ``query_repo_index`` call, even though the file doesn't change
  mid-run;
- SYNTHESIZE/JUDGE nodes need their sibling branches' outputs, which are
  already sitting in memory (annotated onto the graph as each node
  completes) but the local (non-NCP) context path has no way to look them up
  by ``pattern_config.source_ids``/``competitor_ids`` without a fresh linear
  scan of every node in the graph.

Both caches below are scoped to one ``TaskGraphExecutor`` instance, i.e. one
task run -- they hold no state that needs to survive a process restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from src.repo_index import _load_symbols, _score_symbols
except ImportError:
    from repo_index import _load_symbols, _score_symbols


class RepoIndexCache:
    """Memoizes the loaded repo-index symbol list per root for one run.

    ``query_repo_index`` re-reads and re-parses ``symbols.json`` on every
    call; this cache reads it once per distinct root and re-scores the
    already-loaded list against each new query, reloading only if the
    index file's mtime has moved since the cached read (i.e. ``sarathi
    index`` ran again mid-session).
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def query(
        self, target_path: str | Path, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        root = Path(target_path).expanduser().resolve()
        key = str(root)
        symbols_path = root / ".sarathi" / "index" / "symbols.json"
        try:
            mtime = symbols_path.stat().st_mtime
        except OSError:
            mtime = -1.0

        cached = self._entries.get(key)
        if cached is None or cached[0] != mtime:
            symbols = _load_symbols(root)
            self._entries[key] = (mtime, symbols)
        else:
            symbols = cached[1]

        return _score_symbols(symbols, query, limit=limit)


class NodeOutputCache:
    """O(1) lookup of a completed graph node's output, by node id.

    Populated as each node finishes (see
    ``TaskGraphExecutor._annotate_node_result``) instead of requiring every
    later context-compile to linear-scan ``graph["nodes"]``. Also the
    mechanism that lets the local ``ContextCompiler`` path surface
    SYNTHESIZE/JUDGE branch outputs (``pattern_config.source_ids`` /
    ``competitor_ids``) the same way the NCP path already does via
    ``_fetch_branch_outputs``/``_fetch_competitor_outputs`` -- just read from
    this in-memory cache instead of an external NCP fetch.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}

    def record(self, node_id: str, node: dict[str, Any]) -> None:
        self._nodes[node_id] = node

    def get(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def outputs_for(self, node_ids: list[str]) -> list[tuple[str, dict[str, Any]]]:
        """Return ``(node_id, agent_output)`` pairs for the ids that are cached."""
        results: list[tuple[str, dict[str, Any]]] = []
        for node_id in node_ids:
            node = self._nodes.get(node_id)
            if node is None:
                continue
            agent_output = node.get("agent_output")
            if isinstance(agent_output, dict):
                results.append((node_id, agent_output))
        return results
