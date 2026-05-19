You are the primary orchestrator and implementor for one bounded Sarathi slice.

Repo:
- /Users/sweethome/Work/Skills/Sarathi

Goal:
Make the new `Knowledge Center -> Learnings` section actionable instead of static.

This slice should do two things:
1. Fix any route/render gaps so the `learnings` Knowledge Center section behaves like the other internal Knowledge Center sections.
2. Add outbound links/actions from each learning card so operators can navigate from a learning back to related work.

Primary intent:
- Learnings should connect back to the originating task and outward to reusable workflow assets.
- Keep the UI summary-first and consistent with the existing Sarathi desktop style.

Inspect first:
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/App.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/KnowledgeCenter.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/WorkspaceDashboard.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/ProjectDetail.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts
- /Users/sweethome/Work/Skills/Sarathi/src/service/__init__.py
- /Users/sweethome/Work/Skills/Sarathi/tests/test_reuse_kit.py
- /Users/sweethome/Work/Skills/Sarathi/docs/superpowers/tasks/2026-05-10-sarathi-desktop-next.md

Scope constraints:
- Keep changes localized.
- Do not redesign unrelated surfaces.
- Do not use Claude.
- Prefer using existing route state and existing persisted data.

Acceptance criteria:
1. The `learnings` route renders through `KnowledgeCenter` the same way `wiki`, `context`, and `proposals` do.
2. Each learning card exposes at least one useful action when data is available:
   - open related task if `task_id` exists
   - open reusable workflow surface if promoted playbook/view linkage exists
3. The actions are clear and scan-friendly, not noisy.
4. Empty-state behavior remains clean.
5. Update the rolling task log with the completed slice and verification lines.

Implementation guidance:
- Reuse existing app route/state patterns instead of inventing a new navigation model.
- If you need a callback from `App.tsx` into `KnowledgeCenter`, keep it minimal and explicit.
- Prefer one or two direct actions per learning card over a broad action matrix.
- Keep the Learnings section clearly part of Knowledge Center, not a new top-level product.

Verification required:
- Run focused tests if you change service behavior
- Then run:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

Deliver in your response:
- changed files
- concise summary
- verification results
- any blockers
