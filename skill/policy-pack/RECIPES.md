# Reference Recipes

Sarathi ships two reference policy-pack "recipes" under `policy-pack/RECIPES/`.
A recipe is a declarative FANOUT/JUDGE workflow over a complete policy pack that
demonstrates Sarathi's existing FANOUT / SYNTHESIZE / JUDGE primitives.

## Recipes

- **orchestrator** — plan, fan out implementation across two providers in
  parallel, then run a cross-provider JUDGE before merge. This recipe fans out
  across >= 2 providers and produces a judged, merged, measured result (token
  cost is reported from each dispatch's `UsageRecord`).
- **debate** — two providers independently draft answers, then an adversarial
  JUDGE picks or merges the strongest.

## Commands

List the available recipes:

```
sarathi recipes
```

Run a recipe as a FANOUT/JUDGE workflow graph (instead of the standard
lifecycle):

```
sarathi run "<task>" --policy-pack policy-pack/RECIPES/orchestrator --recipe policy-pack/RECIPES/orchestrator
```

The run prints how many nodes completed, which providers were used in the
fan-out, and the measured token cost summed across every dispatch.

See `docs/recipes.md` for the recipe spec format and the measurement story.
