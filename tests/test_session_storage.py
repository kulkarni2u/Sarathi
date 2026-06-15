from src.storage import Storage, connect, run_migrations


def _setup(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    storage = Storage(conn)
    workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
    task = storage.create_task(
        workspace_id=workspace["id"],
        title="Pair on T4.1",
        status="in_progress",
    )
    return conn, storage, workspace, task


def test_create_session_auto_creates_owner_participant(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )

        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        assert session["id"]
        assert session["share_token"]
        assert session["visibility"] == "private"
        assert session["status"] == "active"
        assert session["owner"] == "alice"

        participants = storage.list_session_participants(session["id"])
        assert len(participants) == 1
        owner = participants[0]
        assert owner["user"] == "alice"
        assert owner["role"] == "owner"
        assert owner["status"] == "active"


def test_get_session_and_by_share_token_round_trip(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )

        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
            metadata={"note": "kickoff"},
        )

        assert storage.get_session(session["id"]) == session
        assert storage.get_session_by_share_token(session["share_token"]) == session
        assert storage.get_session("missing") is None
        assert storage.get_session_by_share_token("nope") is None
        assert session["metadata"] == {"note": "kickoff"}


def test_add_participant_and_list(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        observer = storage.add_session_participant(
            session_id=session["id"],
            user="bob",
        )
        assert observer["role"] == "observer"
        assert observer["status"] == "active"

        participants = storage.list_session_participants(session["id"])
        users = {p["user"]: p["role"] for p in participants}
        assert users == {"alice": "owner", "bob": "observer"}


def test_add_participant_upserts_same_user(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        storage.add_session_participant(session_id=session["id"], user="bob")
        storage.add_session_participant(
            session_id=session["id"],
            user="bob",
            role="driver",
        )

        bob_rows = [
            p
            for p in storage.list_session_participants(session["id"])
            if p["user"] == "bob"
        ]
        assert len(bob_rows) == 1
        assert bob_rows[0]["role"] == "driver"
        assert bob_rows[0]["status"] == "active"


def test_remove_participant_soft_deletes(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )
        storage.add_session_participant(session_id=session["id"], user="bob")

        removed = storage.remove_session_participant(session["id"], "bob")
        assert removed["status"] == "left"

        still_present = storage.get_session_participant(session["id"], "bob")
        assert still_present is not None
        assert still_present["status"] == "left"
        assert len(storage.list_session_participants(session["id"])) == 2


def test_update_session_changes_visibility_and_status(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        updated = storage.update_session(
            session["id"],
            visibility="link",
            status="closed",
        )
        assert updated["visibility"] == "link"
        assert updated["status"] == "closed"

        try:
            storage.update_session("missing", status="closed")
        except KeyError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected KeyError for missing session")


def test_list_sessions_for_task(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        sessions = storage.list_sessions_for_task(task["id"])
        assert [s["id"] for s in sessions] == [session["id"]]


def test_message_session_scoping(tmp_path):
    with connect(tmp_path / "sarathi.db") as conn:
        run_migrations(conn)
        storage = Storage(conn)
        workspace = storage.create_workspace(name="Co-drive", root_path="/work/codrive")
        task = storage.create_task(
            workspace_id=workspace["id"],
            title="Pair on T4.1",
            status="in_progress",
        )
        session = storage.create_session(
            workspace_id=workspace["id"],
            task_id=task["id"],
            owner="alice",
        )

        scoped = storage.create_message(
            workspace_id=workspace["id"],
            task_id=task["id"],
            session_id=session["id"],
            role="user",
            content="hello session",
        )
        unscoped = storage.create_message(
            workspace_id=workspace["id"],
            task_id=task["id"],
            role="user",
            content="hello task",
        )

        assert scoped["session_id"] == session["id"]
        assert unscoped["session_id"] is None

        by_session = storage.list_messages(session_id=session["id"])
        assert [m["id"] for m in by_session] == [scoped["id"]]

        by_task = storage.list_messages(task_id=task["id"])
        by_task_ids = {m["id"] for m in by_task}
        assert scoped["id"] in by_task_ids
        assert unscoped["id"] in by_task_ids
