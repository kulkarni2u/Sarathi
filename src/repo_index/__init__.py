"""Deterministic local repo symbol index for Sarathi workspaces.

Builds a lightweight, offline "where is X defined" index -- similar to an
IDE's symbol index -- so dispatched agents can be pointed straight at
relevant files/lines instead of re-discovering the codebase with Glob/Grep
on every phase. Persisted under ``.sarathi/index`` and incremental: only
files whose mtime+size changed since the last build are re-parsed.

Python files are parsed with ``ast`` for accurate function/class/method
symbols. Other languages get best-effort regex extraction -- good enough to
point an agent at a file:line, not a substitute for real language tooling.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Mapping

_SKIP_DIRS = {
    ".git", ".sarathi", ".ncp", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", ".pytest_cache", ".mypy_cache",
}

_INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
    ".java", ".rb", ".php", ".cs",
}

# Best-effort top-level symbol extraction for non-Python languages: keyword-
# anchored regexes matched line-by-line, not a real parser.
_REGEX_RULES: list[tuple[frozenset[str], str, re.Pattern[str]]] = [
    (frozenset({".js", ".jsx", ".ts", ".tsx"}), "function",
     re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
    (frozenset({".js", ".jsx", ".ts", ".tsx"}), "class",
     re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
    (frozenset({".go"}), "function",
     re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),
    (frozenset({".go"}), "type",
     re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b")),
    (frozenset({".rs"}), "function",
     re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")),
    (frozenset({".rs"}), "struct",
     re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)")),
    (frozenset({".rs"}), "enum",
     re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)")),
    (frozenset({".java", ".cs"}), "class",
     re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?class\s+([A-Za-z_]\w*)")),
    (frozenset({".rb"}), "class",
     re.compile(r"^\s*class\s+([A-Za-z_]\w*)")),
    (frozenset({".rb"}), "method",
     re.compile(r"^\s*def\s+([A-Za-z_][\w?!=]*)")),
    (frozenset({".php"}), "class",
     re.compile(r"^\s*class\s+([A-Za-z_]\w*)")),
    (frozenset({".php"}), "function",
     re.compile(r"^\s*function\s+([A-Za-z_]\w*)")),
]

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def build_repo_index(target_path: str | Path, *, force: bool = False) -> dict[str, Any]:
    """Create or incrementally refresh the symbol index under ``.sarathi/index``.

    Files whose (mtime, size) fingerprint is unchanged since the last build
    are reused rather than re-parsed. Pass ``force=True`` to reparse everything.
    """
    root = Path(target_path).expanduser().resolve()
    index_dir = root / ".sarathi" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = index_dir / "manifest.json"
    symbols_path = index_dir / "symbols.json"

    manifest: dict[str, dict[str, Any]] = {}
    symbols_by_file: dict[str, list[dict[str, Any]]] = {}
    if not force and manifest_path.exists() and symbols_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
        try:
            for entry in json.loads(symbols_path.read_text(encoding="utf-8")):
                symbols_by_file.setdefault(entry["file"], []).append(entry)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            symbols_by_file = {}

    seen_files: set[str] = set()
    parsed = 0
    reused = 0
    for path in _iter_source_files(root):
        rel = str(path.relative_to(root))
        seen_files.add(rel)
        fingerprint = _file_fingerprint(path)
        if not force and manifest.get(rel) == fingerprint:
            # manifest membership is authoritative even when the file has zero
            # symbols -- symbols_by_file only gains a key for files that
            # produced at least one entry, so checking that dict here would
            # force a pointless reparse of every symbol-free file every run.
            reused += 1
            continue
        if path.suffix.lower() == ".py":
            symbols_by_file[rel] = _python_symbols(path, rel)
        else:
            symbols_by_file[rel] = _regex_symbols(path, rel)
        manifest[rel] = fingerprint
        parsed += 1

    removed_files = [rel for rel in manifest if rel not in seen_files]
    for rel in removed_files:
        manifest.pop(rel, None)
        symbols_by_file.pop(rel, None)

    all_symbols = [
        entry for rel in sorted(symbols_by_file) for entry in symbols_by_file[rel]
    ]
    symbols_path.write_text(
        json.dumps(all_symbols, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return {
        "status": "built",
        "path": str(index_dir),
        "files_indexed": len(seen_files),
        "files_parsed": parsed,
        "files_reused": reused,
        "files_removed": len(removed_files),
        "symbol_count": len(all_symbols),
    }


def _load_symbols(root: Path) -> list[dict[str, Any]]:
    """Read ``.sarathi/index/symbols.json`` under ``root``, or ``[]`` if unavailable."""
    symbols_path = root / ".sarathi" / "index" / "symbols.json"
    if not symbols_path.exists():
        return []
    try:
        symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(symbols, list):
        return []
    return symbols


def _score_symbols(symbols: list[dict[str, Any]], query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Rank already-loaded symbol entries against a free-text query.

    Scores by token overlap against the symbol name (highest weight), its
    docstring first line, and its file path. Returns the compact symbol
    entries only -- callers format them (see ``format_symbol_hint``).
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        name_tokens = set(_tokenize(str(entry.get("name", ""))))
        doc_tokens = set(_tokenize(str(entry.get("doc", ""))))
        file_tokens = set(_tokenize(str(entry.get("file", ""))))
        score = 0
        for token in query_tokens:
            if token in name_tokens:
                score += 3
            elif token in doc_tokens:
                score += 2
            elif token in file_tokens:
                score += 1
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _score, entry in scored[:limit]]


def query_repo_index(target_path: str | Path, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Rank indexed symbols against a free-text query.

    Reads and scores ``.sarathi/index/symbols.json`` fresh on every call. For
    repeated queries against the same root within one run (e.g. one query per
    phase/graph node), prefer ``runtime.run_cache.RepoIndexCache`` instead,
    which caches the loaded symbol list and only re-reads it when the index
    file's mtime changes.
    """
    root = Path(target_path).expanduser().resolve()
    return _score_symbols(_load_symbols(root), query, limit=limit)


