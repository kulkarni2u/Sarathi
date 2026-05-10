import { useMemo, useState, type CSSProperties } from "react";
import { Card, Pill } from "./ui";
import type { TaskPanelEntry } from "../apiClient";

interface TaskPanelTimelineProps {
  entries: TaskPanelEntry[];
  loading?: boolean;
  emptyLabel?: string;
}

const toneForKind: Record<TaskPanelEntry["kind"], "active" | "healthy" | "warning" | "blocked" | "draft" | "default"> = {
  human_message: "active",
  agent_update: "healthy",
  blocked: "blocked",
  unblocked: "healthy",
  claimed: "active",
  in_progress: "active",
  review: "warning",
  handoff: "draft",
  completion: "healthy",
  evidence: "default",
  system_note: "default",
};

const iconForKind: Record<TaskPanelEntry["kind"], string> = {
  human_message: "●",
  agent_update: "◆",
  blocked: "■",
  unblocked: "○",
  claimed: "▶",
  in_progress: "◐",
  review: "◈",
  handoff: "⤳",
  completion: "✓",
  evidence: "◇",
  system_note: "○",
};

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function formatRelativeTime(iso: string): string {
  try {
    const date = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function sourceInitial(source: string): string {
  if (source === "user") return "U";
  if (source === "assistant") return "S";
  return source.charAt(0).toUpperCase();
}

function groupEntriesByTime(entries: TaskPanelEntry[]): Map<string, TaskPanelEntry[]> {
  const groups = new Map<string, TaskPanelEntry[]>();
  for (const entry of entries) {
    const date = new Date(entry.created_at);
    const bucket = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    const existing = groups.get(bucket) ?? [];
    existing.push(entry);
    groups.set(bucket, existing);
  }
  return groups;
}

export default function TaskPanelTimeline({
  entries,
  loading = false,
  emptyLabel = "No task activity yet.",
}: TaskPanelTimelineProps) {
  const [expandedHistory, setExpandedHistory] = useState(false);

  const sortedEntries = useMemo(() => {
    return [...entries].sort((a, b) => {
      if (a.created_at === b.created_at) return a.id.localeCompare(b.id);
      return b.created_at.localeCompare(a.created_at);
    });
  }, [entries]);

  const groupedEntries = useMemo(() => groupEntriesByTime(sortedEntries), [sortedEntries]);

  const pinnedEntries = useMemo(() => {
    return sortedEntries.filter(
      (e) => e.kind === "blocked" || e.kind === "review" || e.kind === "completion" || e.kind === "handoff"
    );
  }, [sortedEntries]);

  const feedEntries = useMemo(() => {
    return sortedEntries.filter(
      (e) => e.kind !== "blocked" && e.kind !== "review" && e.kind !== "completion" && e.kind !== "handoff"
    );
  }, [sortedEntries]);

  const pinnedCount = pinnedEntries.length;
  const feedCount = feedEntries.length;
  const displayCount = expandedHistory ? sortedEntries.length : 8;

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>
          <span style={styles.spinner} />
          Loading task panel…
        </div>
      </div>
    );
  }

  if (sortedEntries.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.empty}>
          <div style={styles.emptyDot} />
          <p style={styles.emptyLabel}>{emptyLabel}</p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {pinnedCount > 0 && (
        <div style={styles.pinnedSection}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionLabel}>Key Events</span>
            <Pill tone="active">{pinnedCount}</Pill>
          </div>
          <div style={styles.pinnedFeed}>
            {sortedEntries
              .filter(
                (e) =>
                  e.kind === "blocked" ||
                  e.kind === "review" ||
                  e.kind === "completion" ||
                  e.kind === "handoff"
              )
              .slice(0, expandedHistory ? undefined : 4)
              .map((entry) => (
                <div key={entry.id} style={styles.pinnedItem}>
                  <span
                    style={{
                      ...styles.pinnedDot,
                      background:
                        entry.kind === "blocked"
                          ? "var(--status-red-fg)"
                          : entry.kind === "completion" || entry.kind === "handoff"
                          ? "var(--status-green-fg)"
                          : "var(--status-amber-fg)",
                    }}
                  />
                  <div style={styles.pinnedContent}>
                    <div style={styles.pinnedMeta}>
                      <span style={styles.pinnedSource}>{sourceInitial(entry.source)}</span>
                      <span style={styles.pinnedTime}>{formatTime(entry.created_at)}</span>
                    </div>
                    <div style={styles.pinnedSummary}>{entry.summary}</div>
                    {entry.target && <span style={styles.pinnedTarget}>→ {entry.target}</span>}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      <div style={styles.feedSection}>
        {!expandedHistory && pinnedCount > 0 && feedCount > 0 && (
          <div style={styles.feedHeader}>
            <span style={styles.sectionLabel}>Activity Feed</span>
            <span style={styles.feedCount}>{feedCount} entries</span>
          </div>
        )}

        {(expandedHistory || pinnedCount === 0) && (
          <div style={styles.feedList}>
            {sortedEntries
              .slice(0, displayCount)
              .filter(
                (e) =>
                  e.kind !== "blocked" &&
                  e.kind !== "review" &&
                  e.kind !== "completion" &&
                  e.kind !== "handoff"
              )
              .map((entry) => (
                <div key={entry.id} style={styles.feedItem}>
                  <span style={styles.feedIcon}>{iconForKind[entry.kind]}</span>
                  <span style={styles.feedSource}>{sourceInitial(entry.source)}</span>
                  <span style={{ ...styles.feedDot, background: entry.kind === "blocked" ? "var(--status-red-fg)" : entry.kind === "unblocked" || entry.kind === "completion" ? "var(--status-green-fg)" : entry.kind === "in_progress" || entry.kind === "claimed" ? "var(--status-blue-fg)" : "var(--faint)" }} />
                  <div style={styles.feedContent}>
                    <span style={styles.feedSummary}>{entry.summary}</span>
                    {entry.target && <span style={styles.feedTarget}>→ {entry.target}</span>}
                  </div>
                  <span style={styles.feedTime}>{formatRelativeTime(entry.created_at)}</span>
                </div>
              ))}
          </div>
        )}
      </div>

      {sortedEntries.length > displayCount && (
        <button
          style={styles.expandButton}
          onClick={() => setExpandedHistory(!expandedHistory)}
        >
          {expandedHistory ? "Show less" : `Show ${sortedEntries.length - displayCount} more`}
        </button>
      )}
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  loading: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: 16,
    color: "var(--muted)",
    fontSize: "0.83rem",
  },
  spinner: {
    width: 14,
    height: 14,
    border: "2px solid var(--border)",
    borderTopColor: "var(--ink)",
    borderRadius: "50%",
    animation: "spin 0.6s linear infinite",
  },
  empty: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    padding: 24,
    textAlign: "center",
  },
  emptyDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "var(--faint)",
  },
  emptyLabel: {
    margin: 0,
    color: "var(--muted)",
    fontSize: "0.83rem",
  },
  pinnedSection: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  sectionLabel: {
    fontSize: "0.7rem",
    fontWeight: 600,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  pinnedFeed: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  pinnedItem: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    padding: "6px 8px",
    borderRadius: "var(--radius-sm)",
    background: "var(--hover)",
  },
  pinnedDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    marginTop: 4,
    flexShrink: 0,
  },
  pinnedContent: {
    flex: 1,
    minWidth: 0,
  },
  pinnedMeta: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 2,
  },
  pinnedSource: {
    fontSize: "0.65rem",
    fontWeight: 700,
    color: "var(--muted)",
    letterSpacing: "0.04em",
  },
  pinnedTime: {
    fontSize: "0.7rem",
    color: "var(--faint)",
    fontFamily: "'SF Mono', monospace",
  },
  pinnedSummary: {
    fontSize: "0.82rem",
    color: "var(--ink)",
    lineHeight: 1.4,
  },
  pinnedTarget: {
    display: "block",
    marginTop: 2,
    fontSize: "0.75rem",
    color: "var(--muted)",
  },
  feedSection: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  feedHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "4px 0",
  },
  feedCount: {
    fontSize: "0.7rem",
    color: "var(--faint)",
  },
  feedList: {
    display: "flex",
    flexDirection: "column",
    gap: 1,
  },
  feedItem: {
    display: "grid",
    gridTemplateColumns: "auto auto auto 1fr auto",
    gap: 6,
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: "var(--radius-sm)",
    fontSize: "0.78rem",
  },
  feedIcon: {
    fontSize: "0.65rem",
    color: "var(--faint)",
    textAlign: "center",
    width: 14,
  },
  feedSource: {
    fontSize: "0.65rem",
    fontWeight: 700,
    color: "var(--muted)",
    letterSpacing: "0.04em",
    width: 14,
  },
  feedDot: {
    width: 5,
    height: 5,
    borderRadius: "50%",
    flexShrink: 0,
  },
  feedContent: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    minWidth: 0,
  },
  feedSummary: {
    color: "var(--text)",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    maxWidth: 180,
  },
  feedTarget: {
    fontSize: "0.7rem",
    color: "var(--muted)",
    whiteSpace: "nowrap",
  },
  feedTime: {
    fontSize: "0.7rem",
    color: "var(--faint)",
    textAlign: "right",
    minWidth: 50,
  },
  expandButton: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "6px 12px",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    background: "transparent",
    color: "var(--muted)",
    fontSize: "0.78rem",
    fontWeight: 500,
    cursor: "pointer",
    marginTop: 4,
  },
};
