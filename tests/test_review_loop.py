import json
from pathlib import Path
import stat

from src.service import create_app
from src.storage import connect


def request(app, method, path, body=None, correlation_id="corr-review-loop"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-review-loop"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def test_review_run_approves_evidenced_review_units_and_records_ac_coverage(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_dispatched_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "code"},
        )
    )

    assert status == 201
    review = data["review"]
    assert review["status"] == "approved"
    assert review["summary"] == "Review approved with dispatch evidence."
    assert all(item["covered"] for item in review["metadata"]["ac_coverage"])
    assert review["metadata"]["diff_summary"]["changed_files"] >= 1
    assert review["metadata"]["findings"]
    assert all(item["subtask_id"] for item in review["metadata"]["findings"])
    assert all(item["evidence_id"] for item in review["metadata"]["findings"])
    assert all(item["file_path"] for item in review["metadata"]["findings"])
    assert data["completed_subtasks"]

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    assert studio_data["reviews"][0]["id"] == review["id"]
    reviewed_node = next(
        node for node in studio_data["graph"]["nodes"] if node["id"] == data["completed_subtasks"][0]["id"]
    )
    assert reviewed_node["status"] == "complete"
    assert "review.completed" in {event["event_type"] for event in studio_data["events"]}


def test_review_run_approves_when_evidenced_units_already_completed(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_dispatched_unit(app, tmp_path)
    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    reviewed_node = next(node for node in studio_before["graph"]["nodes"] if node["status"] == "review")
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{reviewed_node['id']}/transition",
            {"status": "complete", "actor": "Operator"},
        )
    )

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )

    assert status == 201
    assert data["review"]["status"] == "approved"
    assert data["review"]["summary"] == "Review approved with dispatch evidence."
    assert data["review"]["metadata"]["reviewed_subtasks"] == [reviewed_node["id"]]
    assert [subtask["id"] for subtask in data["completed_subtasks"]] == [reviewed_node["id"]]

    _, studio_after = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    assert "review.completed" in {event["event_type"] for event in studio_after["events"]}


def test_review_run_rejects_missing_evidence_and_requeues_review_units(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_review_unit_without_evidence(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )

    assert status == 201
    review = data["review"]
    assert review["status"] == "rejected"
    assert review["metadata"]["missing_evidence"]
    assert review["metadata"]["findings"]
    assert all(item["check"] == "missing_evidence" for item in review["metadata"]["findings"])
    assert all(item["subtask_id"] for item in review["metadata"]["findings"])
    assert data["requeued_subtasks"]

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    requeued_node = next(
        node for node in studio_data["graph"]["nodes"] if node["id"] == data["requeued_subtasks"][0]["id"]
    )
    assert requeued_node["status"] == "in_progress"
    assert "review.rejected" in {event["event_type"] for event in studio_data["events"]}


def test_review_run_uses_provider_review_trace_findings_when_available(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_traced_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "code"},
        )
    )

    assert status == 201
    review = data["review"]
    findings = review["metadata"]["findings"]
    assert review["status"] == "approved"
    assert review["metadata"]["diff_summary"]["changed_files"] >= 1
    assert review["metadata"]["diff_summary"]["provider_trace_findings"] == 2
    assert review["metadata"]["diff_summary"]["provider_trace_providers"] == ["codex"]
    assert [item["check"] for item in findings] == ["provider_trace", "provider_trace"]
    assert findings[0]["severity"] == "major"
    assert findings[0]["file_path"] == "src/provider_dispatch.py"
    assert findings[0]["line_start"] == 12
    assert findings[0]["line_end"] == 18
    assert findings[0]["provider"] == "codex"
    assert findings[1]["severity"] == "info"
    assert findings[1]["file_path"] == "tests/test_provider_dispatch.py"
    assert all(item["evidence_id"] for item in findings)
    assert all(item["subtask_id"] for item in findings)


