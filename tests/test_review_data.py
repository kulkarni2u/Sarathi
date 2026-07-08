"""Tests for the diff review data layer (src/review_data.py).

Covers the pure unified-diff parser, `record_review_decision`'s persistence
round-trip, and `find_diff_review`'s most-recent-first lookup across a
task's phase history.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.engine import Complexity, Phase, PhaseResult, TaskContext, PersistenceManager
from src.review_data import (
    find_diff_review,
    load_task_diff,
    parse_unified_diff,
    record_review_decision,
    rejected_paths,
)


# ── parse_unified_diff ──────────────────────────────────────────────────────

_MODIFIED_DIFF = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,4 @@
 line one
-line two
+line two changed
+line two point five
 line three
"""

_ADDED_DIFF = """diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+print("hello")
+print("world")
"""

_DELETED_DIFF = """diff --git a/src/old.py b/src/old.py
deleted file mode 100644
index 4444444..0000000
--- a/src/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("bye")
-print("!")
"""

_RENAMED_NO_CONTENT_DIFF = """diff --git a/src/before.py b/src/after.py
similarity index 100%
rename from src/before.py
rename to src/after.py
"""

_MULTI_HUNK_DIFF = """diff --git a/src/multi.py b/src/multi.py
index 5555555..6666666 100644
--- a/src/multi.py
+++ b/src/multi.py
@@ -1,2 +1,2 @@
-top old
+top new
@@ -10,2 +10,2 @@
-bottom old
+bottom new
"""

