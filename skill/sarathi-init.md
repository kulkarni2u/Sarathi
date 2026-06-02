# Sarathi --init Workflow

Automatically generate a policy pack for a codebase via inspection, interview, generation, validation, and evolve.

## Usage

```
sarathi init [target_path] [--engine path]
```

## The --init Flow

### Phase 1: Inspect

Scan target repo to detect:
- Language(s) and version(s)
- Framework(s)
- Build tools (npm, cargo, poetry, etc.)
- Test patterns (`*.test.py`, `*.spec.ts`, etc.)
- Linting tools (eslint, black, mypy, etc.)
- Package manager
- Entry points

**Method:** Explore agent scans files, looks for indicators, asks devil's advocate on ambiguity

### Phase 2: Interview

Ask only high-value questions NOT covered by inspect:
- Policy keys (team conventions, PR requirements)
- Task tracking format preference
- Domain constraints
- Review evidence shape
- SLO targets

**Method:** Devil's advocate fills most answers from inspection. User asked only for:
- High-complexity ambiguous items
- Domain-specific overrides

### Phase 3: Generate

Create policy pack from inspection + interview:

| File | Source |
|------|--------|
| complexity.md | Derived from inspected file types, count heuristics |
| conventions.md | Language defaults + interview overrides |
| commands.md | Detected build/test tools |
| review.md | Standard criteria + interview |
| escalation.md | Default budgets + interview |
| model-routing.md | Default routing + interview |
| skills.md | Default skills + detected stack |
| task-tracking.md | Interview preference |

**Output:** `policy-pack/` directory in target repo

### Phase 4: Validate

Validate generated pack against engine contracts:

```
PASS: All required inputs satisfied
DRIFT: Mismatch between expected and claimed
TODO: Missing required inputs
```

Run dual-source comparison:
- Engine's required-list.md expectations vs policy claims
- Report PASS/DRIFT/TODO per required input

Fix gaps before hand-off.

### Phase 5: Evolve

After first task completes:
1. Update learnings.md with patterns
2. Run skill-evolve
3. Policy hardens from real usage
4. Future --init starts stronger

## Implementation

The --init CLI command (from sarathi.py):

```python
def init(target_path: str, engine_path: str = None):
    workflow = InitWorkflow(target_path, engine_path)
    
    # Inspect
    inspection = workflow.inspect()
    
    # Interview (devil's advocate fills gaps)
    interview = workflow.interview(inspection)
    
    # Generate
    policy_path = workflow.generate(inspection, interview)
    
    # Validate
    results = workflow.validate(policy_path)
    
    # Report
    for r in results:
        print(f"{r.status.value}: {r.required_input}")
    
    return policy_path
```

## Example

```bash
# Initialize policy pack for current directory
sarathi init .

# Initialize for specific project
sarathi init /path/to/project --engine ./sarathi/engine
```

## Output Structure

```
target/
├── policy-pack/
│   ├── complexity.md      # Auto-generated
│   ├── conventions.md   # Auto-generated + overrides
│   ├── commands.md     # Auto-detected
│   ├── review.md       # Standard + custom
│   ├── escalation.md   # Defaults + interview
│   ├── model-routing.md
│   ├── skills.md
│   └── task-tracking.md
└── core-policy-interface-mapping.md  # Auto-generated validation
```

## Policy Override

Teams can override any generated file. --init creates a starting point, not a final answer.

## Validation After Override

Run `sarathi validate ./policy-pack` anytime to check:
- PASS: Policy satisfies engine contract
- DRIFT: Policy has drifted from expectations
- TODO: New engine requirements not met
