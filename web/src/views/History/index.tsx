import { Placeholder } from "../../components/Placeholder";

/**
 * History — phase transitions and governance events for the active workspace.
 * Route: /history
 *
 * Later workers: source data from GET /events?workspace_id=... (see
 * src/api/events.ts for the subscription helper) and/or
 * /workspaces/{id}/operational-views.
 */
export default function History() {
  return <Placeholder name="History" />;
}
