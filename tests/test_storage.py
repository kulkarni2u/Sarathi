from src.storage import Storage, connect, run_migrations


def test_storage_can_create_get_and_list_workspaces(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        workspace = storage.create_workspace(
            name="Pravaha UI",
            root_path="/work/pravaha",
            metadata={"owner": "sutra"},
        )

        assert workspace["id"]
        assert workspace["name"] == "Pravaha UI"
        assert workspace["root_path"] == "/work/pravaha"
        assert workspace["metadata"] == {"owner": "sutra"}
        assert storage.get_workspace(workspace["id"]) == workspace
        assert storage.list_workspaces() == [workspace]


def test_storage_can_create_and_get_task_for_workspace(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(
            name="Pravaha UI",
            root_path="/work/pravaha",
        )

        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Add SQLite storage",
            status="in_progress",
            description="Persist Sarathi UI workspace state.",
            metadata={"ticket": "UI-02"},
        )

        assert task["id"]
        assert task["workspace_id"] == workspace["id"]
        assert task["title"] == "Add SQLite storage"
        assert task["status"] == "in_progress"
        assert task["description"] == "Persist Sarathi UI workspace state."
        assert task["metadata"] == {"ticket": "UI-02"}
        assert storage.get_task(task["id"]) == task


def test_storage_checkpoint_capsule_round_trip(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="QA", root_path="/tmp/qa")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Checkpoint source",
            status="done",
            metadata={"phase": "done"},
        )
        checkpoint = storage.create_checkpoint_capsule(
            workspace_id=workspace["id"],
            task_id=task["id"],
            summary="Task completed and ready for a fresh session.",
            key_decisions=["Keep commit/PR default-off"],
            evidence_refs=["evidence:123"],
            repository_action_preference={"scope": "workspace", "mode": "no_action"},
            next_start_point="Open a new session from the completed result.",
            created_by="Sarathi",
        )
        assert checkpoint["source_task_id"] == task["id"]
        assert checkpoint["summary"] == "Task completed and ready for a fresh session."
        assert storage.get_checkpoint_capsule(checkpoint["id"]) is not None
        assert storage.list_checkpoint_capsules_for_task(task["id"])[0]["id"] == checkpoint["id"]


def test_storage_task_panel_projection_merges_messages_events_and_dispatches(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Pravaha UI", root_path="/work/pravaha")
        task = storage.create_task(workspace_id=workspace["id"], title="Panel", status="in_progress")

        human = storage.create_message(
            workspace_id=workspace["id"],
            task_id=task["id"],
            role="user",
            content="Start the panel flow.",
            metadata={"target": "Sarathi"},
        )
        blocked = storage.create_lifecycle_event(
            workspace_id=workspace["id"],
            task_id=task["id"],
            event_type="task.blocked",
            payload={"reason": "waiting_user"},
        )
        gate = storage.create_approval_gate(
            workspace_id=workspace["id"],
            task_id=task["id"],
            name="PRD/AC",
            status="pending",
            metadata={"requires_human": True},
        )
        dispatch = storage.create_dispatch(
            workspace_id=workspace["id"],
            task_id=task["id"],
            agent_name="Pravaha",
            status="queued",
            metadata={"subtask_id": "subtask-1"},
        )
        evidence = storage.create_evidence_artifact(
            workspace_id=workspace["id"],
            task_id=task["id"],
            artifact_type="doc",
            uri="sarathi://evidence/doc-1",
            metadata={"note": "panel evidence"},
        )
        review = storage.create_review_run(
            workspace_id=workspace["id"],
            task_id=task["id"],
            status="approved",
            summary="Review approved.",
            metadata={"review_type": "code"},
        )
        handoff = storage.create_handoff(
            workspace_id=workspace["id"],
            task_id=task["id"],
            summary="Handoff to Disha for implementation.",
            from_agent="Pravaha",
            to_agent="Disha",
            metadata={"handoff_type": "panel"},
        )

        entries = storage.list_task_panel_entries(task["id"])

        assert [entry["kind"] for entry in entries] == [
            "human_message",
            "blocked",
            "review",
            "claimed",
            "evidence",
            "review",
            "handoff",
        ]
        assert entries[0]["id"] == human["id"]
        assert entries[0]["source"] == "user"
        assert entries[0]["summary"] == "Start the panel flow."
        assert entries[1]["id"] == blocked["id"]
        assert entries[1]["summary"] == "Task blocked: waiting_user"
        assert entries[2]["id"] == gate["id"]
        assert entries[3]["id"] == dispatch["id"]
        assert entries[3]["target"] == "subtask-1"
        assert entries[4]["id"] == evidence["id"]
        assert entries[5]["id"] == review["id"]
        assert entries[6]["id"] == handoff["id"]
        assert all(entry["task_id"] == task["id"] for entry in entries)
        assert all(entry["workspace_id"] == workspace["id"] for entry in entries)


def test_get_methods_return_none_for_missing_records(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        assert storage.get_workspace("missing") is None
        assert storage.get_task("missing") is None
