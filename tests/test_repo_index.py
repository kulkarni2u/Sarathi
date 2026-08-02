"""Tests for src/repo_index -- the offline repo symbol index."""
from __future__ import annotations

import json
from pathlib import Path

from src.repo_index import (
    build_repo_index,
    check_repo_index,
    format_symbol_hint,
    index_summary,
    query_repo_index,
)


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_check_repo_index_missing(tmp_path: Path):
    result = check_repo_index(tmp_path)
    assert result["ok"] is False


def test_build_repo_index_extracts_python_symbols(tmp_path: Path):
    _write(tmp_path, "pkg/widgets.py", '''
class WidgetFactory:
    """Builds widgets."""

    def build(self, kind):
        """Build a widget of the given kind."""
        return kind


def top_level_helper():
    return 1
''')

    result = build_repo_index(tmp_path)

    assert result["status"] == "built"
    assert result["files_indexed"] == 1
    assert result["files_parsed"] == 1
    assert result["symbol_count"] == 3

    symbols_path = tmp_path / ".sarathi" / "index" / "symbols.json"
    symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    names = {entry["name"]: entry for entry in symbols}
    assert names["WidgetFactory"]["kind"] == "class"
    assert names["WidgetFactory.build"]["kind"] == "method"
    assert names["WidgetFactory.build"]["doc"] == "Build a widget of the given kind."
    assert names["top_level_helper"]["kind"] == "function"

    assert check_repo_index(tmp_path)["ok"] is True


def test_build_repo_index_skips_ignored_dirs(tmp_path: Path):
    _write(tmp_path, "node_modules/lib/index.js", "function ignored() {}")
    _write(tmp_path, ".venv/site-packages/mod.py", "def ignored(): pass")
    _write(tmp_path, "src/real.py", "def real_symbol(): pass")

    result = build_repo_index(tmp_path)

    symbols = json.loads((tmp_path / ".sarathi" / "index" / "symbols.json").read_text())
    names = {entry["name"] for entry in symbols}
    assert names == {"real_symbol"}
    assert result["files_indexed"] == 1


def test_build_repo_index_regex_extraction_for_non_python(tmp_path: Path):
    _write(tmp_path, "src/service.ts", "export class UserService {\n}\n\nfunction helper() {}\n")
    _write(tmp_path, "internal/store.go", "type Store struct {\n}\n\nfunc NewStore() *Store {\n\treturn nil\n}\n")

    build_repo_index(tmp_path)

    symbols = json.loads((tmp_path / ".sarathi" / "index" / "symbols.json").read_text())
    by_name = {entry["name"]: entry["kind"] for entry in symbols}
    assert by_name["UserService"] == "class"
    assert by_name["helper"] == "function"
    assert by_name["Store"] == "type"
    assert by_name["NewStore"] == "function"


def test_build_repo_index_incremental_reuses_unchanged_files(tmp_path: Path):
    _write(tmp_path, "a.py", "def a(): pass\n")
    _write(tmp_path, "b.py", "def b(): pass\n")

    first = build_repo_index(tmp_path)
    assert first["files_parsed"] == 2
    assert first["files_reused"] == 0

    second = build_repo_index(tmp_path)
    assert second["files_parsed"] == 0
    assert second["files_reused"] == 2
    assert second["symbol_count"] == first["symbol_count"]


def test_build_repo_index_incremental_handles_symbol_free_files(tmp_path: Path):
    """A file that indexes to zero symbols must still be treated as up to
    date on the next build (regression: manifest is the source of truth for
    "already processed", not membership in the flattened symbols list)."""
    _write(tmp_path, "empty.py", "# just a comment, no defs\n")

    first = build_repo_index(tmp_path)
    assert first["files_parsed"] == 1

    second = build_repo_index(tmp_path)
    assert second["files_parsed"] == 0
    assert second["files_reused"] == 1


def test_build_repo_index_reparses_changed_file(tmp_path: Path):
    path = _write(tmp_path, "a.py", "def a(): pass\n")
    build_repo_index(tmp_path)

    path.write_text("def a(): pass\n\ndef a_new(): pass\n", encoding="utf-8")
    result = build_repo_index(tmp_path)

    assert result["files_parsed"] == 1
    assert result["files_reused"] == 0
    symbols = json.loads((tmp_path / ".sarathi" / "index" / "symbols.json").read_text())
    assert {entry["name"] for entry in symbols} == {"a", "a_new"}


def test_build_repo_index_force_reparses_everything(tmp_path: Path):
    _write(tmp_path, "a.py", "def a(): pass\n")
    build_repo_index(tmp_path)

    result = build_repo_index(tmp_path, force=True)

    assert result["files_parsed"] == 1
    assert result["files_reused"] == 0


def test_build_repo_index_drops_removed_files(tmp_path: Path):
    gone = _write(tmp_path, "gone.py", "def gone_symbol(): pass\n")
    _write(tmp_path, "stays.py", "def stays_symbol(): pass\n")
    build_repo_index(tmp_path)

    gone.unlink()
    result = build_repo_index(tmp_path)

    assert result["files_removed"] == 1
    symbols = json.loads((tmp_path / ".sarathi" / "index" / "symbols.json").read_text())
    assert {entry["name"] for entry in symbols} == {"stays_symbol"}


def test_build_repo_index_handles_syntax_error_gracefully(tmp_path: Path):
    _write(tmp_path, "broken.py", "def broken(:\n    pass\n")

    result = build_repo_index(tmp_path)

    assert result["status"] == "built"
    symbols = json.loads((tmp_path / ".sarathi" / "index" / "symbols.json").read_text())
    assert symbols == []


def test_query_repo_index_ranks_name_matches_first(tmp_path: Path):
    _write(tmp_path, "auth.py", '''
def authenticate_user(token):
    """Verify a user's session token."""
    return True


def unrelated_helper():
    """Formats a date string."""
    return ""
''')
    build_repo_index(tmp_path)

    matches = query_repo_index(tmp_path, "authenticate user", limit=5)

    assert matches
    assert matches[0]["name"] == "authenticate_user"


def test_query_repo_index_empty_when_unindexed(tmp_path: Path):
    assert query_repo_index(tmp_path, "anything") == []


def test_query_repo_index_empty_query_returns_nothing(tmp_path: Path):
    _write(tmp_path, "a.py", "def a(): pass\n")
    build_repo_index(tmp_path)

    assert query_repo_index(tmp_path, "   ") == []


def test_format_symbol_hint():
    entry = {"file": "src/foo.py", "line": 42, "name": "Foo.bar", "kind": "method"}
    assert format_symbol_hint(entry) == "src/foo.py:42 Foo.bar (method)"


def test_index_summary_counts_by_kind(tmp_path: Path):
    _write(tmp_path, "a.py", "class A:\n    def m(self): pass\n\ndef f(): pass\n")
    build_repo_index(tmp_path)

    summary = index_summary(tmp_path)

    assert summary["symbol_count"] == 3
    assert summary["by_kind"] == {"class": 1, "method": 1, "function": 1}


def test_index_summary_empty_when_unindexed(tmp_path: Path):
    assert index_summary(tmp_path) == {"symbol_count": 0, "file_count": 0, "by_kind": {}}
