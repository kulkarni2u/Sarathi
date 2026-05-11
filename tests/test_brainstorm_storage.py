from src.storage import Storage, connect, run_migrations


def make_storage(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    return Storage(conn)


def test_brainstorm_session_can_be_created_and_retrieved(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))

    session = storage.create_brainstorm_session(
        workspace_id=ws["id"],
        title="Add OAuth2 login",
    )

    assert session["id"]
    assert session["workspace_id"] == ws["id"]
    assert session["title"] == "Add OAuth2 login"
    assert session["status"] == "active"
    assert session["dialogue_turns"] == []
    assert session["research_findings"] == []
    assert session["spec_content"] is None


def test_brainstorm_session_turns_can_be_appended(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    turn = {"role": "sarathi", "content": "Which approach?", "options": ["A", "B"]}
    updated = storage.append_brainstorm_turn(session["id"], turn)

    assert len(updated["dialogue_turns"]) == 1
    assert updated["dialogue_turns"][0]["content"] == "Which approach?"


def test_brainstorm_session_research_can_be_appended(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    finding = {"agent": "Vichara", "type": "codebase", "summary": "Found src/auth.py"}
    updated = storage.append_brainstorm_research(session["id"], finding)

    assert len(updated["research_findings"]) == 1
    assert updated["research_findings"][0]["agent"] == "Vichara"


def test_brainstorm_session_spec_can_be_updated(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    updated = storage.update_brainstorm_spec(session["id"], "## Goal\nAdd auth")

    assert updated["spec_content"] == "## Goal\nAdd auth"


def test_brainstorm_session_can_be_approved(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    session = storage.create_brainstorm_session(workspace_id=ws["id"], title="Test")

    approved = storage.approve_brainstorm_session(session["id"])

    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None


def test_brainstorm_sessions_can_be_listed_by_status(tmp_path):
    storage = make_storage(tmp_path)
    ws = storage.create_workspace(name="ws", root_path=str(tmp_path))
    s1 = storage.create_brainstorm_session(workspace_id=ws["id"], title="Active one")
    s2 = storage.create_brainstorm_session(workspace_id=ws["id"], title="To approve")
    storage.approve_brainstorm_session(s2["id"])

    active = storage.list_brainstorm_sessions(ws["id"], status="active")
    approved = storage.list_brainstorm_sessions(ws["id"], status="approved")
    all_sessions = storage.list_brainstorm_sessions(ws["id"])

    assert len(active) == 1 and active[0]["id"] == s1["id"]
    assert len(approved) == 1 and approved[0]["id"] == s2["id"]
    assert len(all_sessions) == 2
