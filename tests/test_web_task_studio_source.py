from pathlib import Path


def test_task_graph_approval_button_dispatches_ready_units():
    source = Path("web/src/views/TaskStudio/index.tsx").read_text(encoding="utf-8")
    branch_start = source.index('} else if (name === "Task graph") {')
    branch_end = source.index("      } else {", branch_start)
    branch = source[branch_start:branch_end]

    assert "api.recordApproval" in branch
    assert "api.scheduleTask(taskId)" in branch


def test_task_studio_renders_only_current_pending_approval_gates():
    source = Path("web/src/views/TaskStudio/index.tsx").read_text(encoding="utf-8")
    assert "function currentApprovalGates" in source
    pending_start = source.index("const pendingApprovals = useMemo(")
    pending_end = source.index("  // Auto-scroll", pending_start)
    pending_block = source[pending_start:pending_end]

    assert "currentApprovalGates(approvals)" in pending_block


def test_task_studio_normalizes_graph_row_provider_ids_before_dispatch():
    source = Path("web/src/views/TaskStudio/index.tsx").read_text(encoding="utf-8")
    assert "function normalizeProviderId" in source
    assert "normalizeProviderId(stringField(node, \"provider\"))" in source
    assert "provider: selectedProvider" in source


def test_task_studio_review_tab_can_run_governed_review():
    client = Path("web/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("web/src/views/TaskStudio/index.tsx").read_text(encoding="utf-8")

    assert "runTaskReview(" in client
    assert "/reviews/run" in client
    assert "<ReviewTab data={data} taskId={taskId} onChanged={onChanged} />" in source
    assert "api.runTaskReview(taskId, { review_type: \"functional\" })" in source
    assert "Run review" in source
    assert "[activeTab]: undefined" in source


def test_task_studio_action_labels_describe_actual_work():
    source = Path("web/src/views/TaskStudio/index.tsx").read_text(encoding="utf-8")

    assert "\"Approve & draft graph\"" in source
    assert "\"Approve & dispatch\"" in source
    assert "\"Schedule ready work\"" in source
