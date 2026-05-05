import {
  DashboardIcon,
  ArchiveIcon,
  PersonIcon,
  GearIcon,
  SunIcon,
  MoonIcon,
} from "@radix-ui/react-icons";

type AppRoute = "home" | "dashboard" | "inbox" | "agents" | "settings" | "project";

const navItems: Array<{ id: AppRoute; label: string; icon: React.ReactNode; badge?: string }> = [
  { id: "dashboard", label: "Dashboard", icon: <DashboardIcon /> },
  { id: "inbox",     label: "Inbox",     icon: <ArchiveIcon />,  badge: "3" },
  { id: "agents",    label: "Agents",    icon: <PersonIcon /> },
  { id: "settings",  label: "Settings",  icon: <GearIcon /> },
];

export default function Sidebar({
  route,
  setRoute,
  dark,
  setDark,
}: {
  route: AppRoute;
  setRoute: (r: AppRoute) => void;
  dark: boolean;
  setDark: (d: boolean) => void;
}) {
  return (
    <aside
      style={{
        width: "var(--s-sidebar-width)",
        minWidth: "var(--s-sidebar-width)",
        height: "100vh",
        position: "sticky",
        top: 0,
        display: "flex",
        flexDirection: "column",
        background: "var(--s-sidebar-bg)",
        borderRight: "1px solid var(--s-border)",
        boxShadow: "var(--s-shadow-sm)",
        overflowY: "auto",
      }}
    >
      {/* Brand + wordmark */}
      <button
        onClick={() => setRoute("home")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "16px 16px 12px",
          background: "transparent",
          border: 0,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "var(--s-radius-sm)",
            background: "var(--s-accent)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: "1rem",
            flexShrink: 0,
          }}
        >
          S
        </div>
        <span
          style={{
            fontWeight: 600,
            fontSize: "0.95rem",
            color: "var(--s-ink)",
          }}
        >
          Sarathi
        </span>
      </button>

      {/* Workspace switcher placeholder */}
      <div style={{ padding: "0 10px 12px" }}>
        <button
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "7px 10px",
            background: "var(--s-accent-bg)",
            border: "1px solid var(--s-border)",
            borderRadius: "var(--s-radius-sm)",
            cursor: "pointer",
            fontSize: "0.8rem",
            color: "var(--s-ink)",
            fontWeight: 500,
          }}
        >
          <span>Sarathi App</span>
          <span style={{ color: "var(--s-muted)", fontSize: "0.7rem" }}>▾</span>
        </button>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: "var(--s-border)", margin: "0 10px 8px" }} />

      {/* Nav items */}
      <nav style={{ flex: 1, padding: "0 8px" }}>
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`s-nav-item${route === item.id ? " active" : ""}`}
            onClick={() => setRoute(item.id)}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
              {item.icon}
              {item.label}
            </span>
            {item.badge && (
              <span
                style={{
                  background: "var(--s-accent-bg)",
                  color: "var(--s-accent)",
                  borderRadius: 99,
                  padding: "1px 7px",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                }}
              >
                {item.badge}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* Bottom: dark mode toggle + connection status */}
      <div
        style={{
          padding: "12px 12px",
          borderTop: "1px solid var(--s-border)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        {/* Connection status dot */}
        <span
          title="Service status"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "var(--s-green)",
            flexShrink: 0,
          }}
        />
        <span style={{ fontSize: "0.75rem", color: "var(--s-muted)", flex: 1 }}>
          Connected
        </span>
        {/* Dark mode toggle */}
        <button
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          onClick={() => setDark(!dark)}
          style={{
            background: "transparent",
            border: 0,
            cursor: "pointer",
            color: "var(--s-muted)",
            display: "flex",
            alignItems: "center",
            padding: 4,
            borderRadius: "var(--s-radius-sm)",
          }}
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
    </aside>
  );
}
