import type { RouteObject } from "react-router-dom";
import { Layout } from "./components/Layout";
import Dashboard from "./views/Dashboard";
import TaskStudio from "./views/TaskStudio";
import History from "./views/History";
import Agents from "./views/Agents";
import Usage from "./views/Usage";
import Wiki from "./views/Wiki";
import Settings from "./views/Settings";
import WorkspaceManage from "./views/Workspace";
import NeedsYou from "./views/NeedsYou";

// ---------------------------------------------------------------------
// Central route table for the Sarathi web cockpit.
//
// Every view lives at web/src/views/<Name>/index.tsx as a self-contained
// default export, so later workers can fill in a view's implementation
// without touching this file (beyond the initial wiring below, which is
// already done for all M1 views).
//
// `handle.title` feeds the TopBar breadcrumb (see components/Layout.tsx).
//
// To add a NEW route:
//   1. Create web/src/views/<Name>/index.tsx exporting a default component.
//   2. Import it above and add a RouteObject entry below, nested under
//      `Layout` (children of the root route) so it gets the sidebar/topbar.
//   3. Add a corresponding nav entry in components/Sidebar.tsx if it should
//      be reachable from the sidebar.
// ---------------------------------------------------------------------

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      // Workspace group
      { index: true, element: <Dashboard />, handle: { title: "Dashboard" } },
      { path: "needs-you", element: <NeedsYou />, handle: { title: "Needs you" } },
      { path: "history", element: <History />, handle: { title: "History" } },
      { path: "agents", element: <Agents />, handle: { title: "Agents" } },

      // Knowledge group
      { path: "wiki", element: <Wiki />, handle: { title: "Wiki" } },
      { path: "usage", element: <Usage />, handle: { title: "Usage Stats" } },

      // System group
      { path: "settings", element: <Settings />, handle: { title: "Settings" } },

      // Workspace management (linked from sidebar workspace switcher)
      { path: "workspace", element: <WorkspaceManage />, handle: { title: "Manage Workspace" } },

      // Task Studio — drill-down view for a single task
      { path: "task/:id", element: <TaskStudio />, handle: { title: "Task Studio" } },
    ],
  },
];
