import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../../api/client";
import type { AnyRecord } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import "./Wiki.css";

/**
 * Wiki — workspace knowledge pages (human-authored + generated, with
 * proposal-backed edits).
 * Route: /wiki
 *
 * Data sources:
 *  - GET /workspaces/{id}/wiki        → page index (left nav)
 *  - GET /workspaces/{id}/wiki/{page} → page content (right pane)
 *
 * The service's current wiki projection returns a fairly minimal shape
 * (`{ pages: [{ name, path, exists }] }` for the index and
 * `{ page, content, path }` for a page). Provenance / generated-vs-human
 * markers are read defensively from optional fields so this view keeps
 * working if the projection is enriched later.
 */

interface WikiPageEntry {
  name: string;
  path: string;
  exists?: boolean;
  generated?: boolean;
  humanAuthored?: boolean;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asBool(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

/** Normalize a raw wiki index entry into a typed shape, reading defensively
 * since the projection's `additionalProperties: true` shape may evolve. */
function normalizeEntry(raw: unknown, index: number): WikiPageEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as AnyRecord;
  const path = asString(rec.path) ?? asString(rec.slug) ?? asString(rec.id);
  const name = asString(rec.name) ?? asString(rec.title) ?? path ?? `Page ${index + 1}`;
  if (!path && !name) return null;

  // Provenance markers — several possible field names depending on how the
  // projection evolves (generated vs. human-authored content).
  const provenance = (rec.provenance as AnyRecord | undefined) ?? undefined;
  const provenanceSource = asString(provenance?.source) ?? asString(rec.source) ?? asString(rec.authored_by);
  let generated: boolean | undefined = asBool(rec.generated) ?? asBool(rec.is_generated);
  let humanAuthored: boolean | undefined = asBool(rec.human_authored) ?? asBool(rec.is_human_authored);
  if (generated === undefined && provenanceSource) {
    generated = provenanceSource.toLowerCase().includes("gen");
  }
  if (humanAuthored === undefined && provenanceSource) {
    humanAuthored = provenanceSource.toLowerCase().includes("human");
  }

  return {
    name,
    path: path ?? name,
    exists: asBool(rec.exists),
    generated,
    humanAuthored,
  };
}

function pageIcon(entry: WikiPageEntry): string {
  const label = entry.name.toLowerCase();
  if (label.includes("architect")) return "\u{1F4D0}"; // 📐
  if (label.includes("setup") || label.includes("develop")) return "\u{1F680}"; // 🚀
  if (label.includes("standard") || label.includes("coding")) return "\u{1F9ED}"; // 🧭
  if (label.includes("provider") || label.includes("payment")) return "\u{1F50C}"; // 🔌
  if (label.includes("data")) return "\u{1F5C4}️"; // 🗄️
  if (label.includes("runbook")) return "\u{1F4CB}"; // 📋
  return "\u{1F4C4}"; // 📄
}

/** Very small markdown-ish renderer: headings (`#`/`##`/`###`), blank-line
 * paragraphs, and inline `code` spans. Good enough for wiki body text
 * without pulling in a markdown dependency. */
function renderBody(content: string) {
  const lines = content.split(/\r?\n/);
  const blocks: { type: "h1" | "h2" | "h3" | "p"; text: string }[] = [];
  let buffer: string[] = [];

  const flush = () => {
    const text = buffer.join(" ").trim();
    if (text) blocks.push({ type: "p", text });
    buffer = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("### ")) {
      flush();
      blocks.push({ type: "h3", text: trimmed.slice(4) });
    } else if (trimmed.startsWith("## ")) {
      flush();
      blocks.push({ type: "h3", text: trimmed.slice(3) });
    } else if (trimmed.startsWith("# ")) {
      flush();
      blocks.push({ type: "h2", text: trimmed.slice(2) });
    } else if (trimmed === "") {
      flush();
    } else {
      buffer.push(trimmed);
    }
  }
  flush();

  return blocks.map((block, idx) => {
    const inline = renderInline(block.text);
    switch (block.type) {
      case "h2":
        return <h2 key={idx}>{inline}</h2>;
      case "h3":
        return <h3 key={idx}>{inline}</h3>;
      default:
        return <p key={idx}>{inline}</p>;
    }
  });
}

/** Render `` `code` `` spans inline within a line of text. */
function renderInline(text: string) {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return <code key={idx}>{part.slice(1, -1)}</code>;
    }
    return <span key={idx}>{part}</span>;
  });
}

