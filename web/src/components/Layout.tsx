import { Outlet, useMatches } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { OfflineBanner } from "./OfflineBanner";

interface RouteHandle {
  title?: string;
}

/**
 * App shell: sidebar + topbar + content outlet. The page title shown in the
 * TopBar comes from each route's `handle.title` (see routes.tsx), falling
 * back to "Sarathi" if unset.
 */
export function Layout() {
  const matches = useMatches();
  const handle = matches
    .slice()
    .reverse()
    .map((m) => m.handle as RouteHandle | undefined)
    .find((h) => h?.title);

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <TopBar title={handle?.title ?? "Sarathi"} />
        <div className="content">
          <OfflineBanner />
          <Outlet />
        </div>
      </div>
    </div>
  );
}
