# Sarathi --init Workflow

Automatically generate a policy pack for a codebase via inspection, interview, generation, validation, and evolve.

## Usage

```
sarathi init [target_path] [--engine path] [--ncp]
```

### `--ncp` flag

Pass `--ncp` to bootstrap NCP (Neural Context Protocol) alongside the policy pack.
This creates a `.ncp/` directory in the target project so Sarathi can auto-detect
NCP on subsequent runs.

**Requires:** Sarathi installed from a package version that includes
`neural-context-protocol>=1.1.0`. See [HOWTO.md §7](HOWTO.md#7-ncp-integration)
for the full NCP setup guide.

When `--ncp` is passed, `sarathi init` also generates a `workflow-patterns.md`
policy file so dynamic workflow patterns (FANOUT, CLASSIFY, LOOP, etc.) are
available to configure.

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
| permissions.md | Provider tool allowlists → written as native config files |

After generating `permissions.md`, `sarathi init` immediately writes provider-native config files:

| Config file | Provider | What it enables |
|-------------|----------|-----------------|
| `.claude/settings.json` | Claude Code | `permissions.allow` tool list — no runtime flags needed |
| `~/.codex/config.yaml` | Codex | `full-auto: true` — auto-approves without sandbox bypass |
| `opencode.json` | OpenCode | `autoapprove: true` — auto-approves tool calls |

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

## Importing Policy Packs (`--from`)

Import an existing policy pack instead of generating one from scratch:

```bash
# From a local directory
sarathi init . --from /path/to/existing/policy-pack

# From a shipped recipe by name
sarathi init . --from bakeoff

# From a git repository
sarathi init . --from https://github.com/org/policy-pack.git

# From a registry entry (shipped recipes)
sarathi init . --from registry:bakeoff

# From a registry entry with version hint
sarathi init . --from bakeoff@latest
```

### Import Sources

The `--from` option accepts these source types:

| Pattern | Example | Description |
|---------|---------|-------------|
| Local path | `--from ./my-pack` | Absolute or relative directory path |
| Recipe name | `--from bakeoff` | Name of a shipped recipe under `policy-pack/RECIPES/` |
| Git URL | `--from https://...` | Any `https://`, `http://`, `git@`, `file://` URL |
| Registry entry | `--from registry:<name>` | Unambiguous lookup in the registry |
| Versioned entry | `--from <name>@<version>` | Registry lookup when the base name exists in the registry |

### Gap-filling

If the imported pack is missing any standard files (`complexity.md`, `commands.md`,
`review.md`, etc.), Sarathi generates sensible defaults for them automatically.

### Force Overwrite

Use `--force` to overwrite an existing `policy-pack/` directory:

```bash
sarathi init . --from bakeoff --force
```

### Registry Manifests

The default registry includes all shipped recipes under `policy-pack/RECIPES/`.
To extend with your own entries, export `SARATHI_REGISTRY` pointing to a JSON
manifest file.

Each entry supports three styles:

| Style | Example | Use case |
|-------|---------|----------|
| Plain | `"source": "..."` | Default source, no version label |
| Labelled | `"source": "...", "version": "v1"` | Single entry with a version tag |
| Versioned | `"source": "...", "versions": { "v1": {...}, "v2": {...} }` | Multi-version with optional default |

**Plain entry** — resolved via `registry:<name>`:

```json
{
  "registries": {
    "my-org": {
      "description": "My org's curated policy packs",
      "entries": {
        "secure-defaults": {
          "description": "Security-hardened base pack",
          "source": "/path/to/secure-defaults"
        }
      }
    }
  }
}
```

**Multi-version entry** — `source` is the default (used by `registry:<name>`);
each version gets its own `source` (used by `<name>@<version>`):

```json
{
  "registries": {
    "my-org": {
      "entries": {
        "my-pack": {
          "description": "A versioned pack",
          "source": "/path/to/latest",
          "versions": {
            "v1": { "source": "/path/to/v1" },
            "v2": { "source": "/path/to/v2" }
          }
        }
      }
    }
  }
}
```

If no `source` is set and only `versions` exist, `registry:<name>` resolves
to the first version's source.

```bash
export SARATHI_REGISTRY=/path/to/registry-manifest.json
sarathi init . --from registry:secure-defaults
sarathi init . --from my-pack@v2
```

External registry entries override built-in entries when names collide.

## Output Structure

```
target/
├── policy-pack/
│   ├── complexity.md        # Auto-generated
│   ├── conventions.md       # Auto-generated + overrides
│   ├── commands.md          # Auto-detected
│   ├── review.md            # Standard + custom
│   ├── escalation.md        # Defaults + interview
│   ├── model-routing.md
│   ├── skills.md
│   ├── task-tracking.md
│   ├── permissions.md       # Provider tool allowlists
│   └── workflow-patterns.md # Generated when --ncp is passed
├── .claude/
│   └── settings.json        # Claude Code permissions (auto-written from permissions.md)
├── opencode.json            # OpenCode autoapprove (auto-written from permissions.md)
├── .ncp/                    # Created when --ncp is passed
│   └── run.py               # NCP sidecar entry point
└── core-policy-interface-mapping.md  # Auto-generated validation
```

Note: `~/.codex/config.yaml` (user-level) is written for Codex since Codex does not support a per-project config.

## Policy Override

Teams can override any generated file. --init creates a starting point, not a final answer.

## Validation After Override

Run `sarathi validate ./policy-pack` anytime to check:
- PASS: Policy satisfies engine contract
- DRIFT: Policy has drifted from expectations
- TODO: New engine requirements not met