def test_review_run_records_provider_diff_and_spec_references(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_diff_and_spec_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )

    assert status == 201
    review = data["review"]
    findings = review["metadata"]["findings"]
    diff_summary = review["metadata"]["diff_summary"]
    ac_coverage = review["metadata"]["ac_coverage"]

    assert review["status"] == "rejected"
    assert "spec drift" in review["summary"].lower()
    assert diff_summary["changed_files"] == 2
    assert diff_summary["provider_diff_hunks"] == 2
    assert diff_summary["provider_diff_providers"] == ["codex"]
    assert diff_summary["provider_spec_references"] == 2
    assert diff_summary["provider_spec_providers"] == ["codex"]
    assert [item["covered"] for item in ac_coverage] == [True, True, False]
    assert [item["id"] for item in ac_coverage] == ["AC-01", "AC-02", "AC-03"]
    assert any(item["check"] == "diff_hunk" for item in findings)
    assert any(item["check"] == "spec_reference" for item in findings)
    assert any(item["check"] == "acceptance_coverage" and item["ac_id"] == "AC-03" for item in findings)
    spec_finding = next(item for item in findings if item["check"] == "spec_reference")
    assert spec_finding["ac_id"] == "AC-01"
    assert spec_finding["file_path"] == "src/provider_dispatch.py"
    assert spec_finding["line_start"] == 12
    assert spec_finding["line_end"] == 20
    assert spec_finding["provider"] == "codex"
    assert spec_finding["evidence_id"]
    assert spec_finding["subtask_id"]
    assert data["requeued_subtasks"]


def test_review_run_uses_normalized_artifact_index_when_raw_traces_are_removed(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_diff_and_spec_unit(app, tmp_path)
    _strip_raw_response_traces(tmp_path / "sarathi.db", task["id"])

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )

    assert status == 201
    review = data["review"]
    diff_summary = review["metadata"]["diff_summary"]
    findings = review["metadata"]["findings"]

    assert review["status"] == "rejected"
    assert diff_summary["changed_files"] == 2
    assert diff_summary["provider_diff_hunks"] == 2
    assert diff_summary["provider_spec_references"] == 2
    assert any(item["check"] == "diff_hunk" for item in findings)
    assert any(item["check"] == "spec_reference" for item in findings)


def test_review_run_rejects_provider_signaled_spec_drift_and_requeues_units(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_spec_drift_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "functional"},
        )
    )

    assert status == 201
    review = data["review"]
    findings = review["metadata"]["findings"]
    assert review["status"] == "rejected"
    assert "spec drift" in review["summary"].lower()
    assert review["metadata"]["coverage_gaps"] == ["AC-03"]
    assert any(item["check"] == "spec_reference" and item["status"] == "fail" for item in findings)
    assert any(item["check"] == "acceptance_coverage" and item["status"] == "fail" for item in findings)
    assert data["requeued_subtasks"]

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    requeued_node = next(
        node for node in studio_data["graph"]["nodes"] if node["id"] == data["requeued_subtasks"][0]["id"]
    )
    assert requeued_node["status"] == "in_progress"
    assert "review.rejected" in {event["event_type"] for event in studio_data["events"]}


def test_review_run_summarizes_provider_diff_risk_annotations(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_diff_risk_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "code"},
        )
    )

    assert status == 201
    review = data["review"]
    findings = review["metadata"]["findings"]
    diff_summary = review["metadata"]["diff_summary"]
    assert review["status"] == "rejected"
    assert diff_summary["provider_diff_hunks"] == 2
    assert diff_summary["provider_diff_blockers"] == 1
    assert diff_summary["provider_diff_confidence"] == 0.72
    assert diff_summary["provider_diff_risk_categories"] == ["security", "coverage"]
    assert diff_summary["provider_diff_highlights"] == [
        "security / src/provider_dispatch.py:40-48",
        "coverage / tests/test_provider_dispatch.py:91-104",
    ]
    blocker = next(item for item in findings if item["check"] == "diff_hunk" and item["status"] == "fail")
    assert blocker["category"] == "security"
    assert blocker["confidence"] == 0.94
    assert blocker["suggestion"] == "Add an explicit auth/token guard before dispatch."
    assert blocker["header"] == "@@ -40,6 +40,12 @@"


def test_review_run_clusters_diff_regions_and_synthesizes_confidence_verdict(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_provider_clustered_diff_unit(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/reviews/run",
            {"review_type": "code"},
        )
    )

    assert status == 201
    review = data["review"]
    diff_summary = review["metadata"]["diff_summary"]
    assert review["status"] == "rejected"
    assert diff_summary["review_confidence_verdict"] == "low"
    assert diff_summary["review_confidence_reasons"] == [
        "1 blocking diff hunk(s) remain.",
        "Provider diff confidence average is 0.66.",
    ]
    assert diff_summary["provider_diff_regions"] == [
        {
            "file_path": "src/provider_dispatch.py",
            "category": "security",
            "line_start": 40,
            "line_end": 56,
            "hunk_count": 2,
            "highest_severity": "critical",
            "max_confidence": 0.94,
        },
        {
            "file_path": "tests/test_provider_dispatch.py",
            "category": "coverage",
            "line_start": 91,
            "line_end": 104,
            "hunk_count": 1,
            "highest_severity": "info",
            "max_confidence": 0.5,
        },
    ]


