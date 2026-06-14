import { useParams } from "react-router-dom";
import { Placeholder } from "../../components/Placeholder";

/**
 * Task Studio — graph + conversation view for a single task.
 * Route: /task/:id
 *
 * Later workers should fetch task detail via GET /tasks/{id}/studio (and
 * related /tasks/{id}/graph, /tasks/{id}/messages, /tasks/{id}/panel
 * endpoints) using the `id` route param below.
 */
export default function TaskStudio() {
  const { id } = useParams<{ id: string }>();
  return <Placeholder name="Task Studio" description={`Task id: ${id ?? "(none)"}`} />;
}
