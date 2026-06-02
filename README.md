# Sarathi

Sarathi is a policy-backed workflow orchestration framework for AI-assisted software delivery.
It gives teams a consistent lifecycle for planning, building, verifying, reviewing, and learning.

## What You Get

- A local CLI (`sarathi`) to initialize, validate, and run workflows
- A policy-pack model to keep behavior explicit and auditable
- A phase-based engine that can scale from simple tasks to complex work
- A portable agent skill pack (in `skill/SKILL.md`) for Claude Code, Codex, Copilot, and OpenCode

## Quick Start

```bash
git clone https://github.com/kulkarni2u/Sarathi.git
cd Sarathi

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

sarathi --help
sarathi validate policy-pack/EXAMPLE
sarathi run "Fix null pointer in user service" --policy-pack policy-pack/EXAMPLE --dry-run
```

Install from any checkout or published wheel (declared dependencies such as PyYAML install automatically):

```bash
python3 -m pip install /path/to/Sarathi
# or from a clone:
python3 -m pip install -e .
```

### Optional: run real tests during Verify

By default Verify uses safe synthetic signals. To execute the `test.command` from `commands.md`:

```bash
export SARATHI_EXEC_COMMANDS=1
export SARATHI_WORKDIR=/path/to/repo   # optional; defaults to cwd
export SARATHI_COMMAND_TIMEOUT=600     # optional; seconds
sarathi run "…" --policy-pack ./policy-pack
```

### Task history

```bash
sarathi list
sarathi log <task_id>
```

### Task status and resumability

```bash
sarathi status <task_id>        # Show task status, graph progress, escalation summary
sarathi resume <task_id>        # Resume a paused or failed task
sarathi reuse                   # Show live workflow templates, saved views, and learned playbooks
```

### Policy proposals

```bash
sarathi proposals                                 # Show policy proposals from persisted learnings
sarathi proposals --accept <proposal_id>          # Append an accepted proposal to its policy file
sarathi proposals --reject <proposal_id> --reason "Already covered"
sarathi proposals --policy-pack ./policy-pack --accept <proposal_id>
```

### Agent roles

```bash
sarathi agents               # Show Sanskrit-inspired agent role names and phase mapping
```

### Workspace Repository Bootstrap

When a repository is attached to a workspace through the local service:

- preview reports repo inspection details plus which Sarathi bootstrap artifacts are present or missing,
- attach remains approval-gated,
- initialize remains approval-gated and only creates missing bootstrap files,
- existing repo-owned docs and policy files are preserved rather than overwritten.

The current bootstrap contract covers:

- `SARATHI.md`
- `wiki/README.md`, `wiki/architecture.md`, `wiki/development.md`
- `coding-standards.md`
- `guidelines.md`
- `learnings.md`
- the full canonical `policy-pack/` set generated from Sarathi init templates

Task-graph snapshots exposed by the local service now also include orchestration semantics such as:

- `ready_nodes`
- `active_nodes`
- `blocked_nodes`
- `waiting_human_nodes`
- `fan_out_ready_nodes`
- `fan_in_nodes`
- `coordination_state`

Workspace policy packs can also opt into cascade scheduling for the service task runtime:

```yaml
graph_execution:
  auto_schedule_ready_nodes: true
```

When enabled, approving the Task graph can immediately start all ready root units, and later blocker completion can auto-start newly ready downstream units without another manual schedule action.

### Python API (agents, scripts)

After `pip install -e .`, import the engine from the `src` package (matches setuptools layout in `pyproject.toml`):

```python
from src.engine import Engine, TaskContext, Complexity, Phase
```

Runtime helpers also expose the Sanskrit-inspired role registry used for
Sarathi-created workers:

```python
from src.runtime import get_agent_role, list_agent_roles

planner = get_agent_role("planner")  # Disha
roles = list_agent_roles()
```

### Provider and scheduler hooks

`model-routing.md` can declare deterministic or command-backed providers:

```yaml
provider: local
providers:
  local: {}
  tool:
    type: command
    command: ["python", "provider.py"]
```

The runtime also exposes `TaskScheduler` for phase-independent graph work-unit scheduling.

Workspace provider settings feed service-side routing:

