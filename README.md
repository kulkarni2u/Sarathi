# Sarathi

**Generic workflow orchestration framework**

---

## Quick Start

```bash
# Install
pip install sarathi

# Initialize a new workspace with policy pack
sarathi init

# Validate policy pack configuration
sarathi validate

# Run workflow
sarathi run
```

---

## Architecture

Sarathi consists of three core components:

### Engine
Zero-domain workflow engine that defines HOW to deliver, not what to build. Provides canonical phase lifecycle with gates.

### Policy Pack
Domain-specific behavior supplied via markdown files. Each policy file controls a specific concern (complexity, conventions, commands, etc.).

### Learn-Evolve
Operational expertise loop. Per-workspace learnings accumulate patterns and failures with confidence ratings. Global baseline propagates best practices across projects.

---

## Lifecycle Phases

| Phase | Purpose |
|-------|---------|
| **Route** | Classify task complexity (Low / Medium / High) |
| **Brainstorm** | Exploration and confidence building before commitment |
| **Plan** | Structured planning with evidence gates |
| **Execute** | Implementation with inline verification |
| **Review** | Quality assurance and evidence validation |
| **Ship** | Deployment and documentation |

---

## Policy Pack Structure

| File | Purpose |
|------|---------|
| `complexity.md` | Complexity triggers and classification rules |
| `conventions.md` | Coding standards and style guides |
| `commands.md` | Build, test, and debug commands |
| `review.md` | Review criteria and evidence requirements |
| `escalation.md` | Budget and severity thresholds |
| `model-routing.md` | Complexity-to-model mapping table |
| `skills.md` | Skill registry and routing rules |
| `task-tracking.md` | Task tracking configuration |
| `learnings.md` | Project-specific learnings (per-workspace) |

---

## Documentation

- [Design Specification](./DESIGN.md) - Detailed architecture and design decisions