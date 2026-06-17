import { useTheme } from "../context/ThemeContext";

export interface TopBarProps {
  /** Page title / breadcrumb shown in the top bar (e.g. "Dashboard"). */
  title: string;
  /**
   * Number of items "needing" operator attention (approvals, blocked tasks,
   * etc). When 0 or undefined, the "Needs you" pill is hidden.
   * Later workers should wire this to live data (e.g. task-dashboard counts).
   */
  needsYouCount?: number;
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

function NeedsYouIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8" />
    </svg>
  );
}

export function TopBar({ title, needsYouCount = 0 }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="top">
      <div className="ttl">
        <MenuIcon />
        <span className="crumb">{title}</span>
      </div>
      <div className="grow" />
      {needsYouCount > 0 && (
        <button className="needs">
          <NeedsYouIcon /> Needs you <span className="n">{needsYouCount}</span>
        </button>
      )}
      <button className="iconbtn" title="Toggle theme" onClick={toggleTheme}>
        {theme === "dark" ? "☾" : "☀"}
      </button>
    </div>
  );
}