def create_task_with_dispatched_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "local"},
        )
    )
    return task


def _strip_raw_response_traces(db_path: Path, task_id: str) -> None:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, metadata FROM evidence_artifacts WHERE task_id = ? ORDER BY created_at, id",
            (task_id,),
        ).fetchall()
        for row in rows:
            raw_metadata = row["metadata"]
            if isinstance(raw_metadata, str) and raw_metadata.strip():
                metadata = json.loads(raw_metadata)
            elif isinstance(raw_metadata, dict):
                metadata = dict(raw_metadata)
            else:
                metadata = {}
            raw = metadata.get("response_evidence")
            if isinstance(raw, dict):
                metadata["response_evidence"] = {}
            conn.execute(
                "UPDATE evidence_artifacts SET metadata = ? WHERE id = ?",
                (json.dumps(metadata), row["id"]),
            )
        conn.commit()


def create_task_with_provider_traced_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim completed work unit'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim completed work unit'"
            "}"
            "},"
            "'evidence': {"
            "'changed_files': ['src/provider_dispatch.py', 'tests/test_provider_dispatch.py'],"
            "'review_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex flagged review hotspots.',"
            "'findings': ["
            "{'check': 'provider_trace', 'status': 'pass', 'severity': 'major', 'message': 'Validate command shim fallback handling.', 'file_path': 'src/provider_dispatch.py', 'line_start': 12, 'line_end': 18},"
            "{'check': 'provider_trace', 'status': 'pass', 'severity': 'info', 'message': 'Add coverage for provider bridge metadata.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 42, 'line_end': 55}"
            "]"
            "}"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )
    return task


def create_task_with_provider_diff_and_spec_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-diff-spec-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim attached diff/spec evidence'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim attached diff/spec evidence'"
            "}"
            "},"
            "'evidence': {"
            "'changed_files': ['src/provider_dispatch.py', 'tests/test_provider_dispatch.py'],"
            "'diff_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex attached exact diff hunks.',"
            "'hunks': ["
            "{'check': 'diff_hunk', 'status': 'pass', 'severity': 'info', 'message': 'Fallback branch updated.', 'file_path': 'src/provider_dispatch.py', 'line_start': 12, 'line_end': 20, 'header': '@@ -12,6 +12,9 @@', 'excerpt': '+ workspace_root_used = workspace_root'},"
            "{'check': 'diff_hunk', 'status': 'pass', 'severity': 'info', 'message': 'Coverage added for bridge metadata.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 70, 'line_end': 92, 'header': '@@ -70,6 +70,18 @@', 'excerpt': '+ assert data[\\'evidence\\'][\\'metadata\\'][\\'provider\\'] == \\'codex\\''}"
            "]"
            "},"
            "'spec_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex mapped acceptance criteria to code regions.',"
            "'references': ["
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'Durable task draft coverage is preserved in the provider dispatch flow.', 'ac_id': 'AC-01', 'criterion': 'A durable task draft exists in the selected workspace.', 'file_path': 'src/provider_dispatch.py', 'line_start': 12, 'line_end': 20},"
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'Source prompt preservation is asserted in provider dispatch tests.', 'ac_id': 'AC-02', 'criterion': 'The source prompt is preserved as a task-scoped user message.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 70, 'line_end': 92}"
            "]"
            "}"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )
    return task


def create_task_with_provider_spec_drift_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-spec-drift-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim detected spec drift'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim detected spec drift'"
            "}"
            "},"
            "'evidence': {"
            "'changed_files': ['src/provider_dispatch.py'],"
            "'spec_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex found a mismatch between implementation and acceptance criteria.',"
            "'references': ["
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-01 is covered.', 'ac_id': 'AC-01', 'criterion': 'A durable task draft exists in the selected workspace.', 'file_path': 'src/provider_dispatch.py', 'line_start': 12, 'line_end': 20},"
            "{'check': 'spec_reference', 'status': 'fail', 'severity': 'critical', 'message': 'Source prompt preservation is not enforced in this code path.', 'ac_id': 'AC-02', 'criterion': 'The source prompt is preserved as a task-scoped user message.', 'file_path': 'src/provider_dispatch.py', 'line_start': 24, 'line_end': 28}"
            "]"
            "}"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )
    return task


