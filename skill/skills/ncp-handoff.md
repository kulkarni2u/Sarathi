# NCP Context Spine

When `--ncp` is active (or NCP is available via `.ncp/run.py`), each phase reads prior context and writes its outcomes to NCP. This is the cross-phase memory that makes multi-session and multi-subagent runs coherent — without it, each phase starts cold.

**Phase read/write contract:**

| Phase | Read from NCP | Write to NCP |
|-------|--------------|-------------|
| Brainstorm start | prior task patterns (semantic) | — |
| Brainstorm end | — | spec → semantic; research findings → episodic |
| Plan start | spec from Brainstorm (semantic) | — |
| Plan end | — | checkpoint list + dependency map → semantic |
| Build (per task, start) | plan checkpoint (semantic) | — |
| Build (per task, end) | — | build evidence + test results → episodic |
| Verify start | build evidence (episodic) | — |
| Verify end | — | failure patterns → procedural (if failures occurred) |
| Review start | spec + build evidence | — |
| Review end | — | review findings → episodic |
| Learn end | — | learnings → procedural; full phase log → semantic |

## Dispatching any subagent (Vichara, Pravaha, Nirnaya, etc.)

Every dispatch instruction — explore-mode or execute-mode — must start with a
`get_context` call and end with a `write_memory` call. Skipping either means
the subagent starts cold and its findings are lost on compaction.

Start of turn — prepend to every instruction:
```bash
First run: .ncp/run.py get_context '{"agent_id":"<role>","role":"<role>","task":"<phase-task>","slot":"build","intent":"<phase-goal>"}'
```

End of turn — append to every instruction:
```bash
When done run: .ncp/run.py write_memory '{"content":"<one_sentence_summary>","layer":"episodic","src":"tool_result","written_by":"<role>"}'
```

All execute-mode and explore-mode task packets include `ncp_context`:
```json
{
  "ncp_context": {
    "agent_id": "<role-name>",
    "prior_refs": ["<ref-from-previous-phase>"],
    "layer": "episodic|semantic|procedural"
  }
}
```

### Execute-mode dispatch (Pravaha): seed the full spec before handoff

Before dispatching any execute-mode subagent, write the task spec to NCP —
not a one-line summary. The spec must be retrievable by the subagent's own
`get_context` query, so include the task slug, file names, function
signatures, and acceptance criteria verbatim:

```bash
python3 .ncp/run.py write_memory '{
  "content": "<full structured spec — file paths, interfaces, acceptance criteria, TDD steps>",
  "layer": "semantic",
  "src": "agent_inferred",
  "written_by": "sarathi",
  "pipeline_id": "<task-slug>"
}'
```

With the spec seeded, the dispatch instruction itself stays short (5-8
lines) — working dir, branch, the `get_context` call, "implement per
context", the test command, the `write_memory` call. Leave out file lists,
code templates, interfaces, or TDD steps; those live in NCP, not in the
instruction text:

```
Work in <repo-path> on branch <branch>.

FIRST: python3 .ncp/run.py get_context '{"agent_id":"pravaha","role":"pravaha","task":"<task-slug>","slot":"build","intent":"<one-phrase-intent>"}'

Read the files named in your context. Implement the spec. Follow TDD: test first.
Run: python3 -m pytest -q after each change.

LAST: python3 .ncp/run.py write_memory '{"content":"<summary>","layer":"episodic","src":"tool_result","written_by":"pravaha"}'
```

**Self-check before dispatching any subagent:**
- [ ] Instruction starts with `get_context`, ends with `write_memory`
- [ ] `agent_id`, `role`, `task`, and `intent` are filled in — not left as `<placeholders>`
- [ ] For execute-mode: the full spec was written to NCP with `write_memory` before this dispatch (not a one-line summary)
- [ ] For execute-mode: the instruction itself stays ≤ 10 lines and excludes file lists, code templates, and TDD steps

If any box is unchecked, fix it before sending the instruction.
