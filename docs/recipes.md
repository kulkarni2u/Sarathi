# Reference Recipes

A **recipe** is a declarative FANOUT/JUDGE workflow over a complete policy pack.
Recipes demonstrate Sarathi's existing dynamic workflow primitives — FANOUT,
SYNTHESIZE, and JUDGE — as runnable, measured reference packs. They live under
`policy-pack/RECIPES/` and are loaded by `src/runtime/recipes.py`.

## The recipe spec format

A recipe is described in a `recipe.md` file (a markdown file with a single
```yaml block) — or a `recipe.yaml`/`recipe.yml` — inside a recipe directory.
The spec fields are:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Human-readable recipe name. |
| `key` | no | Stable identifier; defaults to a slugified `name`. |
| `description` | no | One-line summary. |
| `providers` | no | Declared list of provider ids the recipe fans out across. |
| `workflow` | yes | Must contain a non-empty `nodes` list (typed workflow graph). |

The `workflow.nodes` list is the same shape consumed by
`graph_from_workflow` in `src/task_graph.py`: each node has an `id`, `title`,
`node_type` (`execute` / `fanout` / `synthesize` / `judge` / `loop_gate` /
`classify`), optional `depends_on`, and optional `pattern_config`.

`Recipe.build_graph()` turns the spec into a `TaskGraph`; `Recipe.to_artifact()`
serializes it.

## How per-branch providers work

The orchestrator and debate recipes fan out branch work across more than one
provider. This is driven entirely by the FANOUT node's `pattern_config`:

1. The FANOUT node declares `pattern_config.providers: [provider-a, provider-b]`
   and a branch `count`.
2. When the FANOUT node completes, `_inject_fanout_children`
   (`src/runtime/graph_executor.py`) creates one EXECUTE branch per `count` and
   round-robins the declared providers onto them — branch *i* gets
   `providers[(i - 1) % len(providers)]`. With `count: 3` and two providers the
   assignment is `provider-a, provider-b, provider-a`.
3. Each branch carries its provider in its own `pattern_config.provider`.
4. When a branch is dispatched, `_dispatch_node` threads that provider into the
   dispatch `constraints["provider"]`. The harness-aware dispatcher only injects
   a provider when none is already set, so per-branch providers are honored.

When a FANOUT node omits `providers`, branches get an empty `pattern_config`
and behavior is unchanged (single/default provider).

After the branches finish, a SYNTHESIZE node (`<fanout-id>-synthesize`) merges
their results, and a JUDGE node reviews the merged output — injecting a
`<judge-id>-winner` node to propagate the selected/merged result.

## The two shipped recipes

- **orchestrator** (`policy-pack/RECIPES/orchestrator/`) — `plan` → `fanout`
  (across `provider-a` and `provider-b`) → cross-provider `judge`. Produces a
  judged, merged, measured result. This is the T5.3 acceptance recipe: it fans
  out across >= 2 providers and produces a judged, merged, measured result.
- **debate** (`policy-pack/RECIPES/debate/`) — dual-provider independent drafts
  (`debate` FANOUT) → adversarial `judge`.

Each recipe directory is a full policy pack (all nine policy files plus
`workflow-patterns.md`) so it compiles and runs standalone, and ships
declarative agent specs under `agents/`.

## The measurement story

Every dispatch returns a `DispatchResponse` carrying a `UsageRecord`
(`src/runtime/contracts.py`) with `input_tokens` / `output_tokens` /
`total_tokens`. The executor records each `UsageRecord` on its execution events,
and the CLI sums `total_tokens` across all events to report the recipe's
**measured token cost**.

This is the parity point against omnigent-style multi-agent recipes: those
orchestrate several agents but do not capture a single, summed, measured token
cost for the whole fan-out + judge run. Sarathi's recipes do, because every
branch dispatch flows through the typed `DispatchRequest`/`DispatchResponse`
contract. See `docs/omnigent-parity-design.md` (Task F2) for the broader
parity design.

## Commands

```
# List discovered recipes
sarathi recipes

# Run a recipe's FANOUT/JUDGE workflow graph
sarathi run "<task>" \
  --policy-pack policy-pack/RECIPES/orchestrator \
  --recipe policy-pack/RECIPES/orchestrator
```
