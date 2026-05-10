# Sarathi Brainstorm Phase Design

Date: 2026-05-10
Status: Approved

## Goal

Replace the current evidence-weighted confidence gate in Sarathi's Brainstorm phase with a
structured, provider-driven dialogue that produces an approved spec before any Plan or Build
phase begins. Every task entry point — Skill (any agent runtime) or Desktop — funnels through
the same brainstorm session, persisted in SQLite, with the actual dialogue conducted by
whichever provider is configured for the workspace (Claude, Codex, OpenCode, Copilot, or custom).

## Constraints

- Skill entry works standalone — no Desktop required
- Desktop entry works without Claude Code open
- Both produce the same SQLite task record and `.sarathi/brainstorm/<id>/spec.md` artifact
- Git commit of spec is user-initiated, never automatic
- Sarathi framework changes (SKILL.md, brainstorm.py, templates) are committed to the repo
- Evidence gate (4 dimensions) still enforced — spec must cover them before approval allowed
- No new infrastructure beyond what Sarathi already has (Python service, SQLite, SSE, Desktop)

## Architecture

```
Entry Points
│
├── Skill (any agent runtime)        Desktop UI
│   SKILL.md drives dialogue         "New Task" → brainstorm overlay
│   configured provider conducts     configured provider conducts
│   terminal/IDE is the canvas       Desktop overlay is the canvas
│         │                                │
│         └──────────────┬─────────────────┘
│                        ▼
│              Python Service (existing)
│              5 new brainstorm endpoints
│              SSE stream extended (existing)
│                        │
│                   SQLite + .sarathi/
│              brainstorm_sessions table
│              .sarathi/brainstorm/<id>/spec.md
│              .sarathi/brainstorm/<id>/brainstorm.json
│                        │
│                On approval
│                        ▼
│              Task created in SQLite
│              → Sarathi 12-phase lifecycle begins
```

## Data Model

### New SQLite Table

```sql
CREATE TABLE IF NOT EXISTS brainstorm_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    task_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL,
    provider TEXT,
    spec_path TEXT,
    spec_content TEXT,
    output_format TEXT DEFAULT 'markdown',
    dialogue_turns TEXT NOT NULL DEFAULT '[]',
    research_findings TEXT NOT NULL DEFAULT '[]',
    visual_options TEXT NOT NULL DEFAULT '[]',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### Dialogue Turn Shape

```json
{
  "role": "sarathi | user",
  "content": "Which auth strategy fits your scale?",
  "options": ["Session tokens", "JWT stateless", "Delegated OAuth"],
  "selected": "JWT stateless",
  "timestamp": "2026-05-10T14:00:00Z"
}
```

### Research Finding Shape

```json
{
  "agent": "Vichara",
  "type": "codebase | risk | pattern | reference",
  "summary": "Existing auth middleware uses session tokens",
  "refs": ["src/auth.py:42", "tests/test_auth.py:18"],
  "timestamp": "2026-05-10T14:00:01Z"
}
```

### Artifact Store

```
.sarathi/brainstorm/<session_id>/
  spec.md          ← live spec, updated each turn
  brainstorm.json  ← full session dump on approval
```

On approval, Sarathi offers (never forces) export to a user-specified path.

## Service Endpoints

Five new endpoints under `/api/brainstorm`:

```
POST /api/brainstorm/sessions
  body: { workspace_id, project_id?, title, provider?, output_format? }
  → creates session, dispatches Explore sub-agents for initial research
  returns: { session }

GET  /api/brainstorm/:id
  → full session snapshot
  returns: { session }

POST /api/brainstorm/:id/turns
  body: { role, content, options?, selected? }
  → appends dialogue turn, updates spec_content draft
  returns: { session }

POST /api/brainstorm/:id/research
  body: { agent, type, summary, refs? }
  → appends research finding from Explore sub-agent
  returns: { session }

POST /api/brainstorm/:id/approve
  body: { output_format?, export_path? }
  → marks approved, writes spec to .sarathi/brainstorm/:id/spec.md
  → creates task in SQLite
  → if export_path provided, also writes there
  returns: { session, task }