- `local` — deterministic built-in (default for tests and dry-runs)
- `claude` — native `claude -p {prompt} --output-format json --dangerously-skip-permissions` bridge; unwraps the Claude Code JSON envelope automatically
- `codex` — native `codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -o {file} {prompt}` bridge
- `copilot` — `gh copilot -- -p {prompt}` bridge (requires `gh auth login`)
- `opencode` — HTTP bridge via `opencode serve`; starts a local server, creates a session, and reads the SSE stream for the response
- Any provider can also point at a custom executable that reads Sarathi JSON from stdin and returns a normalized JSON result on stdout

To wire real CLI providers in a policy pack:

```yaml
# policy-pack/model-routing.md
provider: claude
providers:
  claude:
    type: command
    command: "python3 -m src.runtime.providers.cli_bridge --provider claude --path /path/to/claude --workspace-root ."
    timeout_seconds: 300
  copilot:
    type: command
    command: "python3 -m src.runtime.providers.cli_bridge --provider copilot --path /path/to/gh --workspace-root ."
    timeout_seconds: 300
```

Set `SARATHI_DISPATCH_TIMEOUT=300` (or higher) when running real provider dispatch to avoid the thread-level timeout firing before the subprocess completes.

Native Claude/Copilot runs execute from the workspace root and persist bridge metadata such as CLI family, invocation kind, and workspace root inside dispatch evidence.

Recovery loops carry provider context forward. When verify/review retries are triggered, Sarathi classifies failures such as `auth`, `provider_offline`, and `native_cli_failure` and passes that context into recovery actions and retry guidance.

Provider-backed dispatch evidence can also carry structured `review_trace` findings. Sarathi persists those with provider/file/line metadata and surfaces provider trace counts in review summaries.

Dispatch evidence can now also carry:

- `diff_trace` hunks with provider/file/line/header/excerpt detail
- `spec_trace` references that map acceptance-criterion IDs and requirement text to exact code regions

When that richer evidence is present, approved review runs persist those diff/spec references directly and AC coverage maps to explicit evidence references rather than treating any evidence as blanket coverage for every criterion.

If structured provider `spec_trace` data is partial or explicitly failing, Sarathi now treats that as review-blocking spec drift: the review is rejected and the unit is requeued instead of being auto-approved.

Provider `diff_trace` hunks can also carry reviewer-grade metadata such as `category`, `confidence`, and `suggestion`. Sarathi persists those fields on review findings and synthesizes review-level diff summaries including blocker counts, average confidence, risk categories, and patch-region highlights.

Those diff summaries now also cluster related hunks into grouped patch regions and emit a `review_confidence_verdict` with explicit reasons, so downstream review surfaces can show both the risky regions and the overall trust level of the provider-backed patch analysis.

## Common Commands

```bash
# Initialize a policy pack in the current directory
sarathi init .

# Validate a policy pack
sarathi validate ./policy-pack
sarathi validate ./policy-pack --verbose

# Run a task
sarathi run "Add OAuth2 authentication" --policy-pack ./policy-pack
```

## NCP Integration

NCP (Neural Context Protocol) provides advanced context management, replacing Sarathi's native context compilation, persistence, and artifact storage with NCP-backed runtime services.

```bash
# Bootstrap a project with NCP
sarathi init --ncp

# Run with NCP enabled
sarathi run --ncp "task description"
```

**Options:**
- `--ncp-mode {direct|mcp}` — transport mode (default: direct)
- `--ncp-router` — enable whisper-based cross-phase signaling

NCP can be toggled via `--ncp` / `--no-ncp` flags or set as the default in `model-routing.md`.

## Repository Layout

```text
Sarathi/
├── src/                 # CLI + engine implementation
├── tests/               # Test suite
├── policy-pack/         # EXAMPLE and TEMPLATE policy packs
├── docs/                # Supporting documentation
├── DESIGN.md            # Design notes
└── README.md
```

## Companion Skill Pack

This repo contains both the CLI framework and the portable skill pack.

- `skill/SKILL.md` — attach to any agent host (Claude Code, Codex CLI, Copilot, OpenCode)
- `skill/policy-pack/` — EXAMPLE and TEMPLATE policy packs for bootstrapping new projects
- `skill/reference/` — policy reference docs the skill reads at runtime

For GitHub Copilot agent-mode integration, see the agent entry example in `skill/SKILL.md`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT. See [LICENSE](./LICENSE).
