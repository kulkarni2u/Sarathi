# Chat Orchestrator Implementation Tasks

**Parent Task:** `a3145818b97c4cccaf38c78987a23f75` - Implement Chat Orchestrator UI
**Status:** graph_pending (needs manual orchestration via Claude/Codex)

## Spec & Plan
- **Design:** `docs/superpowers/specs/2026-05-04-chat-orchestrator-design.md`
- **Plan:** `docs/superpowers/plans/2026-05-04-chat-orchestrator.md`

## 6 Subtasks (execute in order)

| # | Subtask ID | Title | Status | Notes |
|---|------------|-------|--------|-------|
| 1 | fac32352ee2643a7880a5b611a8da5a1 | Enable chat composer UI | blocked | Enable send button in Task Studio chat |
| 2 | t2-add-api-client | Add chat API client | blocked | Add sendChatMessage() to apiClient.ts |
| 3 | t3-priority-settings | Add provider priority to settings | blocked | Allow reorder in Settings tab |
| 4 | t4-chat-endpoint | Add /api/chat endpoint | blocked | Smart dispatch based on priority |
| 5 | t5-wire-ui | Wire UI to API | blocked | Connect handleChatSubmit to API |
| 6 | t6-rate-limits | Add rate limit tracking | blocked | Track and fallback on rate limits |

## Implementation Details

### Task 1: Enable Chat Composer UI
- **File:** `desktop/src/App.tsx:1515-1517`
- **Current:** `<form onSubmit={...}><input placeholder="Send..." />` - disabled with TODO
- **Change:** Add state, handler, wire up form

```typescript
const [chatInput, setChatInput] = useState("");
const handleChatSubmit = async (e: FormEvent) => {
  e.preventDefault();
  if (!chatInput.trim()) return;
  // TODO: call API
};
// <form onSubmit={handleChatSubmit}><input value={chatInput} onChange={...}
```

### Task 2: Add Chat API Client
- **File:** `desktop/src/apiClient.ts`
- Add after `sendTaskMessage` (~line 514):

```typescript
export async function sendChatMessage(
  message: string,
  context?: { taskId?: string }
): Promise<{ taskId: string; agent: string; status: string }> {
  return postJson("/api/chat", { message, context });
}
```

### Task 3: Add Provider Priority to Settings
- **File:** `desktop/src/App.tsx` - find SettingsPage
- Add reorderable list for provider priority
- Store in workspace metadata: `{"provider_priority": ["claude", "codex", "copilot", "opencode"]}`
- Default priority from Settings tab order

### Task 4: Add /api/chat Endpoint
- **File:** `src/service/__init__.py` - add after `/api/providers` (~line 607)
- New endpoint: POST /api/chat

```python
if method == "POST" and parts == ["chat"]:
    return _handle_chat(storage, body)
```

Key functions needed:
- `_parse_chat_intent(message)` - create_task, query, approve
- `_get_provider_priority(storage, workspace_id)` - from settings
- `_select_available_provider(storage, workspace_id, priority)` - check health, skip rate-limited

### Task 5: Wire UI to API
- **File:** `desktop/src/App.tsx`
- Import `sendChatMessage`
- Update handleChatSubmit:

```typescript
const handleChatSubmit = async (e: FormEvent) => {
  e.preventDefault();
  if (!chatInput.trim()) return;
  const result = await sendChatMessage(chatInput, {});
  setChatInput("");
  setStatus(`Task ${result.taskId.slice(0,8)} dispatched to ${result.agent}`);
};
```

### Task 6: Rate Limit Tracking
- **File:** `src/service/__init__.py`
- In `_provider_check_config`: detect "rate limit" in CLI stderr
- On dispatch failure: update provider config with rate limit status
- Fallback logic already in `_select_available_provider`

## Testing Checklist

- [ ] UI: Chat composer sends messages
- [ ] Settings: Reorder providers, persists
- [ ] API: POST /api/chat creates task and dispatches
- [ ] Priority: Uses Settings priority order
- [ ] Fallback: Rate-limited provider skipped, next used

## Running

1. Start service: `cd Sarathi && python3 -m src.service`
2. Start UI: `cd desktop && npm run dev`
3. Test at http://localhost:5173