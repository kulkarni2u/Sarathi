# Sarathi Desktop Next Task

Date: 2026-05-10

## Current Goal

The main Sarathi desktop ship pass is effectively complete.

Current remaining product work is narrow:

1. Decide whether `Settings` should get editable `auto_approve_preference` controls in a future pass.

## Already Verified

- `workspace -> project -> task` flow works
- workspace project creation is persisted
- task studio opens on the correct task
- support surfaces are hardened
- QA wrapper uses isolated DB state
- backend `auto_approve_preference` contract exists
- `Settings` shows read-only auto-approve policy posture
- project-creation entry-point regression is cleared:
  - create form now scrolls into view
  - `Project name` field is focused

## Known Verification Reality

- Browser QA wrapper passes when run unsandboxed on the host:

```bash
BASE_URL=http://127.0.0.1:5175 CLEANUP_DB_PATH=true desktop/scripts/validate-task-panel.sh
```

- Sandboxed Playwright runs can fail due local Chromium/macOS permission issues in the agent runtime. Treat that as environment-specific unless proven otherwise.

## If Continuing Product Work

Only open a new implementation slice if you are intentionally doing one of:

- editable `auto_approve_preference` controls in `Settings`
- release hygiene / commit slicing
- a brand-new desktop feature pass
