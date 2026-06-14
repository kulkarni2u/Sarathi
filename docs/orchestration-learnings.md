# Orchestration Learnings — Bounded-Context Delegation, Token Efficiency, Context Management

**Date:** 2026-06-14
**Context:** Building the omnigent-parity work (M0 + M1 web cockpit) using an
orchestrator + worker-subagent model on a single branch
(`claude/sarathi-omnigent-comparison-511ubm`). This documents what we learned
applying Sarathi's methodology (independently-testable units, fan-out/fan-in,
measured outcomes) with Claude Code subagents as the execution fabric.

---

## 1. The model we used

- **Orchestrator (brain):** holds the plan, the conversation history, the
  architectural decisions, and the integration seams. Writes bounded specs,
  reviews diffs, runs the authoritative tests, owns all commits.
- **Workers (hands):** each spawned fresh with ONLY its task spec + the specific
  files it needs — never the full transcript. Implements one independently-
  testable unit, self-verifies where possible, returns a concise summary.
- **Model arbitrage:** Haiku for mechanical, fully-specified units; Sonnet for
  judgment-heavy implementation; Opus for orchestration/synthesis.

This is a manual dogfood of Sarathi's FANOUT → (independent units) → SYNTHESIZE
pattern, with the orchestrator playing the SYNTHESIZE/fan-in role.

---

## 2. Measured token efficiency (this session)

Each worker's implementation tokens were spent in an **isolated context**. The
orchestrator context only ever saw the bounded spec it sent and the short result
summary it got back — not the worker's exploration, dead-ends, or file reads.

| Worker (unit) | Model | Worker tokens | Outcome |
|---|---|---:|---|
| WebUI mockup finish | Sonnet | ~59.3k | done |
| M0 migration (`tasks.project_id`) | Haiku | 64.9k | 15 tests |
| M0 queue-state projection | Sonnet | 102.9k | 19 tests |
| M0 OpenAPI spec | Sonnet | 57.7k | 4 pass/1 skip |
| M0 SSE building blocks | Sonnet | 64.1k | 7 tests |
| M0 integration wiring | Sonnet | 87.5k | 0 regressions |
| M1 web scaffold | Sonnet | 92.1k | build+typecheck green |
| desktop.py → web/ wiring | Haiku | 19.9k | 6 tests |
| API client expansion | Sonnet | 32.9k | typecheck green |
| Dashboard view | Sonnet | 65.9k | view complete |
| Task Studio view | Sonnet | 154.6k | view complete |
| History/Agents/Usage views | Sonnet | 151.5k | views complete |
| Wiki/Settings/Workspace/NeedsYou | Sonnet | 139.6k | views complete |
| Live smoke + screenshots | Sonnet | 102.5k | 7 views, 0 console errors |

**~1.2M worker tokens across ~14 units**, almost none of which entered the
orchestrator's context. The orchestrator stayed focused on specs, reviews
(diff stats + targeted test runs), and integration — a small, stable working set
even as total work grew large. This is the core efficiency win: **context cost
scales with the number of decisions, not the volume of code produced.**

Model arbitrage compounded it: the two purely mechanical units went to Haiku
(64.9k + 19.9k) at a fraction of Sonnet/Opus cost, with no quality loss.

---

## 3. What worked

1. **Context hygiene by construction.** Workers never received the transcript, so
   their contexts were small and on-task; the orchestrator never absorbed
   implementation detail it didn't need. Reviewing a worker = reading a diff stat
   + a targeted test result, not re-reading the code.
2. **Safe parallelism via disjoint-file decomposition.** The 4 M0 module-workers
   and 4 view-workers ran concurrently with zero collisions because each owned a
   genuinely independent unit (separate modules / separate `views/<Name>/` dirs).
3. **Model-to-task matching.** Assigning Haiku to well-specified mechanical work
   and Sonnet to judgment work kept cost proportional to difficulty.
4. **Failure isolation.** Workers' transient flakes and exploration stayed in
   their own contexts (e.g., one worker's mid-write typecheck errors, another's
   spelunking through `views.py`) — invisible to the orchestrator and siblings.