def create_task_with_provider_diff_risk_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-diff-risk-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim attached risk-scored diff annotations'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim attached risk-scored diff annotations'"
            "}"
            "},"
            "'evidence': {"
            "'changed_files': ['src/provider_dispatch.py', 'tests/test_provider_dispatch.py'],"
            "'diff_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex scored diff regions by risk and confidence.',"
            "'hunks': ["
            "{'check': 'diff_hunk', 'status': 'fail', 'severity': 'critical', 'message': 'Dispatch path can bypass auth validation.', 'category': 'security', 'confidence': 0.94, 'suggestion': 'Add an explicit auth/token guard before dispatch.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 48, 'header': '@@ -40,6 +40,12 @@', 'excerpt': '+ token = request.headers.get(\"authorization\")'},"
            "{'check': 'diff_hunk', 'status': 'pass', 'severity': 'info', 'message': 'Test coverage reflects the new dispatch metadata.', 'category': 'coverage', 'confidence': 0.50, 'suggestion': 'Keep regression coverage when provider routing changes.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 91, 'line_end': 104, 'header': '@@ -91,6 +91,18 @@', 'excerpt': '+ assert dispatch.metadata[\"artifacts\"][\"bridge\"] == \"shim\"'}"
            "]"
            "},"
            "'spec_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex mapped every acceptance criterion for this patch.',"
            "'references': ["
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-01 is covered.', 'ac_id': 'AC-01', 'criterion': 'A durable task draft exists in the selected workspace.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 48},"
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-02 is covered.', 'ac_id': 'AC-02', 'criterion': 'The source prompt is preserved as a task-scoped user message.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 91, 'line_end': 104},"
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-03 is covered.', 'ac_id': 'AC-03', 'criterion': 'Sarathi creates a PRD/AC approval gate before task graph generation.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 48}"
            "]"
            "}"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )
    return task


def create_task_with_provider_clustered_diff_unit(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-clustered-diff-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim attached clustered diff annotations'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim attached clustered diff annotations'"
            "}"
            "},"
            "'evidence': {"
            "'changed_files': ['src/provider_dispatch.py', 'tests/test_provider_dispatch.py'],"
            "'diff_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex grouped multiple security hunks into one risky region.',"
            "'hunks': ["
            "{'check': 'diff_hunk', 'status': 'fail', 'severity': 'critical', 'message': 'Dispatch path can bypass auth validation.', 'category': 'security', 'confidence': 0.94, 'suggestion': 'Add an explicit auth/token guard before dispatch.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 48, 'header': '@@ -40,6 +40,12 @@', 'excerpt': '+ token = request.headers.get(\"authorization\")'},"
            "{'check': 'diff_hunk', 'status': 'pass', 'severity': 'major', 'message': 'Retry loop needs tighter exception scoping.', 'category': 'security', 'confidence': 0.54, 'suggestion': 'Narrow the caught exception surface around retryable failures.', 'file_path': 'src/provider_dispatch.py', 'line_start': 49, 'line_end': 56, 'header': '@@ -49,6 +49,10 @@', 'excerpt': '+ except Exception as exc:'},"
            "{'check': 'diff_hunk', 'status': 'pass', 'severity': 'info', 'message': 'Test coverage reflects the new dispatch metadata.', 'category': 'coverage', 'confidence': 0.5, 'suggestion': 'Keep regression coverage when provider routing changes.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 91, 'line_end': 104, 'header': '@@ -91,6 +91,18 @@', 'excerpt': '+ assert dispatch.metadata[\"artifacts\"][\"bridge\"] == \"shim\"'}"
            "]"
            "},"
            "'spec_trace': {"
            "'provider': 'codex',"
            "'summary': 'Codex mapped every acceptance criterion for this patch.',"
            "'references': ["
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-01 is covered.', 'ac_id': 'AC-01', 'criterion': 'A durable task draft exists in the selected workspace.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 56},"
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-02 is covered.', 'ac_id': 'AC-02', 'criterion': 'The source prompt is preserved as a task-scoped user message.', 'file_path': 'tests/test_provider_dispatch.py', 'line_start': 91, 'line_end': 104},"
            "{'check': 'spec_reference', 'status': 'pass', 'severity': 'major', 'message': 'AC-03 is covered.', 'ac_id': 'AC-03', 'criterion': 'Sarathi creates a PRD/AC approval gate before task graph generation.', 'file_path': 'src/provider_dispatch.py', 'line_start': 40, 'line_end': 56}"
            "]"
            "}"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )
    return task


def create_task_with_review_unit_without_evidence(app, tmp_path):
    task = create_task_with_approved_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/transition",
            {"status": "review", "actor": "Pravaha"},
        )
    )
    return task


def create_task_with_approved_graph(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    workspace_id = workspace_data["workspace"]["id"]
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Review dispatch evidence.", "title": "Review loop"},
        )
    )
    task = draft_data["task"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/graph-draft"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    return task


def _write_provider_script(path: Path, inline_python: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n" + inline_python + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
