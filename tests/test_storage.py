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


def test_get_methods_return_none_for_missing_records(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)

        assert storage.get_workspace("missing") is None
        assert storage.get_task("missing") is None
