import { Placeholder } from "../../components/Placeholder";

/**
 * Wiki — workspace knowledge pages (human-authored + generated, with
 * proposal-backed edits).
 * Route: /wiki
 *
 * Later workers: source data from GET /workspaces/{id}/wiki and
 * /workspaces/{id}/wiki/{page}, with edits via /workspaces/{id}/proposals.
 */
export default function Wiki() {
  return <Placeholder name="Wiki" />;
}