_BINARY_DIFF = """diff --git a/assets/logo.png b/assets/logo.png
index 7777777..8888888 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""


def test_parse_modified_file_hunk_and_line_kinds():
    files = parse_unified_diff(_MODIFIED_DIFF)

    assert len(files) == 1
    file_diff = files[0]
    assert file_diff.path == "src/a.py"
    assert file_diff.status == "modified"
    assert file_diff.old_path is None
    assert len(file_diff.hunks) == 1

    hunk = file_diff.hunks[0]
    assert hunk.old_start == 1 and hunk.old_count == 3
    assert hunk.new_start == 1 and hunk.new_count == 4
    kinds = [line.kind for line in hunk.lines]
    assert kinds == ["context", "del", "add", "add", "context"]
    assert hunk.lines[1].text == "-line two"
    assert hunk.lines[2].text == "+line two changed"


def test_parse_added_file_marks_status_and_dev_null_origin():
    files = parse_unified_diff(_ADDED_DIFF)

    assert len(files) == 1
    assert files[0].path == "src/new.py"
    assert files[0].status == "added"
    assert files[0].old_path is None
    assert len(files[0].hunks) == 1
    assert all(line.kind == "add" for line in files[0].hunks[0].lines)


def test_parse_deleted_file_marks_status():
    files = parse_unified_diff(_DELETED_DIFF)

    assert len(files) == 1
    assert files[0].path == "src/old.py"
    assert files[0].status == "deleted"
    assert all(line.kind == "del" for line in files[0].hunks[0].lines)


def test_parse_pure_rename_has_no_hunks():
    files = parse_unified_diff(_RENAMED_NO_CONTENT_DIFF)

    assert len(files) == 1
    file_diff = files[0]
    assert file_diff.path == "src/after.py"
    assert file_diff.old_path == "src/before.py"
    assert file_diff.status == "renamed"
    assert file_diff.hunks == []


def test_parse_multiple_hunks_in_one_file_stay_separate():
    files = parse_unified_diff(_MULTI_HUNK_DIFF)

    assert len(files) == 1
    hunks = files[0].hunks
    assert len(hunks) == 2
    assert hunks[0].old_start == 1
    assert hunks[1].old_start == 10
    assert hunks[0].lines[0].text == "-top old"
    assert hunks[1].lines[0].text == "-bottom old"


def test_parse_binary_file_has_no_hunks_and_is_flagged():
    files = parse_unified_diff(_BINARY_DIFF)

    assert len(files) == 1
    assert files[0].binary is True
    assert files[0].hunks == []


def test_parse_multiple_files_in_one_diff():
    combined = _MODIFIED_DIFF + _ADDED_DIFF + _DELETED_DIFF
    files = parse_unified_diff(combined)

    assert [f.path for f in files] == ["src/a.py", "src/new.py", "src/old.py"]
    assert [f.status for f in files] == ["modified", "added", "deleted"]


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "not a diff at all\njust some random text\n",
        "diff --git a/x b/x\nindex only, no hunks or --- +++\n",
        "@@ garbage hunk header @@\n+not attached to any file\n",
    ],
)
def test_parse_malformed_input_never_raises(malformed):
    # Should degrade gracefully rather than raising.
    result = parse_unified_diff(malformed)
    assert isinstance(result, list)


def test_parse_malformed_diff_git_header_alone_yields_file_with_no_hunks():
    files = parse_unified_diff("diff --git a/x b/x\nindex only, no hunks or --- +++\n")
    assert len(files) == 1
    assert files[0].path == "x"
    assert files[0].hunks == []


# ── load_task_diff ──────────────────────────────────────────────────────────

def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "seed"], capture_output=True, check=True)


def test_load_task_diff_prefers_recorded_review_diff_over_live_git(tmp_path):
    _init_git_repo(tmp_path)
    # Live workspace has no changes at all — the recorded diff should win.
    task = TaskContext(task_id="t-recorded", description="x", complexity=Complexity.LOW)
    task.phase_results.append(
        PhaseResult(
            phase=Phase.REVIEW,
            outcome="pass",
            artifacts={
                "review_inputs": {
                    "workspace_diff": {"measured": True, "diff": _MODIFIED_DIFF, "diff_truncated": False}
                }
            },
        )
    )

    files = load_task_diff(task, workspace_root=str(tmp_path))

    assert len(files) == 1
    assert files[0].path == "src/a.py"


def test_load_task_diff_falls_back_to_live_git_diff(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "seed.txt").write_text("seed\nmodified\n", encoding="utf-8")
    task = TaskContext(task_id="t-live", description="x", complexity=Complexity.LOW)

    files = load_task_diff(task, workspace_root=str(tmp_path))

    assert len(files) == 1
    assert files[0].path == "seed.txt"
    assert files[0].status == "modified"


def test_load_task_diff_returns_empty_list_when_nothing_available(tmp_path):
    task = TaskContext(task_id="t-empty", description="x", complexity=Complexity.LOW)

    files = load_task_diff(task, workspace_root=str(tmp_path))  # not a git repo

    assert files == []


# ── record_review_decision / find_diff_review ───────────────────────────────

def test_record_review_decision_persists_and_round_trips(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="t-decide", description="x", complexity=Complexity.LOW)
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass"))
    persistence.save_task(task)

    record_review_decision(persistence, "t-decide", "src/a.py", "rejected", note="looks off")

    reloaded = persistence.load_task("t-decide")
    diff_review = reloaded.phase_results[-1].artifacts["diff_review"]
    assert len(diff_review["decisions"]) == 1
    entry = diff_review["decisions"][0]
    assert entry["path"] == "src/a.py"
    assert entry["decision"] == "rejected"
    assert entry["note"] == "looks off"
    assert entry["hunk_index"] is None


def test_record_review_decision_replaces_earlier_decision_for_same_path(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="t-redecide", description="x", complexity=Complexity.LOW)
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass"))
    persistence.save_task(task)

    record_review_decision(persistence, "t-redecide", "src/a.py", "rejected")
    record_review_decision(persistence, "t-redecide", "src/a.py", "approved")

    reloaded = persistence.load_task("t-redecide")
    decisions = reloaded.phase_results[-1].artifacts["diff_review"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "approved"


def test_record_review_decision_keeps_separate_hunks_independent(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="t-hunks", description="x", complexity=Complexity.LOW)
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass"))
    persistence.save_task(task)

    record_review_decision(persistence, "t-hunks", "src/a.py", "approved", hunk_index=0)
    record_review_decision(persistence, "t-hunks", "src/a.py", "rejected", hunk_index=1)

    reloaded = persistence.load_task("t-hunks")
    decisions = reloaded.phase_results[-1].artifacts["diff_review"]["decisions"]
    assert len(decisions) == 2
    by_hunk = {d["hunk_index"]: d["decision"] for d in decisions}
    assert by_hunk == {0: "approved", 1: "rejected"}


def test_record_review_decision_rejects_unknown_decision(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="t-bad", description="x", complexity=Complexity.LOW)
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass"))
    persistence.save_task(task)

    with pytest.raises(ValueError):
        record_review_decision(persistence, "t-bad", "src/a.py", "maybe")


def test_record_review_decision_missing_task_raises(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))

    with pytest.raises(ValueError):
        record_review_decision(persistence, "does-not-exist", "src/a.py", "approved")


def test_record_review_decision_requires_phase_history(tmp_path):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(task_id="t-no-history", description="x", complexity=Complexity.LOW)
    persistence.save_task(task)

    with pytest.raises(ValueError):
        record_review_decision(persistence, "t-no-history", "src/a.py", "approved")


def test_find_diff_review_prefers_most_recent_phase_result():
    task = TaskContext(task_id="t-find", description="x", complexity=Complexity.LOW)
    task.phase_results.append(
        PhaseResult(
            phase=Phase.BUILD,
            outcome="pass",
            artifacts={"diff_review": {"decisions": [{"path": "old.py", "decision": "rejected", "hunk_index": None}]}},
        )
    )
    task.phase_results.append(
        PhaseResult(
            phase=Phase.VERIFY,
            outcome="pass",
            artifacts={"diff_review": {"decisions": [{"path": "new.py", "decision": "approved", "hunk_index": None}]}},
        )
    )

    diff_review = find_diff_review(task)

    assert diff_review["decisions"][0]["path"] == "new.py"


def test_find_diff_review_returns_empty_dict_when_none_recorded():
    task = TaskContext(task_id="t-none", description="x", complexity=Complexity.LOW)
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass"))

    assert find_diff_review(task) == {}


def test_rejected_paths_dedupes_and_sorts():
    diff_review = {
        "decisions": [
            {"path": "b.py", "decision": "rejected"},
            {"path": "a.py", "decision": "rejected"},
            {"path": "a.py", "decision": "rejected", "hunk_index": 2},
            {"path": "c.py", "decision": "approved"},
        ]
    }

    assert rejected_paths(diff_review) == ["a.py", "b.py"]


def test_rejected_paths_empty_when_no_decisions():
    assert rejected_paths({}) == []
    assert rejected_paths({"decisions": []}) == []
