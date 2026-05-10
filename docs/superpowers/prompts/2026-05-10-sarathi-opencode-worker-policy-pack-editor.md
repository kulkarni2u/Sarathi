# OpenCode Worker Prompt: Policy Pack Editor UI

Date: 2026-05-10
Complexity: MEDIUM
Orchestrator: Sarathi (Claude)

## Task

Add a policy pack editor surface to the Sarathi desktop Settings page.

## Context

The backend already exposes:

- `GET /api/workspaces/:id/policy-pack` → returns `{ files: [{ name, content }] }`
- `PUT /api/workspaces/:id/policy-pack/:filename` → body `{ content }`, saves the file

These routes are implemented in `src/service/__init__.py` (search for `_get_policy_pack` and `_put_policy_pack_file`).

The desktop `Settings.tsx` currently has:
- Readiness card
- Repository safety (editable select + save)
- Approval workflow (editable select + threshold + save)
- AI providers (expand/test per provider)
- Agent dispatch order (reorder pills)

No policy pack editor exists yet.

## Files to Modify

- `desktop/src/apiClient.ts` — add two client functions
- `desktop/src/pages/Settings.tsx` — add a new `<section>` for the policy pack editor

## Step 1: Add client functions in `apiClient.ts`

Add after the existing `listProviders` function:

```typescript
export type PolicyPackFile = {
  name: string;
  content: string;
};

export async function getWorkspacePolicyPack(
  workspaceId: string,
): Promise<PolicyPackFile[]> {
  const data = await getJson<{ files: PolicyPackFile[] }>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/policy-pack`,
  );
  return data.files;
}

export async function putWorkspacePolicyPackFile(
  workspaceId: string,
  filename: string,
  content: string,
): Promise<void> {
  await putJson<Record<string, unknown>>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/policy-pack/${encodeURIComponent(filename)}`,
    { content },
  );
}
```

**Important:** The backend route is `PUT` (not PATCH) — confirmed at line ~936 of `src/service/__init__.py`. You must add a `putJson` helper to `apiClient.ts` — it does not exist yet. Add it after `patchJson`, matching the exact same pattern:

```typescript
async function putJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const config = getSarathiApiConfig();
  if (!config) {
    throw new Error("Sarathi local service is not configured for this desktop build.");
  }
  const response = await fetch(`${config.baseUrl}${path}`, {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new Error(envelope.error.message);
  }
  return envelope.data;
}
```

## Step 2: Add state and load logic in `Settings.tsx`

Import the new client functions at the top. Add state:

```typescript
const [policyFiles, setPolicyFiles] = useState<PolicyPackFile[]>([]);
const [expandedPolicyFile, setExpandedPolicyFile] = useState<string | null>(null);
const [policyDrafts, setPolicyDrafts] = useState<Record<string, string>>({});
const [savingPolicyFile, setSavingPolicyFile] = useState<string | null>(null);
const [loadingPolicy, setLoadingPolicy] = useState(false);
```

In the `loadSettingsProviders` async function (already exists in the useEffect), after setting providers, add:

```typescript
setLoadingPolicy(true);
try {
  const files = await getWorkspacePolicyPack(activeWorkspaceId);
  if (!cancelled) {
    setPolicyFiles(files);
    setPolicyDrafts(Object.fromEntries(files.map((f) => [f.name, f.content])));
  }
} catch {
  // policy pack unavailable — not a blocking error
} finally {
  if (!cancelled) setLoadingPolicy(false);
}
```

Add save function:

```typescript
async function savePolicyFile(filename: string) {
  if (!apiConfigured || !workspaceId) return;
  setSavingPolicyFile(filename);
  try {
    await putWorkspacePolicyPackFile(workspaceId, filename, policyDrafts[filename] ?? "");
    setPolicyFiles((current) =>
      current.map((f) => f.name === filename ? { ...f, content: policyDrafts[filename] ?? "" } : f),
    );
    setSettingsStatus(`${filename} saved.`);
  } catch (error) {
    setSettingsStatus(error instanceof Error ? error.message : `Save failed for ${filename}.`);
  } finally {
    setSavingPolicyFile(null);
  }
}
```

## Step 3: Add the UI section in `Settings.tsx`

Add a new `<section className="panel" style={{ gridColumn: "1 / -1" }}>` block below the Agent dispatch order section (which is the last section before the closing `</div>`):

```tsx
<section className="panel" style={{ gridColumn: "1 / -1" }}>
  <h2 style={{ marginBottom: 4 }}>Policy pack</h2>
  <p style={{ fontSize: "0.83rem", color: "var(--muted)", marginBottom: 16 }}>
    Policy files control how Sarathi routes, builds, reviews, and escalates tasks.
    {!workspaceId && " Select a workspace to view policy files."}
  </p>
  {loadingPolicy && (
    <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>Loading policy files…</div>
  )}
  {!loadingPolicy && policyFiles.length === 0 && workspaceId && (
    <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>No policy pack found for this workspace.</div>
  )}
  {policyFiles.map((file) => {
    const isExpanded = expandedPolicyFile === file.name;
    const isDirty = policyDrafts[file.name] !== file.content;
    return (
      <div key={file.name} style={{ marginBottom: 8, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
        <div
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", cursor: "pointer" }}
          onClick={() => setExpandedPolicyFile(isExpanded ? null : file.name)}
        >
          <span style={{ fontSize: "0.85rem", fontWeight: 500 }}>{file.name}</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {isDirty && <span style={{ fontSize: "0.68rem", color: "var(--amber)" }}>unsaved</span>}
            <span style={{ color: "var(--muted)", fontSize: "0.7rem" }}>{isExpanded ? "▲" : "▼"}</span>
          </div>
        </div>
        {isExpanded && (
          <div style={{ padding: "0 14px 14px" }}>
            <textarea
              aria-label={`Edit ${file.name}`}
              value={policyDrafts[file.name] ?? ""}
              onChange={(e) => setPolicyDrafts((d) => ({ ...d, [file.name]: e.target.value }))}
              rows={Math.min(30, Math.max(8, (policyDrafts[file.name] ?? "").split("\n").length + 2))}
              style={{
                width: "100%",
                fontFamily: "monospace",
                fontSize: "0.78rem",
                padding: "8px 10px",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--canvas)",
                resize: "vertical",
                boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
              <button
                onClick={() => void savePolicyFile(file.name)}
                disabled={savingPolicyFile !== null || !isDirty}
                style={{ fontSize: "0.75rem", padding: "4px 10px" }}
              >
                {savingPolicyFile === file.name ? "Saving…" : "Save"}
              </button>
              <button
                onClick={() => setPolicyDrafts((d) => ({ ...d, [file.name]: file.content }))}
                disabled={!isDirty}
                style={{ fontSize: "0.75rem", padding: "4px 10px" }}
              >
                Revert
              </button>
            </div>
          </div>
        )}
      </div>
    );
  })}
</section>
```

## Step 4: Verify

```bash
npm --prefix desktop run build
```

Expected: ✓ built, no TypeScript errors.

## Step 5: Commit

```bash
git add desktop/src/apiClient.ts desktop/src/pages/Settings.tsx
git commit -m "feat: add policy pack editor to Settings"
```

## Constraints

- Do NOT modify `src/service/__init__.py` — the backend routes already exist.
- Do NOT modify any other pages or components.
- Do NOT add dependencies.
- Keep the section style consistent with the existing Agent dispatch order section (same `gridColumn: "1 / -1"`, same panel class).
