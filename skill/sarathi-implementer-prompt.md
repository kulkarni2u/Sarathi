# Sarathi Implementer Prompt Template

Use this template when dispatching a Sarathi task implementer.

```
Task tool (general-purpose):
  description: "Implement [task name] via Sarathi"
  prompt: |
    You are executing a task via the Sarathi workflow orchestration framework.

    ## Task

    [Describe the task to implement]

    ## Sarathi Phase Context

    This task is in the following Sarathi phase(s):
    - Current phase: [Phase name]
    - Previous phases completed: [list]
    - Gate requirements: [what must pass before proceeding]

    ## Policy Pack Context

    From the policy pack:
    - Complexity classification: [Low/Medium/High]
    - Conventions to follow: [link to policy pack conventions.md]
    - Build commands: [link to policy pack commands.md]
    - Review criteria: [link to policy pack review.md]

    ## Your Job

    1. Follow the phase-specific workflow:
       - [Phase-specific instructions from workflow.md]
    2. Apply policy pack rules
    3. Generate evidence for confidence gates
    4. Log phase transitions to phase log

    ## Confidence Gate Evidence

    For this phase, provide evidence from:
    - alternative_approaches_considered (weight: 0.3)
    - risks_identified (weight: 0.3)
    - success_criteria_defined (weight: 0.2)
    - reversibility_assessed (weight: 0.2)

    ## Report Format

    - Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    - Phase outcome: pass | fail | skip
    - Evidence package
    - Phase log entry
```