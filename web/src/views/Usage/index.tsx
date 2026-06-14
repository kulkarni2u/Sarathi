import { Placeholder } from "../../components/Placeholder";

/**
 * Usage Stats — HarnessOutcome quality signals (pass rate, blast radius,
 * latency, tokens, policy proposals).
 * Route: /usage
 *
 * Later workers: source data from /workspaces/{id}/dogfood-learning,
 * /workspaces/{id}/dogfood-acceptance, and related outcome endpoints.
 */
export default function Usage() {
  return <Placeholder name="Usage Stats" />;
}