export default function Wiki() {
  const { currentWorkspace, currentWorkspaceId, serviceStatus } = useWorkspace();

  const [pages, setPages] = useState<WikiPageEntry[] | null>(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [pageData, setPageData] = useState<AnyRecord | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Load the page index whenever the workspace changes.
  useEffect(() => {
    if (!currentWorkspaceId) {
      setPages(null);
      setSelectedPath(null);
      return;
    }
    const controller = new AbortController();
    setIndexLoading(true);
    setIndexError(null);
    api
      .getWiki(currentWorkspaceId, controller.signal)
      .then((data) => {
        const rawPages = (data as AnyRecord)?.pages;
        const list = Array.isArray(rawPages)
          ? rawPages.map((p, i) => normalizeEntry(p, i)).filter((p): p is WikiPageEntry => p !== null)
          : [];
        setPages(list);
        setSelectedPath((prev) => {
          if (prev && list.some((p) => p.path === prev)) return prev;
          return list[0]?.path ?? null;
        });
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setPages([]);
        setSelectedPath(null);
        setIndexError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIndexLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId]);

  // Load the selected page's content.
  useEffect(() => {
    if (!currentWorkspaceId || !selectedPath) {
      setPageData(null);
      return;
    }
    const controller = new AbortController();
    setPageLoading(true);
    setPageError(null);
    api
      .getWikiPage(currentWorkspaceId, selectedPath, controller.signal)
      .then((data) => setPageData(data as AnyRecord))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setPageData(null);
        setPageError(err instanceof ApiClientError ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setPageLoading(false);
      });
    return () => controller.abort();
  }, [currentWorkspaceId, selectedPath]);

  const selectedEntry = useMemo(
    () => pages?.find((p) => p.path === selectedPath) ?? null,
    [pages, selectedPath],
  );

  const content = asString(pageData?.content) ?? "";
  const lastEditedBy = asString(pageData?.last_edited_by) ?? asString(pageData?.author);
  const lastEditedAt = asString(pageData?.updated_at) ?? asString(pageData?.last_edited_at);
  const linkedTasks = Array.isArray(pageData?.linked_tasks) ? (pageData?.linked_tasks as unknown[]) : undefined;

  return (
    <section>
      <div className="ph">
        <div className="row">
          <div>
            <h1>Wiki</h1>
            <p>
              {currentWorkspace?.name ?? currentWorkspaceId ?? "no workspace selected"} · workspace knowledge ·
              approved &amp; proposal-backed edits
            </p>
          </div>
          <div className="grow" />
          <button className="btn" disabled title="Proposing edits is not available in M1">
            Propose edit
          </button>
        </div>
      </div>

      {serviceStatus === "offline" && (
        <div className="banner offline">⚠ Service offline — wiki content may be unavailable.</div>
      )}

      {!currentWorkspaceId && (
        <div className="card2" style={{ padding: 18, color: "var(--muted)" }}>
          {serviceStatus === "connecting" ? "Loading workspaces…" : "No workspace selected."}
        </div>
      )}

      {currentWorkspaceId && (
        <div className="wiki-layout">
          <nav className="wiki-nav">
            {indexLoading && <div className="wiki-loading">Loading pages…</div>}
            {!indexLoading && indexError && (
              <div className="wiki-empty">Failed to load wiki index: {indexError}</div>
            )}
            {!indexLoading && !indexError && pages && pages.length === 0 && (
              <div className="wiki-empty">No wiki pages yet for this workspace.</div>
            )}
            {!indexLoading &&
              !indexError &&
              pages &&
              pages.map((entry) => (
                <button
                  key={entry.path}
                  className={`wiki-item${entry.path === selectedPath ? " on" : ""}`}
                  onClick={() => setSelectedPath(entry.path)}
                  title={entry.path}
                >
                  <span className="wiki-icon">{pageIcon(entry)}</span>
                  <span className="wiki-title">{entry.name}</span>
                  {entry.humanAuthored && <span className="wiki-tag human">human</span>}
                  {!entry.humanAuthored && entry.generated && <span className="wiki-tag">gen</span>}
                </button>
              ))}
          </nav>

          <div className="wiki-doc">
            {!selectedPath && !indexLoading && (
              <div className="wiki-empty">Select a page from the list to view its content.</div>
            )}

            {selectedPath && pageLoading && <div className="wiki-loading">Loading page…</div>}

            {selectedPath && !pageLoading && pageError && (
              <div className="banner offline">⚠ Failed to load page: {pageError}</div>
            )}

            {selectedPath && !pageLoading && !pageError && pageData && (
              <>
                <h2>{selectedEntry?.name ?? asString(pageData.page) ?? selectedPath}</h2>
                <div className="wiki-provenance">
                  {lastEditedBy ? `Last edited by ${lastEditedBy}` : "Provenance unavailable"}
                  {lastEditedAt ? ` · ${lastEditedAt}` : ""}
                  {selectedEntry?.humanAuthored
                    ? " · human-authored"
                    : selectedEntry?.generated
                      ? " · generated"
                      : ""}
                  {linkedTasks && linkedTasks.length > 0 ? ` · linked to ${linkedTasks.length} task(s)` : ""}
                </div>
                <div className="wiki-body">
                  {content.trim().length > 0 ? (
                    renderBody(content)
                  ) : (
                    <p style={{ color: "var(--muted)" }}>This page has no content yet.</p>
                  )}
                </div>
              </>
            )}

            {selectedPath && !pageLoading && !pageError && !pageData && (
              <div className="wiki-empty">No content available for this page.</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
