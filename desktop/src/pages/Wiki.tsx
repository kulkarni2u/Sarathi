import { useEffect, useState } from "react";

import {
  getSarathiApiConfig,
  getWiki,
  getWikiPage,
  saveWikiPage,
  type WikiData,
} from "../apiClient";
import { Pill } from "../components/ui";

interface WikiProps {
  workspaceId: string | null;
}

const mockWikiPages: WikiData = {
  workspace_id: "",
  pages: [{ name: "README", path: "README.md", exists: true }],
};

const mockPageContent: Record<string, string> = {
  README: "# Workspace Wiki\n\nThis is a demo wiki surface. Connect the Sarathi service to inspect persisted workspace pages.",
};

function pageIdFromPath(path: string) {
  return path.replace(/\.md$/i, "");
}

export default function Wiki({ workspaceId }: WikiProps) {
  const [wikiData, setWikiData] = useState<WikiData | null>(null);
  const [selectedPage, setSelectedPage] = useState<string | null>(null);
  const [pageContent, setPageContent] = useState<string | null>(null);
  const [draftContent, setDraftContent] = useState("");
  const [newPageName, setNewPageName] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("Loading workspace wiki.");
  const apiConfigured = getSarathiApiConfig() !== null;

  useEffect(() => {
    if (!workspaceId) {
      setWikiData(null);
      setSelectedPage(null);
      setLoading(false);
      setStatus("Select a workspace to inspect its wiki.");
      return;
    }
    if (!apiConfigured) {
      setWikiData(mockWikiPages);
      setSelectedPage(pageIdFromPath(mockWikiPages.pages[0].path));
      setLoading(false);
      setStatus("Demo wiki. Connect the Sarathi service for persisted workspace docs.");
      return;
    }
    setLoading(true);
    getWiki(workspaceId)
      .then((next) => {
        setWikiData(next);
        setSelectedPage(next.pages[0] ? pageIdFromPath(next.pages[0].path) : null);
        setStatus(`${next.pages.length} wiki page${next.pages.length === 1 ? "" : "s"} loaded.`);
      })
      .catch((error) => {
        setWikiData(null);
        setSelectedPage(null);
        setStatus(error instanceof Error ? error.message : "Wiki load failed.");
      })
      .finally(() => setLoading(false));
  }, [workspaceId, apiConfigured]);

  useEffect(() => {
    if (!selectedPage) {
      setPageContent(null);
      setDraftContent("");
      return;
    }
    if (!workspaceId || !apiConfigured) {
      const nextContent = mockPageContent[selectedPage] ?? "No demo content available for this page.";
      setPageContent(nextContent);
      setDraftContent(nextContent);
      return;
    }
    getWikiPage(workspaceId, selectedPage)
      .then((page) => {
        setPageContent(page.content);
        setDraftContent(page.content);
      })
      .catch((error) => {
        const nextError = error instanceof Error ? error.message : "Wiki page load failed.";
        setPageContent(nextError);
        setDraftContent(nextError);
      });
  }, [selectedPage, workspaceId, apiConfigured]);

  async function handleSave(pageId: string) {
    if (!workspaceId) return;
    if (!apiConfigured) {
      setStatus("Connect the Sarathi service to persist wiki pages.");
      return;
    }
    const trimmedPage = pageId.trim();
    if (!trimmedPage) {
      setStatus("Page name is required.");
      return;
    }
    setSaving(true);
    try {
      const saved = await saveWikiPage(workspaceId, {
        page: trimmedPage,
        content: draftContent,
      });
      setPageContent(saved.content);
      setDraftContent(saved.content);
      const nextPagePath = saved.path.split("/wiki/").pop() ?? `${trimmedPage}.md`;
      const nextPageId = pageIdFromPath(nextPagePath);
      setSelectedPage(nextPageId);
      setNewPageName("");
      const nextWiki = await getWiki(workspaceId);
      setWikiData(nextWiki);
      setStatus(`Saved wiki page: ${trimmedPage}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Wiki save failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>Loading wiki...</div>;
  }

  if (!wikiData) {
    return <div style={{ padding: 32, color: "var(--muted)" }}>{status}</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100%", overflow: "hidden" }}>
      <aside style={{ borderRight: "1px solid var(--border)", padding: 16, overflow: "auto" }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: "0.86rem", margin: 0, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Wiki pages
          </h3>
          <p style={{ margin: "6px 0 0", fontSize: "0.72rem", color: "var(--faint)" }}>{status}</p>
        </div>
        <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
          <input
            value={newPageName}
            onChange={(event) => setNewPageName(event.target.value)}
            placeholder="guides/new-page"
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--surface)",
              color: "var(--ink)",
            }}
          />
          <button
            className="secondary-action"
            onClick={() => {
              const nextPage = newPageName.trim();
              if (!nextPage) {
                setStatus("Enter a page name to create a wiki page.");
                return;
              }
              setSelectedPage(nextPage);
              setPageContent("");
              setDraftContent("");
              setStatus(`Creating draft for ${nextPage}.`);
            }}
          >
            New page
          </button>
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {wikiData.pages.map((page) => {
            const pageId = pageIdFromPath(page.path);
            const isSelected = selectedPage === pageId;
            return (
              <button
                key={page.path}
                onClick={() => setSelectedPage(pageId)}
                style={{
                  textAlign: "left",
                  padding: "10px 12px",
                  background: isSelected ? "var(--accent-bg)" : "var(--surface)",
                  border: "1px solid",
                  borderColor: isSelected ? "var(--accent)" : "var(--border)",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  color: isSelected ? "var(--accent)" : "var(--ink)",
                }}
              >
                <div style={{ fontSize: "0.82rem", fontWeight: 500 }}>{page.name}</div>
                <div style={{ marginTop: 3, fontSize: "0.7rem", color: "var(--muted)" }}>{page.path}</div>
              </button>
            );
          })}
        </div>
        {wikiData.pages.length === 0 && (
          <p style={{ fontSize: "0.78rem", color: "var(--muted)" }}>No wiki pages found.</p>
        )}
      </aside>

      <main style={{ padding: 20, overflow: "auto" }}>
        {selectedPage ? (
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{selectedPage}</h2>
              <Pill tone="active">editable</Pill>
            </div>
            <textarea
              value={draftContent}
              onChange={(event) => setDraftContent(event.target.value)}
              spellCheck={false}
              style={{
                minHeight: 420,
                width: "100%",
                resize: "vertical",
                fontSize: "0.85rem",
                lineHeight: 1.6,
                fontFamily: "ui-monospace, SFMono-Regular, monospace",
                background: "var(--surface)",
                padding: 16,
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border)",
                color: "var(--ink)",
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="primary" onClick={() => void handleSave(selectedPage)} disabled={saving}>
                {saving ? "Saving…" : "Save page"}
              </button>
              <button
                className="secondary-action"
                onClick={() => setDraftContent(pageContent ?? "")}
                disabled={saving}
              >
                Reset changes
              </button>
            </div>
          </div>
        ) : (
          <p style={{ color: "var(--muted)" }}>Select a wiki page to inspect its content.</p>
        )}
      </main>
    </div>
  );
}