```

SSE extension (no new infrastructure):

```
GET /api/events/stream  (existing, extended)
  New events emitted:
    brainstorm.session_started
    brainstorm.turn_added
    brainstorm.research_added
    brainstorm.spec_updated
    brainstorm.approved
```

## Skill Changes

### SKILL.md — Brainstorm Phase Block

The SKILL.md is **provider-agnostic** — it must work identically whether the
conducting provider is Claude, Codex, OpenCode, Copilot, or any future provider.
No provider name appears in the skill text. The provider reads the skill and
follows the process; Sarathi routes to whichever provider is configured.

Replace current evidence-gate description with:

```markdown
## Brainstorm Phase

Every task starts here. No Plan, no Build until an approved spec exists.
This phase is conducted by the configured provider — the process is identical
regardless of which provider is active.

### Process

1. Research first — dispatch Explore sub-agents before asking the user anything:
   - Vichara: scan relevant files, existing patterns, prior decisions
   - Marga: classify complexity, identify affected surfaces
   - Post findings to /api/brainstorm/:id/research

2. One question at a time — informed by research, not abstract:
   - Multiple choice preferred when options are enumerable
   - Never ask what the code already answers
   - Never ask two questions in one message

3. Propose 2-3 approaches with tradeoffs, lead with recommendation

4. Build spec live — update spec draft after each answered question:
   - Goal, constraints, success criteria
   - Chosen approach + rationale
   - Explicit out-of-scope
   - Risks identified

5. Hard gate — no transition to Plan until:
   - All four evidence dimensions covered in spec
   - User approves (Desktop button or terminal confirmation)
   - POST /api/brainstorm/:id/approve called
   - Task record exists in SQLite

### Evidence Dimensions (auto-checked by brainstorm.py)
- alternative_approaches_considered (weight 0.3)
- risks_identified (weight 0.3)
- success_criteria_defined (weight 0.2)
- reversibility_assessed (weight 0.2)

### Output
- Spec: .sarathi/brainstorm/<id>/spec.md
- Task: SQLite tasks table, linked to session
- Export: offered to user, never forced

### Provider Contract
The conducting provider receives a structured turn payload and returns a
structured response (question + options + spec_update). The provider does
not need to know it is inside a Sarathi lifecycle — the skill instructs it
on the process, the service handles persistence and routing.
```

### `src/phases/brainstorm.py` Changes

Current: evidence confidence gate only.

New responsibilities:
1. Create or resume brainstorm session via service API
2. Dispatch Explore sub-agents (Vichara, Marga) for initial research
3. Drive dialogue loop until `session.status == "approved"`
4. Validate spec covers all four evidence dimensions
5. Return `PhaseResult` with `spec_path` as artifact

```python
class BrainstormPhase:
    def run(self, context: TaskContext) -> PhaseResult:
        session = self._get_or_create_session(context)
        self._dispatch_research_agents(context, session)
        result = self._wait_for_approval(session)
        self._validate_spec_coverage(result.spec_content)
        return PhaseResult(outcome="pass", artifact=result.spec_path)
```

`_wait_for_approval` polls `GET /api/brainstorm/:id` with timeout and escalation
if the user goes idle past the configured threshold.

## Desktop Overlay

### New Files

```
desktop/src/pages/Brainstorm.tsx           ← full-panel overlay page
desktop/src/components/BrainstormChat.tsx  ← dialogue thread + clickable options
desktop/src/components/SpecPreview.tsx     ← live markdown → HTML render
desktop/src/components/ResearchPanel.tsx   ← Explore agent findings
```

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  Brainstorm  ·  "Add OAuth2 login"        [phase 1 of 12]│
│  Provider: claude  ·  Workspace: sarathi                 │
├─────────────────────────┬────────────────────────────────┤
│ Research                 │ Spec (live)                   │
│ Vichara ↳ src/auth.py   │ ## Goal                       │
│ Marga ↳ complexity: med │ ## Approach                   │
│                          │ ## Out of scope               │
│ Dialogue                 │ ## Risks                      │
│                          │                               │
│ Sarathi:                 │                               │
│ [question]               │                               │
│                          │                               │
│ [A] Option               │                               │
│ [B] Option               │                               │
│ [C] Option               │                               │
│                          │                               │
│ [type or click] ______   │  [Export spec]  [Approve →]  │
└─────────────────────────┴────────────────────────────────┘
```

