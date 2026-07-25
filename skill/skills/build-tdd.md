# Build Phase — TDD Iron Law

Pravaha (executor) operates under this non-negotiable rule:

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

**Red-Green-Refactor cycle (mandatory for every unit of work):**

1. **RED** — Write one failing test for the target behavior. Run it. Confirm it fails for the right reason (feature missing, not a syntax error or typo). If it passes immediately, the test is wrong — fix it.
2. **GREEN** — Write the minimum code to make the test pass. Nothing more. No extra features, no refactoring other code.
3. **VERIFY GREEN** — Run the test. Confirm it passes. Confirm no other tests broke.
4. **REFACTOR** — Clean up only. No new behavior. Keep tests green. Run tests again after refactoring.
5. **Repeat** for the next behavior.

**If code was written before the test: delete it. Start over with the test. No exceptions.**

Red flags — stop and restart with TDD:
- Code exists before a failing test was written
- Test passes immediately on first run (proves it tests nothing)
- "I'll add tests after" — no
- "This is too simple to test" — no
- "I already manually tested it" — no
- "Tests after achieve the same goals" — no. Tests-after answer "what does this do?" Tests-first answer "what should this do?"
- "Keep as reference while writing the test" — no. Delete means delete.
