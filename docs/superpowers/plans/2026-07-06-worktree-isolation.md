# Worktree Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Phase 2.2 worktree-isolation slice so graph EXECUTE branches can be prepared in isolated git worktrees.

**Architecture:** Introduce a focused `src/runtime/isolation.py` module for git worktree lifecycle operations, then declare the selected mode on `HarnessConfig`. The graph executor integration will use that declaration later to route provider working directories without changing provider-specific bridge APIs first.

**Tech Stack:** Python dataclasses, pathlib, subprocess git CLI, pytest temp git repositories.

---

### Task 1: Git Worktree Lifecycle Helper

**Files:**
- Create: `src/runtime/isolation.py`
- Create: `tests/test_runtime_isolation.py`

- [x] **Step 1: Write failing tests**

Create `tests/test_runtime_isolation.py` with tests that initialize a temporary git repo, commit one file, call `GitWorktreeIsolation.create_worktree(task_id="task-1", node_id="node-a")`, assert the returned path is under `.sarathi/worktrees/task-1/node-a`, assert `git rev-parse --git-common-dir` in the child points at the parent repo common dir, and assert cleanup removes the worktree path from disk and `git worktree list --porcelain`.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_runtime_isolation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.runtime.isolation'`.

- [x] **Step 3: Implement minimal helper**

Create `GitWorktreeIsolation` with `create_worktree`, `cleanup_worktree`, and `cleanup_task_worktrees`. Use `git worktree add --detach <path> HEAD` for deterministic test repos and `git worktree remove --force <path>` for cleanup.

- [x] **Step 4: Run tests to verify pass**

Run: `python3 -m pytest tests/test_runtime_isolation.py -q`
Expected: PASS.

### Task 2: Declare Isolation Mode on HarnessConfig

**Files:**
- Modify: `src/harness.py`
- Modify: `tests/test_harness.py`

- [x] **Step 1: Write failing tests**

Add `test_harness_config_defaults_to_no_isolation`, `test_harness_config_isolation_mode_roundtrip`, and extend the old-format JSON test to remove `isolation_mode` and assert it defaults to `"none"`.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_harness.py::test_harness_config_defaults_to_no_isolation tests/test_harness.py::test_harness_config_isolation_mode_roundtrip tests/test_harness.py::test_from_json_handles_old_format_without_new_fields -q`
Expected: FAIL because `HarnessConfig` has no `isolation_mode` field.

- [x] **Step 3: Implement minimal field**

Add `isolation_mode: str = "none"` to `HarnessConfig` under the execution plan fields and set `d.setdefault("isolation_mode", "none")` in `from_json`.

- [x] **Step 4: Run tests to verify pass**

Run: same targeted pytest command.
Expected: PASS.

### Task 3: Graph Dispatch Integration

**Files:**
- Modify: `src/runtime/graph_executor.py`
- Modify: `tests/test_workflow_patterns.py`

- [x] **Step 1: Write failing tests**

Add tests proving `TaskGraphExecutor` creates per-node worktree paths before dispatch when `HarnessConfig(isolation_mode="worktree")` is supplied and includes the path in `DispatchRequest.constraints["workspace_dir"]`.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_workflow_patterns.py::test_executor_dispatches_execute_node_with_worktree_workspace_constraint -q`
Expected: FAIL because no workspace constraint is emitted yet.

- [x] **Step 3: Implement minimal executor wiring**

Create the worktree before node dispatch, include `workspace_dir` and `isolation_mode` in constraints, and clean up task worktrees when execution finishes.

- [x] **Step 4: Run tests to verify pass**

Run: targeted workflow-pattern tests, then `python3 -m pytest tests/test_runtime_isolation.py tests/test_harness.py tests/test_workflow_patterns.py -q`.
Expected: PASS.

### Task 4: Provider Bridge Workspace Routing

**Files:**
- Modify: `src/runtime/providers/cli_bridge.py`
- Modify: `tests/test_cli_bridge_sessions.py`

- [x] **Step 1: Write failing tests**

Add fake-CLI tests proving `DispatchRequest.constraints["workspace_dir"]` changes the process `cwd` for Codex and the `--dir` argument plus process `cwd` for OpenCode.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_cli_bridge_sessions.py::test_codex_dispatch_uses_workspace_dir_constraint_for_cwd tests/test_cli_bridge_sessions.py::test_opencode_dispatch_uses_workspace_dir_constraint_for_dir_and_cwd -q`
Expected: FAIL because both providers still run in the parent workspace.

- [x] **Step 3: Implement minimal bridge routing**

In `dispatch_via_cli_bridge`, treat a non-empty `request.constraints["workspace_dir"]` as the effective workspace root before permission setup, snapshots, provider command construction, and process execution.

- [x] **Step 4: Run tests to verify pass**

Run: same targeted pytest command, then `python3 -m pytest tests/test_cli_bridge_sessions.py tests/test_workflow_patterns.py tests/test_runtime_isolation.py -q`.
Expected: PASS.

### Task 5: Manual Candidate Worktree Retention

**Files:**
- Modify: `src/harness.py`
- Modify: `src/runtime/graph_executor.py`
- Modify: `tests/test_harness.py`
- Modify: `tests/test_workflow_patterns.py`

- [x] **Step 1: Write failing tests**

Add tests proving `HarnessConfig.isolation_cleanup` defaults to `"auto"`, round-trips as `"manual"`, old JSON defaults to `"auto"`, and manual cleanup leaves an isolated node worktree present while recording isolation metadata on the graph node and provider result.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_harness.py::test_harness_config_defaults_to_no_isolation tests/test_harness.py::test_harness_config_isolation_mode_roundtrip tests/test_harness.py::test_from_json_handles_old_format_without_new_fields tests/test_workflow_patterns.py::test_manual_worktree_cleanup_retains_workspace_and_records_metadata -q`
Expected: FAIL because `isolation_cleanup` and retained metadata do not exist.

