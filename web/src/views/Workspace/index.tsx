import { Placeholder } from "../../components/Placeholder";

/**
 * Workspace — "Manage workspace…" page (linked from the sidebar workspace
 * switcher menu).
 * Route: /workspace
 *
 * Later workers: source data from GET /workspaces/{id},
 * /workspaces/{id}/repositories, /workspaces/{id}/ncp/status, and
 * /workspaces/{id}/projects; support workspace creation via POST /workspaces.
 */
export default function WorkspaceManage() {
  return <Placeholder name="Manage Workspace" />;
}
