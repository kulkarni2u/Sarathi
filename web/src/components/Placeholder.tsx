export interface PlaceholderProps {
  /** View name shown in the heading, e.g. "Task Studio". */
  name: string;
  /** Optional extra description/context for the view. */
  description?: string;
}

/**
 * Generic "coming soon" placeholder used by views that will be filled in by
 * later M1 workers. Keeps the route + layout wiring real while leaving
 * content implementation to the owning worker.
 */
export function Placeholder({ name, description }: PlaceholderProps) {
  return (
    <div className="placeholder">
      <h1>{name}</h1>
      <p>
        <code>{name}</code> — coming in M1.
      </p>
      {description && <p>{description}</p>}
    </div>
  );
}
