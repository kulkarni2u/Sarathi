You are the primary orchestrator and implementor for one bounded Sarathi slice.

Repo:
- /Users/sweethome/Work/Skills/Sarathi

Goal:
Add direct navigation from proposals to related learnings.

Owned files:
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/App.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/KnowledgeCenter.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Proposals.tsx

Do not edit:
- ProjectDetail.tsx
- validate-task-panel.mjs
- tests unless absolutely required for type/build compatibility

Acceptance criteria:
1. A proposal with an inferred learning link can open the related learning inside `Knowledge Center`.
2. The route and section state remain consistent with the existing Knowledge Center IA.
3. The UI stays summary-first and lightweight.
4. No unrelated route churn.

Implementation guidance:
- Reuse the existing `Learning link` indicator.
- Prefer a minimal callback path from `App.tsx` into `Proposals` via `KnowledgeCenter`.
- It is acceptable to identify the target learning by task_id or another existing stable identifier already available in the learning/proposal data.

Verification required:
- `npm --prefix desktop run build`

Deliver:
- changed files
- concise summary
- verification result
- blockers
