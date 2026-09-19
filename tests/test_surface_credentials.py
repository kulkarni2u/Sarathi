

from src.service import create_app
from src.service.providers import _provider_dispatch_adapter_config
from src.storage import Storage, connect


def _workspace(app, tmp_path):
    status, payload = app.handle(
        "POST", "/api/workspaces", body={"name": "Credentials", "root_path": str(tmp_path)}
    )
    assert status == 201
    return payload["data"]["workspace"]


def test_provider_configuration_rejects_raw_api_key(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = _workspace(app, tmp_path)

    status, payload = app.handle(
        "POST",
        f"/api/workspaces/{workspace['id']}/providers/codex/test",
        body={"api_key": "sk-secret", "path": ""},
    )

    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
    with connect(tmp_path / "sarathi.db") as conn:
        assert Storage(conn).get_provider(workspace["id"], "codex") is None


def test_provider_configuration_uses_environment_name_and_dispatch_never_persists_key(tmp_path, monkeypatch):
    app = create_app(tmp_path / "sarathi.db")
    workspace = _workspace(app, tmp_path)
    monkeypatch.setenv("SARATHI_TEST_KEY", "sk-secret")

    status, payload = app.handle(
        "POST",
        f"/api/workspaces/{workspace['id']}/providers/codex/test",
        body={"api_key_env": "SARATHI_TEST_KEY", "path": ""},
    )

    assert status == 200
    assert payload["data"]["provider"]["api_key_env"] == "SARATHI_TEST_KEY"
    with connect(tmp_path / "sarathi.db") as conn:
        storage = Storage(conn)
        record = storage.get_provider(workspace["id"], "codex")
        assert record is not None
        assert "api_key" not in record["config"]
        dispatch = _provider_dispatch_adapter_config(
            storage, workspace_id=workspace["id"], provider_id="codex"
        )
        assert "api_key" not in dispatch["providers"]["codex"]


def test_legacy_raw_key_is_removed_and_provider_needs_auth(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = _workspace(app, tmp_path)
    with connect(tmp_path / "sarathi.db") as conn:
        storage = Storage(conn)
        storage.upsert_provider(
            workspace_id=workspace["id"],
            provider_id="codex",
            name="Codex",
            provider_type="sdk",
            config={"path": "", "api_key": "sk-legacy", "health": "online"},
        )

    status, payload = app.handle("GET", f"/api/providers?workspace_id={workspace['id']}")

    assert status == 200
    provider = next(p for p in payload["data"]["providers"] if p["id"] == "codex")
    assert provider["auth"] == "needs_auth"
    with connect(tmp_path / "sarathi.db") as conn:
        record = Storage(conn).get_provider(workspace["id"], "codex")
        assert record is not None
        assert "api_key" not in record["config"]