- [x] **Step 3: Implement minimal retention switch**

Add `isolation_cleanup: str = "auto"` to `HarnessConfig`, preserve old JSON compatibility, skip automatic worktree cleanup when the mode is `"manual"`, and stamp `{"mode": "worktree", "cleanup": ..., "workspace_dir": ...}` onto node/provider artifacts for later judging or merge-back.

- [x] **Step 4: Run tests to verify pass**

Run: same targeted pytest command, then `python3 -m pytest tests/test_runtime_isolation.py tests/test_harness.py tests/test_workflow_patterns.py tests/test_cli_bridge_sessions.py -q`.
Expected: PASS.

### Task 6: Approved Candidate Merge-Back Primitive

**Files:**
- Modify: `src/runtime/isolation.py`
- Modify: `tests/test_runtime_isolation.py`

- [x] **Step 1: Write failing tests**

Add tests proving `GitWorktreeIsolation.apply_worktree_changes(...)` requires explicit approval, applies approved untracked and tracked candidate file edits back to the parent repo, rejects a dirty parent workspace, excludes candidate `.sarathi/` runtime artifacts, and rejects unmanaged worktree paths.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_runtime_isolation.py::test_apply_worktree_changes_requires_approval tests/test_runtime_isolation.py::test_apply_worktree_changes_applies_untracked_candidate_file tests/test_runtime_isolation.py::test_apply_worktree_changes_rejects_dirty_parent_workspace tests/test_runtime_isolation.py::test_apply_worktree_changes_excludes_sarathi_runtime_artifacts tests/test_runtime_isolation.py::test_apply_worktree_changes_rejects_unmanaged_worktree_path -q`
Expected: FAIL before implementation for the missing method, `.sarathi/` exclusion, and unmanaged path validation.

- [x] **Step 3: Implement minimal approval-gated apply**

Add `apply_worktree_changes(path, approved=...)`, validate the path is a registered managed worktree, require a clean parent repo, intent-add candidate untracked files while excluding `.sarathi/`, generate a binary diff, preflight it with `git apply --check`, and apply it to the parent repo only after approval.

- [x] **Step 4: Run tests to verify pass**

Run: same targeted pytest command, then `python3 -m pytest tests/test_runtime_isolation.py tests/test_harness.py tests/test_workflow_patterns.py tests/test_cli_bridge_sessions.py -q`.
Expected: PASS.

### Task 7: Explicit Approved JUDGE Winner Apply Surface

**Files:**
- Modify: `src/runtime/graph_executor.py`
- Modify: `tests/test_workflow_patterns.py`

- [x] **Step 1: Write failing tests**

Add tests proving `TaskGraphExecutor.apply_judge_winner_worktree(...)` requires explicit approval, applies only the retained worktree for `last_provider_result.outputs.winner`, records the apply result on a returned graph copy, cleans managed candidate worktrees after successful apply, skips when the judge output has no winner, skips when the winner node is absent, and skips when the winner node has no worktree isolation metadata.

- [x] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_workflow_patterns.py::test_apply_judge_winner_worktree_requires_explicit_approval tests/test_workflow_patterns.py::test_apply_judge_winner_worktree_applies_approved_winner tests/test_workflow_patterns.py::test_apply_judge_winner_worktree_skips_without_winner_output tests/test_workflow_patterns.py::test_apply_judge_winner_worktree_skips_without_isolation_metadata tests/test_workflow_patterns.py::test_apply_judge_winner_worktree_skips_when_winner_node_missing -q`
Expected: FAIL with `AttributeError` because the executor surface does not exist yet.

- [x] **Step 3: Implement minimal apply surface**

Add `apply_judge_winner_worktree(graph, judge_node_id=..., approved=...)` to locate the judge output, resolve the winning node isolation metadata, delegate to `GitWorktreeIsolation.apply_worktree_changes`, annotate a copied graph only after an approved apply succeeds, and clean managed candidate worktrees from the graph.

- [x] **Step 4: Run tests to verify pass**

Run: same targeted pytest command, then `python3 -m pytest tests/test_runtime_isolation.py tests/test_harness.py tests/test_workflow_patterns.py tests/test_cli_bridge_sessions.py -q`.
Expected: PASS.
