import { Placeholder } from "../../components/Placeholder";

/**
 * Needs You — tasks awaiting operator approval/attention across the
 * workspace (the "amber" lane from the Dashboard board, surfaced as its own
 * view + sidebar nav item).
 * Route: /needs-you
 *
 * Later workers: filter GET /workspaces/{id}/task-dashboard rows by
 * approval/blocked/failed status, and/or GET /tasks/{id}/approvals.
 */
export default function NeedsYou() {
  return <Placeholder name="Needs you" />;
}
