import { useState, useEffect } from "react";
import {
  getSarathiApiConfig,
  listWorkspaces,
  createWorkspace,
  type WorkspaceRecord,
} from "../apiClient";
import { workspace } from "../mockData";

interface WorkspacesHomeProps {
  setRoute?: (r: string) => void;
  setSelectedWorkspaceId?: (id: string) => void;
}

function mockToWorkspaceRecord(ws: typeof workspace): WorkspaceRecord {
  return {
    id: ws.id,
    name: ws.name,
    root_path: ws.repos[0]?.path ?? "",
    metadata: {
      repo_count: ws.repos.length,
      status: ws.status,
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

export default function WorkspacesHome({
  setRoute,
  setSelectedWorkspaceId,
}: WorkspacesHomeProps) {
  const apiConfigured = getSarathiApiConfig() !== null;
  const [workspaces, setWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [loading, setLoading] = useState(apiConfigured);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createPath, setCreatePath] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiConfigured) {
      setWorkspaces([mockToWorkspaceRecord(workspace)]);
      return;
    }
    setLoading(true);
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list.length > 0 ? list : [mockToWorkspaceRecord(workspace)]);
      })
      .catch(() => {
        setWorkspaces([mockToWorkspaceRecord(workspace)]);
      })
      .finally(() => setLoading(false));
  }, [apiConfigured]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createName.trim() || !createPath.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const ws = await createWorkspace(createName.trim(), createPath.trim());
      setWorkspaces((prev) => [...prev, ws]);
      setShowCreate(false);
      setCreateName("");
      setCreatePath("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create workspace");
    } finally {
      setCreating(false);
    }
  }

  function handleSelectWorkspace(ws: WorkspaceRecord) {
    if (setSelectedWorkspaceId) setSelectedWorkspaceId(ws.id);
    if (setRoute) setRoute("dashboard");
  }

  const repoCount = (ws: WorkspaceRecord): string => {
    const count = typeof ws.metadata?.repo_count === "number" ? ws.metadata.repo_count : 1;
    return `${count} repo${count !== 1 ? "s" : ""}`;
  };

  const taskCount = (ws: WorkspaceRecord & { task_count?: number }): number =>
    ws.task_count ?? 0;
  const activeCount = (ws: WorkspaceRecord & { active_count?: number }): number =>
    ws.active_count ?? 0;
  const isActive = (ws: WorkspaceRecord & { active_count?: number }): boolean =>
    (ws.active_count ?? 0) > 0;

  return (
    <div style={styles.page}>
      <div style={styles.container}>
        <div style={styles.header}>
          <div style={styles.headerLogo}>Sarathi</div>
          <h1 style={styles.headerTitle}>Your workspaces</h1>
        </div>

        {loading && (
          <p style={styles.loadingText}>Loading workspaces…</p>
        )}

        <div style={styles.grid}>
          {workspaces.map((ws) => {
            const active = isActive(ws as WorkspaceRecord & { active_count?: number });
            const tasks = taskCount(ws as WorkspaceRecord & { task_count?: number });
            const active_ = activeCount(ws as WorkspaceRecord & { active_count?: number });
            return (
              <WorkspaceCard
                key={ws.id}
                name={ws.name}
                taskCount={tasks}
                activeCount={active_}
                repoLabel={repoCount(ws)}
                isActive={active}
                onClick={() => handleSelectWorkspace(ws)}
              />
            );
          })}

          {/* Create workspace card */}
          {!showCreate ? (
            <button
              style={{ ...styles.card, ...styles.cardCreate }}
              onClick={() => setShowCreate(true)}
              aria-label="Create workspace"
            >
              <span style={styles.createIcon}>+</span>
              <span style={styles.createLabel}>Create workspace</span>
            </button>
          ) : (
            <div style={{ ...styles.card, ...styles.cardForm }}>
              <form onSubmit={(e) => { void handleCreate(e); }} style={styles.form}>
                <div style={styles.formTitle}>New workspace</div>
                <input
                  style={styles.input}
                  type="text"
                  placeholder="Name"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  autoFocus
                  disabled={creating}
                />
                <input
                  style={styles.input}
                  type="text"
                  placeholder="Path (e.g. /Users/you/project)"
                  value={createPath}
                  onChange={(e) => setCreatePath(e.target.value)}
                  disabled={creating}
                />
                {createError && (
                  <div style={styles.errorText}>{createError}</div>
                )}
                <div style={styles.formActions}>
                  <button
                    type="submit"
                    style={{ ...styles.btn, ...styles.btnPrimary }}
                    disabled={creating || !createName.trim() || !createPath.trim()}
                  >
                    {creating ? "Creating…" : "Create"}
                  </button>
                  <button
                    type="button"
                    style={styles.btn}
                    onClick={() => {
                      setShowCreate(false);
                      setCreateError(null);
                      setCreateName("");
                      setCreatePath("");
                    }}
                    disabled={creating}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface WorkspaceCardProps {
  name: string;
  taskCount: number;
  activeCount: number;
  repoLabel: string;
  isActive: boolean;
  onClick: () => void;
}

function WorkspaceCard({
  name,
  taskCount,
  activeCount,
  repoLabel,
  isActive,
  onClick,
}: WorkspaceCardProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      style={{
        ...styles.card,
        ...(hovered ? styles.cardHover : {}),
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
    >
      <div style={styles.cardName}>
        <span
          style={{
            ...styles.dot,
            backgroundColor: isActive
              ? "var(--s-green)"
              : "var(--s-faint)",
          }}
        />
        {name}
      </div>
      <div style={styles.cardMeta}>
        <span>{taskCount} task{taskCount !== 1 ? "s" : ""}</span>
        {activeCount > 0 && (
          <span style={styles.activeBadge}>{activeCount} active</span>
        )}
        {activeCount === 0 && (
          <span style={styles.idleText}>idle</span>
        )}
      </div>
      <div style={styles.repoRow}>{repoLabel}</div>
    </button>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    backgroundColor: "var(--s-canvas)",
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "center",
    padding: "48px 24px",
  },
  container: {
    width: "100%",
    maxWidth: 800,
  },
  header: {
    marginBottom: 32,
  },
  headerLogo: {
    fontSize: 13,
    fontWeight: 600,
    color: "var(--s-accent)",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    marginBottom: 8,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 700,
    color: "var(--s-ink)",
    margin: 0,
  },
  loadingText: {
    color: "var(--s-muted)",
    fontSize: 14,
    marginBottom: 16,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 16,
  },
  card: {
    background: "var(--s-surface)",
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius)",
    padding: "16px",
    textAlign: "left",
    cursor: "pointer",
    transition: "box-shadow 0.15s ease, border-color 0.15s ease",
    display: "flex",
    flexDirection: "column",
    gap: 8,
    // Reset button styles
    font: "inherit",
    color: "inherit",
    outline: "none",
  },
  cardHover: {
    boxShadow: "var(--s-shadow)",
    borderColor: "var(--s-border-strong)",
  },
  cardCreate: {
    alignItems: "center",
    justifyContent: "center",
    color: "var(--s-muted)",
    border: "1.5px dashed var(--s-border-strong)",
    minHeight: 100,
  },
  cardForm: {
    cursor: "default",
    minHeight: 120,
  },
  createIcon: {
    fontSize: 22,
    lineHeight: 1,
    marginBottom: 4,
  },
  createLabel: {
    fontSize: 13,
    fontWeight: 500,
  },
  cardName: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontWeight: 600,
    fontSize: 14,
    color: "var(--s-ink)",
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    display: "inline-block",
    flexShrink: 0,
  },
  cardMeta: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 13,
    color: "var(--s-muted)",
  },
  activeBadge: {
    background: "var(--s-green-bg)",
    color: "var(--s-green)",
    fontSize: 11,
    fontWeight: 600,
    borderRadius: 4,
    padding: "2px 6px",
  },
  idleText: {
    color: "var(--s-faint)",
    fontSize: 12,
  },
  repoRow: {
    fontSize: 12,
    color: "var(--s-faint)",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    width: "100%",
  },
  formTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: "var(--s-ink)",
    marginBottom: 4,
  },
  input: {
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius-sm)",
    padding: "6px 10px",
    fontSize: 13,
    color: "var(--s-ink)",
    background: "var(--s-canvas)",
    outline: "none",
    width: "100%",
    boxSizing: "border-box",
  },
  errorText: {
    color: "var(--s-red)",
    fontSize: 12,
  },
  formActions: {
    display: "flex",
    gap: 6,
    marginTop: 4,
  },
  btn: {
    border: "1px solid var(--s-border)",
    borderRadius: "var(--s-radius-sm)",
    padding: "5px 12px",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
    background: "var(--s-surface)",
    color: "var(--s-ink)",
    font: "inherit",
  },
  btnPrimary: {
    background: "var(--s-accent)",
    color: "#fff",
    border: "none",
  },
};
