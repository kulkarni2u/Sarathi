import { useWorkspace } from "../context/WorkspaceContext";

/**
 * Shows a clear "service offline / degraded" banner inside the content area
 * when the Sarathi service is unreachable. Per requirements, the shell must
 * never render blank — this banner sits above whatever the view renders so
 * views can keep their own (possibly empty/placeholder) content.
 */
export function OfflineBanner() {
  const { serviceStatus, error } = useWorkspace();

  if (serviceStatus === "online") return null;

  if (serviceStatus === "offline") {
    return (
      <div className="banner offline">
        ⚠ Sarathi service is offline — showing degraded UI.
        {error ? ` (${error.message})` : ""}
      </div>
    );
  }

  if (serviceStatus === "degraded") {
    return <div className="banner warn">⚠ Sarathi service reports a degraded status.</div>;
  }

  // "connecting"
  return <div className="banner">Connecting to Sarathi service…</div>;
}
