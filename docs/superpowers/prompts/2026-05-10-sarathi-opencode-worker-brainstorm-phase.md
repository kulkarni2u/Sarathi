# OpenCode Worker Prompt: Sarathi Brainstorm Phase

Date: 2026-05-10
Model: Minimax m2.5 (or any capable provider)
Orchestrator: Sarathi (Claude Sonnet 4.6)

## Your Job

Implement the Sarathi Brainstorm Phase, task-by-task, exactly as specified in the
implementation plan. Do not skip steps. Do not combine tasks. Commit after every task.

## Repository

```
/Users/sweethome/Work/Skills/Sarathi
```

All commands must be run from this directory.

## Plan

Full implementation plan is at:
```
docs/superpowers/plans/2026-05-10-sarathi-brainstorm-phase.md
```

Read it completely before starting. Then implement each task in order:

| Task | What | Files |
|------|------|-------|
| 1 | Storage: brainstorm_sessions migration + CRUD | `src/storage/__init__.py`, `tests/test_brainstorm_storage.py` |
| 2 | Service: 5 brainstorm endpoints + SSE | `src/service/__init__.py`, `tests/test_brainstorm_api.py` |
| 3 | Phase: brainstorm.py session lifecycle | `src/phases/brainstorm.py` |
| 4 | Client: apiClient.ts brainstorm functions | `desktop/src/apiClient.ts` |
| 5 | Component: ResearchPanel.tsx | `desktop/src/components/ResearchPanel.tsx` |
| 6 | Component: SpecPreview.tsx | `desktop/src/components/SpecPreview.tsx` |
| 7 | Component: BrainstormChat.tsx | `desktop/src/components/BrainstormChat.tsx` |
| 8 | Page: Brainstorm.tsx overlay | `desktop/src/pages/Brainstorm.tsx` |
| 9 | Wiring: App.tsx route + entry point | `desktop/src/App.tsx` |
| 10 | Skill: SKILL.md brainstorm block | `Sarathi-Skill/SKILL.md` |

## Critical Constraints

1. **TDD for all backend tasks** — write the failing test first, run it, then implement
2. **Build check for all frontend tasks** — `npm --prefix desktop run build` must pass after each task
3. **Commit after every task** — use the commit message from the plan exactly
4. **Do not modify** files outside the task's file list
5. **Use `_load_json_list`** (not `_load_json`) for JSON array columns in storage
6. **Use `create_lifecycle_event`** (not `create_event`) in the service `_emit_event` helper
7. **Schema version** must be bumped to 5 in `src/storage/__init__.py`

## Verification Before Done

Run these three commands and confirm all pass:

```bash
python3 -m pytest tests/test_brainstorm_storage.py tests/test_brainstorm_api.py -v
python3 -m pytest tests/ -q --tb=short
npm --prefix desktop run build 2>&1 | tail -4
```

All must be green. Report exact output.

## What This Builds

Every Sarathi task now starts with a structured brainstorm dialogue instead of
jumping straight to planning. The provider (any: Claude, Codex, OpenCode, Copilot)
conducts the dialogue. The Desktop shows a full-panel overlay with live spec preview.
The CLI phase polls the service until the spec is approved, then creates the task.
