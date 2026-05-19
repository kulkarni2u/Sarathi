from src.runtime.context import ContextCompiler


def test_context_compiler_builds_compact_task_tracking_pack():
    compiler = ContextCompiler()

    pack = compiler.compile_task_tracking_context(
        task={
            "id": "task-1",
            "title": "Ship review loop",
            "status": "planning",
            "metadata": {
                "acceptance_criteria": [
                    "Review findings are persisted",
                    "Context packs are recorded per dispatch",
                ],
                "relevant_files": ["src/service/__init__.py", "tests/test_provider_dispatch.py"],
            },
        },
        subtask={
            "id": "subtask-1",
            "title": "Implement context compiler",
            "status": "in_progress",
            "metadata": {
                "role": "Pravaha",
                "provider": "Codex",
                "evidence_required": ["changed_files", "tests"],
                "task_packet": {
                    "goal": "Implement context compiler",
                    "review_criteria": ["Context packs are compact", "Dispatch metadata persists them"],
                },
            },
        },
        evidence_artifacts=[
            {
                "id": "ev-1",
                "artifact_type": "dispatch_result",
                "uri": "sarathi://dispatches/ev-1",
                "metadata": {
                    "response_evidence": {
                        "changed_files": ["src/runtime/context.py", "src/service/__init__.py"],
                    }
                },
            }
        ],
        review_runs=[
            {
                "id": "review-1",
                "summary": "Previous review found missing evidence links.",
                "metadata": {"findings": [{"message": "Attach evidence refs to dispatch metadata."}]},
            }
        ],
        available_tools=["workspace_files", "git_diff"],
    )

    artifact = pack.to_artifact()

    assert artifact["role"] == "Pravaha"
    assert artifact["phase"] == "TaskTracking"
    assert artifact["agent_input"]["objective"] == "Implement context compiler"
    assert "Context packs are compact" in artifact["agent_input"]["acceptance_criteria"]
    assert "src/runtime/context.py" in artifact["agent_input"]["relevant_files"]
    assert artifact["compilation"]["full_history_excluded"] is True
    assert artifact["compilation"]["estimated_tokens"] <= artifact["agent_input"]["token_budget"]


def test_context_compiler_trims_low_priority_sections_to_budget():
    compiler = ContextCompiler()

    pack = compiler.compile_task_tracking_context(
        task={
            "id": "task-budget",
            "title": "Large task",
            "status": "planning",
            "metadata": {
                "acceptance_criteria": [f"Criterion {index}" for index in range(1, 12)],
                "relevant_files": [f"src/file_{index}.py" for index in range(1, 15)],
            },
        },
        subtask={
            "id": "subtask-budget",
            "title": "Budgeted execution",
            "status": "in_progress",
            "metadata": {
                "role": "Nirnaya",
                "provider": "Claude",
                "evidence_required": ["review_verdict", "ac_coverage"],
                "task_packet": {"goal": "Budgeted execution"},
            },
        },
        review_runs=[
            {"id": f"review-{index}", "summary": f"Finding {index} " * 12, "metadata": {}}
            for index in range(1, 8)
        ],
        token_budget=90,
    )

    artifact = pack.to_artifact()

    assert artifact["compilation"]["estimated_tokens"] <= 90
    assert artifact["compilation"]["trimmed_sections"]


def test_context_compiler_prefers_normalized_artifact_index_for_relevant_files():
    compiler = ContextCompiler()

    pack = compiler.compile_task_tracking_context(
        task={
            "id": "task-2",
            "title": "Use normalized evidence",
            "status": "planning",
            "metadata": {},
        },
        subtask={
            "id": "subtask-2",
            "title": "Compile compact context",
            "status": "in_progress",
            "metadata": {
                "role": "Pravaha",
                "provider": "Codex",
                "task_packet": {"goal": "Compile compact context"},
            },
        },
        evidence_artifacts=[
            {
                "id": "ev-2",
                "artifact_type": "dispatch_result",
                "uri": "sarathi://dispatches/ev-2",
                "metadata": {
                    "artifact_index": {
                        "files_changed": ["src/runtime/output_index.py", "src/service/__init__.py"]
                    },
                    "response_evidence": {},
                },
            }
        ],
    )

    assert "src/runtime/output_index.py" in pack.to_artifact()["agent_input"]["relevant_files"]
