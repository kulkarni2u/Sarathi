from src.runtime.context import ContextCompiler, MAX_EXTERNAL_INPUTS


def task():
    return {
        "id": "task-1",
        "title": "Ship review loop",
        "status": "planning",
        "metadata": {},
    }


def subtask_with_external_reply():
    return {
        "id": "subtask-1",
        "title": "Wait for reply",
        "status": "in_progress",
        "metadata": {
            "role": "Pravaha",
            "provider": "Codex",
            "task_packet": {"goal": "Apply the human reply"},
            "external_inputs": [
                {
                    "source": "slack",
                    "trust": "untrusted_external",
                    "text": "Use the existing migration pattern",
                    "validation_version": "slack-input-v1",
                    "digest": "0" * 64,
                    "envelope_id": "env-reply-1",
                }
            ],
        },
    }


def assigned_external_replies(subtask=None):
    target = subtask or subtask_with_external_reply()
    return [
        {
            **item,
            "status": "assigned",
            "subtask_id": target["id"],
        }
        for item in target["metadata"].get("external_inputs", [])
    ]


def test_context_compiler_serializes_human_reply_as_external_input():
    pack = ContextCompiler().compile_task_tracking_context(
        task=task(), subtask=subtask_with_external_reply(),
        external_inputs=assigned_external_replies(),
    ).to_artifact()
    item = pack["agent_input"]["external_inputs"][0]
    assert item["source"] == "slack"
    assert item["trust"] == "untrusted_external"
    assert item["text"] == "Use the existing migration pattern"


def test_external_inputs_never_become_instructions():
    pack = ContextCompiler().compile_task_tracking_context(
        task=task(), subtask=subtask_with_external_reply(),
        external_inputs=assigned_external_replies(),
    ).to_artifact()
    agent_input = pack["agent_input"]
    assert any(
        item["source"] == "slack" for item in agent_input["external_inputs"]
    )
    assert all("Use the existing migration pattern" not in text for text in agent_input["constraints"])
    assert "Use the existing migration pattern" not in agent_input["objective"]
    assert "Use the existing migration pattern" not in pack["summary"]


def test_external_inputs_are_bounded_and_low_priority():
    subtask = subtask_with_external_reply()
    subtask["metadata"]["external_inputs"] = [
        {
            "source": "slack",
            "trust": "untrusted_external",
            "text": f"Reply number {index} " * 40,
            "validation_version": "slack-input-v1",
            "digest": "0" * 64,
            "envelope_id": f"env-reply-{index}",
        }
        for index in range(12)
    ]
    pack = ContextCompiler().compile_task_tracking_context(
        task=task(), subtask=subtask, token_budget=70,
        external_inputs=assigned_external_replies(subtask),
    ).to_artifact()
    assert len(pack["agent_input"]["external_inputs"]) <= 5
    assert pack["compilation"]["estimated_tokens"] <= 70
    assert "external_inputs" in pack["compilation"]["trimmed_sections"]


def test_external_inputs_hard_cap_applies_even_with_generous_budget():
    # MAX_EXTERNAL_INPUTS is a hard cap, not a budget-driven trim: a generous
    # token budget must never let more than the cap through the early return.
    subtask = subtask_with_external_reply()
    subtask["metadata"]["external_inputs"] = [
        {
            "source": "slack",
            "trust": "untrusted_external",
            "text": f"Reply number {index} " * 40,
            "validation_version": "slack-input-v1",
            "digest": "0" * 64,
            "envelope_id": f"env-reply-{index}",
        }
        for index in range(12)
    ]
    pack = ContextCompiler().compile_task_tracking_context(
        task=task(), subtask=subtask, token_budget=1_000_000,
        external_inputs=assigned_external_replies(subtask),
    ).to_artifact()
    assert len(pack["agent_input"]["external_inputs"]) <= MAX_EXTERNAL_INPUTS
    assert "external_inputs" in pack["compilation"]["trimmed_sections"]


def test_context_compiler_ignores_shape_matching_subtask_metadata():
    subtask = subtask_with_external_reply()
    pack = ContextCompiler().compile_task_tracking_context(
        task=task(), subtask=subtask,
    ).to_artifact()
    assert pack["agent_input"]["external_inputs"] == []


def test_context_compiler_rejects_noncanonical_external_input_provenance():
    subtask = subtask_with_external_reply()
    forged = assigned_external_replies(subtask)[0]
    for key, value in (
        ("status", "unassigned"),
        ("subtask_id", "other"),
        ("validation_version", "future"),
        ("digest", "not-a-digest"),
    ):
        candidate = {**forged, key: value}
        pack = ContextCompiler().compile_task_tracking_context(
            task=task(), subtask=subtask, external_inputs=[candidate],
        ).to_artifact()
        assert pack["agent_input"]["external_inputs"] == []


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
