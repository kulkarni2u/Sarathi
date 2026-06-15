import pytest

from src.storage import Storage, connect, run_migrations


def _setup(tmp_path):
    conn = connect(tmp_path / "sarathi.db")
    run_migrations(conn)
    storage = Storage(conn)
    return conn, storage


def test_create_user_generates_token_and_defaults_active(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        user = storage.create_user(username="alice")

        assert user["id"]
        assert user["username"] == "alice"
        assert user["token"]
        assert user["status"] == "active"
        assert user["metadata"] == {}


def test_user_lookups_round_trip(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        created = storage.create_user(
            username="bob",
            display_name="Bob Builder",
        )

        assert storage.get_user(created["id"]) == created
        assert storage.get_user_by_token(created["token"]) == created
        assert storage.get_user_by_username("bob") == created


def test_users_have_distinct_tokens_and_list_returns_all(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        first = storage.create_user(username="carol")
        second = storage.create_user(username="dave")

        assert first["token"] != second["token"]

        users = storage.list_users()
        ids = {user["id"] for user in users}
        assert {first["id"], second["id"]} <= ids
        assert len(users) == 2


def test_create_user_uses_explicit_token(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        user = storage.create_user(username="erin", token="explicit-token-123")

        assert user["token"] == "explicit-token-123"
        assert storage.get_user_by_token("explicit-token-123") == user


def test_update_user_changes_display_name_and_status(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        user = storage.create_user(username="frank", display_name="Frank")

        updated = storage.update_user(
            user["id"],
            display_name="Franklin",
            status="disabled",
        )

        assert updated["display_name"] == "Franklin"
        assert updated["status"] == "disabled"
        assert updated["username"] == "frank"


def test_update_user_missing_id_raises_key_error(tmp_path):
    conn, storage = _setup(tmp_path)
    with conn:
        with pytest.raises(KeyError):
            storage.update_user("does-not-exist", status="disabled")
