from src.runtime import build_artifact_index, normalize_agent_output
from src.runtime.contracts import DispatchResponse


def test_build_artifact_index_extracts_structured_retrieval_fields():
    response = DispatchResponse(
        success=True,
        outputs={
            "summary": "Implemented compact dispatch persistence",
            "files_changed": ["src/service/__init__.py"],
            "tests_added": ["python3 -m pytest tests/test_provider_dispatch.py"],
            "findings": [
                {
                    "message": "Attach normalized artifacts to graph nodes.",
                    "severity": "major",
                    "check": "traceability",
                }
            ],
            "known_risks": ["Task Studio still needs a richer artifact inspector."],
            "work_unit_result": {
                "status": "completed",
                "summary": "Dispatch normalization complete",
            },
        },
        evidence={
            "changed_files": ["src/runtime/output_index.py", "src/service/__init__.py"],
            "tests_ran": ["python3 -m pytest tests/test_runtime_output_index.py"],
            "review_trace": {
                "findings": [
                    {
                        "message": "Keep provider blobs out of future context retrieval.",
                        "severity": "minor",
                        "check": "token_budget",
                    }
                ]
            },
        },
        artifacts={
            "review_trace": {
                "findings": [
                    {
                        "message": "Persist agent_output beside raw provider outputs.",
                        "severity": "major",
                        "check": "contract",
                    }
                ]
            }
        },
    )

    artifact_index = build_artifact_index(response)

    assert artifact_index["files_changed"] == [
        "src/service/__init__.py",
        "src/runtime/output_index.py",
    ]
    assert artifact_index["tests_run"] == [
        "python3 -m pytest tests/test_provider_dispatch.py",
        "python3 -m pytest tests/test_runtime_output_index.py",
    ]
    assert artifact_index["known_risks"] == [
        "Task Studio still needs a richer artifact inspector."
    ]
    assert [item["message"] for item in artifact_index["review_findings"]] == [
        "Attach normalized artifacts to graph nodes.",
        "Keep provider blobs out of future context retrieval.",
        "Persist agent_output beside raw provider outputs.",
    ]


def test_normalize_agent_output_builds_compact_contract_for_review_handoff():
    response = DispatchResponse(
        success=True,
        outputs={
            "summary": "Implemented compact dispatch persistence",
            "work_unit_result": {
                "status": "completed",
                "summary": "Dispatch normalization complete",
            },
            "known_risks": ["Task Studio still needs a richer artifact inspector."],
        },
        evidence={
            "changed_files": ["src/service/__init__.py", "tests/test_provider_dispatch.py"],
            "tests_ran": ["python3 -m pytest tests/test_provider_dispatch.py"],
        },
    )

    contract = normalize_agent_output(
        response,
        phase="TaskTracking",
        purpose="child_task_execution",
    ).to_artifact()

    assert contract["status"] == "completed"
    assert contract["summary"] == "Implemented compact dispatch persistence"
    assert contract["artifacts"] == [
        "files_changed:2",
        "tests_run:1",
        "known_risks:1",
    ]
    assert contract["findings"] == [
        "Task Studio still needs a richer artifact inspector."
    ]
    assert contract["next_recommended_agent"] == "Nirnaya"


def test_build_artifact_index_preserves_diff_and_spec_structures():
    response = DispatchResponse(
        success=True,
        evidence={
            "diff_trace": {
                "provider": "codex",
                "hunks": [
                    {
                        "check": "diff_hunk",
                        "status": "fail",
                        "severity": "critical",
                        "message": "Guard auth before dispatch.",
                        "file_path": "src/provider_dispatch.py",
                        "line_start": 40,
                        "line_end": 48,
                        "category": "security",
                        "confidence": 0.94,
                    }
                ],
            },
            "spec_trace": {
                "provider": "codex",
                "references": [
                    {
                        "check": "spec_reference",
                        "status": "pass",
                        "severity": "major",
                        "message": "Acceptance coverage preserved.",
                        "ac_id": "AC-01",
                        "criterion": "A durable task draft exists in the selected workspace.",
                        "file_path": "src/provider_dispatch.py",
                        "line_start": 12,
                        "line_end": 20,
                    }
                ],
            },
        },
    )

    artifact_index = build_artifact_index(response)

    diff_finding = next(item for item in artifact_index["review_findings"] if item["check"] == "diff_hunk")
    spec_finding = next(item for item in artifact_index["review_findings"] if item["check"] == "spec_reference")

    assert diff_finding["provider"] == "codex"
    assert diff_finding["category"] == "security"
    assert diff_finding["confidence"] == 0.94
    assert diff_finding["line_start"] == 40
    assert diff_finding["line_end"] == 48
    assert spec_finding["provider"] == "codex"
    assert spec_finding["ac_id"] == "AC-01"
    assert spec_finding["criterion"] == "A durable task draft exists in the selected workspace."
