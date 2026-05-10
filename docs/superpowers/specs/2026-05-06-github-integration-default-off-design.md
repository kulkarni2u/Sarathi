# Sarathi GitHub Integration Default-Off Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-06

## Goal

Sarathi should support GitHub in a way that feels similar to Codex: repo-aware, issue-aware, and PR-aware, but only when the user explicitly enables it. By default, commit and PR actions must remain disabled.

This slice is not about full webhook sync or deep GitHub project management. It is about letting Sarathi import GitHub work into the workspace/task model and, when the user opts in, export a task back to GitHub as a commit or PR.

## Design Principles

1. Default off
   - Sarathi must not commit or open a PR unless the user explicitly enables repository actions.
   - The default posture is local-only and review-safe.

2. User preference first
   - Commit and PR capabilities should be controlled at the workspace or task level.
   - The user must choose the action mode explicitly: no commit, commit only, draft PR, or ready PR.

3. Codex-like workflow
   - GitHub should be treated as part of the delivery path, not as a separate integration island.
   - The flow should feel like: import issue -> work in Sarathi -> optionally export commit/PR.

4. Narrow first slice
   - Start with issue import and export preference gating.
   - Defer webhook sync, project boards, and bidirectional status sync until the core contract proves useful.

## Recommended Approaches

### Option 1: Import-only first

- Import GitHub issues into Sarathi tasks.
- Leave commit/PR export for later.

Trade-off:
- Lowest risk and fastest to ship.
- Does not yet match the full Codex-like end-to-end handoff.

### Option 2: Export-only first

- Add commit/PR export from completed tasks.
- Import remains manual or through chat paste.

Trade-off:
- Useful for delivery, but weaker on task intake.
- Harder for users who want GitHub issues to become tasks automatically.

### Option 3: Import + export with default-off commit/PR

- Import GitHub issues into Sarathi tasks.
- Add explicit repository-action preferences.
- Enable commit / draft PR / ready PR only when the user opts in.

Trade-off:
- Slightly larger than a one-way slice.
- Best match to the Codex-like workflow and the user’s preference for safe defaults.

**Recommendation:** Option 3, because it preserves safety while giving Sarathi a complete repo-aware workflow.

## User-Facing Behavior

### Import

Sarathi should let a user bring a GitHub issue into a workspace or task with minimal friction:

- issue URL
- issue number
- repository reference
- optional labels / milestone metadata

The imported issue becomes a Sarathi task draft or inbox item, depending on workspace state.

### Export

Sarathi should support four repository-action modes:

- `no_action`
- `prepare_patch`
- `commit`
- `draft_pr`
- `ready_pr`

By default, the workspace should stay on `no_action`.

When the user enables a higher mode, Sarathi may prepare the required branch/patch/PR body, but only after explicit confirmation.

## Preference Model

Repository actions should be controlled by preference at three scopes:

1. Workspace
   - Default behavior for all tasks in the workspace.

2. Project
   - Optional override for a project that wants a stronger or weaker repository-action posture.

3. Task
   - Final handoff choice for the current work item.

Precedence should be task > project > workspace > default.

Default values:

- `no_action`
- no automatic commit
- no automatic PR

## Data Flow

1. A user imports a GitHub issue or pastes a GitHub issue link into Sarathi.
2. Sarathi creates or updates a task draft using the workspace/project context.
3. The task is executed and reviewed inside Sarathi.
4. At final handoff, Sarathi checks the active repository-action preference.
5. If the user opted in, Sarathi prepares the commit or PR action and asks for explicit approval before execution.
6. If the user did not opt in, Sarathi exports a local handoff only.

## Integration Contract

GitHub integration should be modeled as a generic repository-source / repository-destination capability:

- source: issue import
- destination: commit, branch, draft PR, ready PR

The contract should avoid hard-coding GitHub into the task graph. GitHub is one provider of repository metadata and repository actions.

## UI Surface

### Settings

Add a repository-actions section:

- default action mode
- issue import enabled or disabled
- commit enabled or disabled
- PR enabled or disabled
- PR default type: draft or ready, if enabled

### Task detail / final handoff

Show the current repository-action preference and the action that will happen if the user approves:

- no commit
- commit only
- draft PR
- ready PR

Keep the language plain and explicit.

## Error and Safety Rules

- No repository action is allowed unless the preference explicitly enables it.
- Sarathi must show what will happen before execution.
- A failed commit or PR preparation should fall back to a local handoff and surface the error clearly.
- Secrets, tokens, and raw GitHub credentials must never appear in the UI.

## Non-Goals

- Full GitHub webhook sync
- GitHub Projects support
- Comment-thread synchronization
- Automatic PR creation without explicit approval
- Provider-specific GitHub behavior that bypasses Sarathi’s repository-action gate

## Current Gap Summary

Sarathi already has the policy and repository-action concepts needed for a safe GitHub integration. The remaining work is to make the workflow explicit and useful:

- import GitHub issues into Sarathi tasks
- keep commit / PR default-off
- let users opt in at workspace/project/task scope
- export repository actions only after explicit approval

That gives Sarathi a Codex-like GitHub flow without sacrificing the calm, policy-backed default posture.
