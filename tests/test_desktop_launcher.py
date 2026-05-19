import json
import subprocess
import sys

from src.service.desktop import (
    build_launch_config,
    connect_base_url,
    default_db_path,
    render_runtime_script,
    render_runtime_stub,
)


def test_desktop_launcher_module_exposes_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.service.desktop", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Run the Sarathi local desktop stack with runtime config wiring." in result.stdout
    assert "--print-config" in result.stdout
    assert "--service-port" in result.stdout
    assert "--service-timeout" in result.stdout


def test_render_runtime_script_contains_base_url_and_token():
    script = render_runtime_script(base_url="http://127.0.0.1:8765", token="secret-token")

    assert "__SARATHI_RUNTIME_CONFIG__" in script
    assert "http://127.0.0.1:8765" in script
    assert "secret-token" in script


def test_render_runtime_stub_is_safe_default():
    assert render_runtime_stub() == "window.__SARATHI_RUNTIME_CONFIG__ = window.__SARATHI_RUNTIME_CONFIG__ || {};\n"


def test_build_launch_config_uses_random_token_and_default_db(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    namespace = type(
        "Args",
        (),
        {
            "db": None,
            "token": None,
            "service_host": "127.0.0.1",
            "service_port": 8765,
            "vite_host": "127.0.0.1",
            "vite_port": 5173,
            "service_timeout": 18.0,
            "runtime_script": None,
        },
    )()

    config = build_launch_config(namespace)

    assert config["db_path"].endswith(str(default_db_path()))
    assert config["base_url"] == "http://127.0.0.1:8765"
    assert config["service_timeout"] == 18.0
    assert config["token"]


def test_connect_base_url_normalizes_wildcard_hosts():
    assert connect_base_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert connect_base_url("::", 8765) == "http://127.0.0.1:8765"
    assert connect_base_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"


def test_desktop_launcher_print_config_returns_json():
    result = subprocess.run(
        [sys.executable, "-m", "src.service.desktop", "--print-config", "--token", "fixed"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["token"] == "fixed"
    assert payload["base_url"].startswith("http://127.0.0.1:")
