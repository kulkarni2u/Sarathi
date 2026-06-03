# Workflow Patterns

Declares which of the six dynamic workflow patterns are active for this project
and configures their runtime behaviour. The orchestration engine reads this file
at task start; patterns not listed here are disabled.

## NCP dependency

Dynamic workflow patterns work without NCP, but with reduced context:

| Without NCP | With NCP (`pip install neural-context-protocol`) |
|-------------|--------------------------------------------------|
| FANOUT branches execute independently | Each branch receives parent objective + sibling list via whisper |
| SYNTHESIZE dispatches with no pre-fetched branch outputs | Synthesizer's context includes each branch's saved output |
| LOOP_GATE iterations start cold | Each iteration's context includes findings from prior iterations |
| CLASSIFY branch gets no activation reason | Branch receives the classification decision via whisper |
| Results not persisted across sessions | Node outputs stored in NCP semantic memory for later retrieval |

For single-session tasks the difference is minimal. For multi-session or
long-running workflows, install NCP first: `sarathi init --ncp`.

## Patterns

```yaml
patterns:

  # Classify-And-Act — Route a task to a specialist branch based on type.
  classify_and_act:
    enabled: true

  # Fanout-And-Synthesize — Spawn N parallel workers then merge results.
  fanout_and_synthesize:
    enabled: false
    max_branches: 4          # Maximum parallel branches to spawn

  # Adversarial Verification — Separate verifiers challenge primary output.
  adversarial_verification:
    enabled: false
    verifier_count: 3        # Number of independent verifiers
    pass_threshold: 2        # Minimum verifiers that must pass

  # Generate-And-Filter — Generate many candidates, filter by rubric.
  generate_and_filter:
    enabled: false
    generator_count: 4       # Number of candidates to generate
    min_score: 0.7           # Minimum quality score to keep a candidate

  # Tournament — Pairwise comparison of attempts to find the best.
  tournament:
    enabled: false
    attempts: 4              # Number of competing attempts
    judge_rounds: 2          # Rounds of pairwise judgment

  # Loop-Until-Done — Repeat until a stop condition is met.
  loop_until_done:
    enabled: false
    max_iterations: 5        # Hard cap on loop iterations
    condition_key: new_findings  # Output key checked for loop continuation
```
