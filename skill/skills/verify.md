# Verify Phase — Auto-Fix Loop with Systematic Debugging Escalation

Nirnaya runs the auto-fix loop bounded by the budget and severity thresholds in `policy-pack/escalation.md`.

**Systematic Debugging Escalation:**

When fix iterations ≥ 3 with no progress on the same failure, **stop the fix loop**. Root cause investigation is required before the next fix attempt:

1. Read error messages completely — full stack traces, don't skim past them
2. Reproduce the failure consistently before proposing fixes
3. Check what changed (git diff, recent commits, env differences) that could cause this
4. In multi-component systems: add diagnostic instrumentation at each component boundary to find WHERE it breaks before deciding HOW to fix:
   ```
   For each component boundary:
     - Log what data enters the component
     - Log what data exits the component
     - Verify environment/config propagation at each layer
   Run once to gather evidence → find the failing boundary → investigate that boundary
   ```
5. Form one specific hypothesis: "X is the root cause because Y" — write it down
6. Test minimally — one variable at a time. Make the smallest possible change to test the hypothesis.
7. If hypothesis fails: form a new one. Do not stack multiple fixes at once.
8. If 5+ iterations with no progress: this is likely an architectural problem, not a fixable symptom. Escalate to the user — present the pattern of failures and ask whether to rethink the approach.

**Verification Before Claiming Pass:**

Nirnaya must not claim Verify passed without fresh evidence. Before stating any completion or success:

```
1. IDENTIFY: What exact command proves this claim?
2. RUN: Execute the full command now (fresh run, complete output)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does the output confirm the claim?
5. ONLY THEN: State the result, quoting the evidence
```

Forbidden before running verification: "should pass", "probably works", "seems to", "looks good", "Done!", "Perfect!", "Great!" — any wording implying success without having run the check is a verification failure.