### SSE Subscription

`Brainstorm.tsx` subscribes to the existing event stream and reacts to:
- `brainstorm.turn_added` → append to dialogue thread
- `brainstorm.research_added` → append to research panel
- `brainstorm.spec_updated` → re-render spec preview
- `brainstorm.approved` → navigate to Task Studio for the new task

### Entry Points

**From Desktop "New Task"**: calls `POST /api/brainstorm/sessions`, navigates to
`/brainstorm/:id` instead of going straight to task creation.

**From Skill**: Skill creates the session via service API. Desktop receives a
`brainstorm.session_started` SSE event and shows a notification badge on the
Brainstorm nav item. User clicks to open the overlay — it does not auto-navigate
away from whatever the user is currently viewing.

### New `apiClient.ts` Functions

```typescript
createBrainstormSession(workspaceId, projectId?, title, provider?)
getBrainstormSession(sessionId)
addBrainstormTurn(sessionId, turn)
approveBrainstormSession(sessionId, options?)
```

## Provider Integration

### New Provider Mode: `brainstorm_turn`

Each provider call is one dialogue turn. Provider receives:

```json
{
  "mode": "brainstorm_turn",
  "context": {
    "title": "Add OAuth2 login",
    "research_findings": [...],
    "dialogue_so_far": [...],
    "spec_draft": "## Goal\n...",
    "evidence_coverage": {
      "approaches_considered": false,
      "risks_identified": true,
      "success_criteria": false,
      "reversibility": false
    }
  },
  "instructions": "Ask one question. Multiple choice if options are enumerable. Never ask what research already answers. Update spec draft."
}
```

Provider returns:

```json
{
  "question": "Existing auth uses sessions. JWT means migration. Which fits your timeline?",
  "options": ["Migrate all", "Run parallel", "JWT for new users only"],
  "spec_update": "## Approach\nJWT stateless chosen because..."
}
```

### Entry-Point Routing

| Entry | Provider | Dispatch |
|---|---|---|
| Skill (any agent runtime) | Whichever provider is conducting the session | Provider calls service API directly to persist turns |
| Desktop | Configured workspace provider (claude/codex/opencode/copilot/custom) | `cli_bridge` dispatch per turn |

The Skill works in any agent runtime that can read SKILL.md — Claude Code, Cursor,
Copilot, Codex, OpenCode. The conducting provider follows the same process regardless
of which runtime loaded the skill.

## Sarathi Framework Changes to Commit

- `Sarathi-Skill/SKILL.md` — updated brainstorm phase block
- `src/phases/brainstorm.py` — session lifecycle driver
- `src/storage/__init__.py` — brainstorm_sessions table + CRUD
- `src/service/__init__.py` — 5 new brainstorm endpoints + SSE events
- `policy-pack/TEMPLATE/` — brainstorm process template for new projects
- `desktop/src/pages/Brainstorm.tsx` — overlay page
- `desktop/src/components/BrainstormChat.tsx`
- `desktop/src/components/SpecPreview.tsx`
- `desktop/src/components/ResearchPanel.tsx`
- `desktop/src/apiClient.ts` — 4 new brainstorm client functions
- `desktop/src/App.tsx` — route wiring + "New Task" entry point change
- `tests/test_brainstorm_api.py` — new test file

## What This Replaces

- `superpowers:brainstorming` skill invocation from Sarathi flows
- `superpowers:writing-plans` invocation (Plan phase handles this natively)
- Superpowers visual companion Node.js server (Desktop overlay replaces it)

## Out of Scope

- Async brainstorm (user closes Desktop mid-session and resumes later) — sessions
  persist so resume works, but no push notification to re-engage the user
- Multi-user brainstorm sessions
- Brainstorm history / search across past sessions
- AI-to-AI brainstorm (provider debates itself) — single provider per session