def check_repo_index(target_path: str | Path) -> dict[str, Any]:
    root = Path(target_path).expanduser().resolve()
    index_dir = root / ".sarathi" / "index"
    symbols_path = index_dir / "symbols.json"
    return {
        "ok": symbols_path.exists(),
        "path": str(index_dir),
    }


def index_summary(target_path: str | Path) -> dict[str, Any]:
    """Quick counts for CLI display: total symbols and a breakdown by kind."""
    root = Path(target_path).expanduser().resolve()
    symbols_path = root / ".sarathi" / "index" / "symbols.json"
    if not symbols_path.exists():
        return {"symbol_count": 0, "file_count": 0, "by_kind": {}}
    try:
        symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"symbol_count": 0, "file_count": 0, "by_kind": {}}
    by_kind: dict[str, int] = {}
    files: set[str] = set()
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        files.add(str(entry.get("file", "")))
    return {"symbol_count": len(symbols), "file_count": len(files), "by_kind": by_kind}


def format_symbol_hint(entry: Mapping[str, Any]) -> str:
    """Render a symbol entry as a compact "file:line name (kind)" hint."""
    return f"{entry.get('file')}:{entry.get('line')} {entry.get('name')} ({entry.get('kind')})"


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in _INDEXABLE_EXTENSIONS:
            continue
        yield path


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _WORD_RE.findall(text) if len(tok) > 2]


def _python_symbols(path: Path, rel: str) -> list[dict[str, Any]]:
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, ValueError, OSError, RecursionError):
        return []

    symbols: list[dict[str, Any]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}" if prefix else child.name
                doc = ast.get_docstring(child) or ""
                symbols.append({
                    "file": rel,
                    "name": name,
                    "kind": "method" if prefix else "function",
                    "line": child.lineno,
                    "doc": doc.splitlines()[0][:160] if doc else "",
                })
                visit(child, prefix=f"{name}.")
            elif isinstance(child, ast.ClassDef):
                doc = ast.get_docstring(child) or ""
                symbols.append({
                    "file": rel,
                    "name": child.name,
                    "kind": "class",
                    "line": child.lineno,
                    "doc": doc.splitlines()[0][:160] if doc else "",
                })
                visit(child, prefix=f"{child.name}.")
            else:
                visit(child, prefix=prefix)

    visit(tree, prefix="")
    return symbols


def _regex_symbols(path: Path, rel: str) -> list[dict[str, Any]]:
    ext = path.suffix.lower()
    rules = [(kind, pattern) for exts, kind, pattern in _REGEX_RULES if ext in exts]
    if not rules:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    symbols: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        for kind, pattern in rules:
            match = pattern.match(line)
            if match:
                symbols.append({
                    "file": rel,
                    "name": match.group(1),
                    "kind": kind,
                    "line": lineno,
                    "doc": "",
                })
    return symbols