5. **Clean audit trail.** One unit → one reviewed diff → one commit. Git history
   reads as a sequence of coherent, individually-tested changes.
6. **Live validation caught what bounded units couldn't.** The end-to-end smoke
   found real bugs (a `fan_in_blocked` task mis-routed out of "Needs You";
   project UUIDs shown instead of names) that defensive per-unit coding masked.

---

## 4. Limits and failure modes (honest)

1. **Integration seams are irreducible.** Conflicts didn't come from bad splits;
   they clustered where many units must register centrally — the `_route` ladder
   in `app.py` and the single whole-project web build (`tsc`/Vite). Someone must
   own that fan-in. We made the orchestrator own all route-wiring and run the one
   authoritative build.
2. **Whole-project build forces batching.** Web view workers could not safely run
   `npm`/`tsc` concurrently (shared `dist`, and `tsc` sees siblings' half-written
   files). So they wrote files only; the orchestrator ran the single build. This
   caps parallel *verification* even when parallel *authoring* is fine.
3. **Stale cross-unit context.** Parallel isolation means a worker can't see a
   sibling's in-progress change. The projection worker reported `project_id`
   "not applied yet" (stale view of the migration); a view worker assumed
   `queue_state` existed on dashboard rows when it didn't. Both required an
   orchestrator reconciliation pass. **This is exactly what NCP whispers /
   shared context compilation are meant to remove.**
4. **Spec quality is the bottleneck.** A worker is only as good as its bounded
   spec: explicit file ownership ("edit only X; don't touch `app.py`"),
   acceptance criteria, and the known-failure baseline ("9 `httpx` failures are
   pre-existing") were what kept output correct and verifiable.
5. **Verification can't be delegated blindly.** Workers self-report "tests pass,"
   but only see their slice. The orchestrator must re-run the *full* suite and
   know the baseline to distinguish real regressions from pre-existing failures.
6. **Workers occasionally claim more than they did.** One referenced a helper it
   hadn't defined; the orchestrator's authoritative typecheck caught it. Trust,
   but verify.

---

## 5. Practices that made it work (reusable checklist)

- Decompose into **independently-testable units**; assign **disjoint file
  ownership** per worker; keep shared contracts (e.g. the API client) owned by
  the orchestrator or a single dedicated worker.
- Give every worker: explicit file scope, acceptance criteria, the test command,
  the **known-failure baseline**, and "do not run git / do not touch shared
  files."
- Match model to task difficulty (Haiku mechanical, Sonnet judgment, Opus
  orchestration).
- The orchestrator owns: route/registration wiring, the **single authoritative
  build/test run**, reconciliation of cross-unit assumptions, and all commits
  (one unit = one commit).
- Run a **live end-to-end smoke** after a milestone of units — integration seams
  are where the real bugs hide, and defensive per-unit code hides them.
- Never commit a unit you haven't re-verified against the full suite + baseline.

---

## 6. How this validates Sarathi + NCP

This session is a hand-rolled instance of Sarathi's thesis, and the friction
points map directly onto its automated value:

| What we did manually | What Sarathi/NCP automates |
|---|---|
| Bounded spec per worker; transcript withheld | Per-node **context compilation** (only relevant context per unit) |
| Disjoint-file FANOUT + orchestrator fan-in | FANOUT / SYNTHESIZE node types in the task graph |
| Reconciling stale cross-unit assumptions by hand | **NCP whispers** / shared semantic memory across branches |
| Re-running the full suite, tracking baseline | `HarnessOutcome` quality-signal measurement |
| Orchestrator-owned commits, one unit each | Governed, auditable lifecycle with permission scopes |
| Choosing Haiku vs Sonnet per unit | Policy-driven model routing per TaskClass |

**Takeaway:** the bounded-context model is not just cheaper — it keeps the
orchestrator's reasoning clear over a long build. The places it strains
(integration seams, stale cross-unit context) are precisely the places Sarathi's
fan-in modeling and NCP's context layer are designed to handle. Our manual pain
points are Sarathi's feature list.
