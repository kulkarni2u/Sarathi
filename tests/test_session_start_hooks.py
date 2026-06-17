import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "skill" / "hooks" / "session-start"


def _run_hook(cwd: Path, **env: str) -> dict:
    hook_env = os.environ.copy()
    hook_env.update(env)
    result = subprocess.run(
        ["bash", str(HOOK)],
        cwd=cwd,
        env=hook_env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_session_start_hook_noops_outside_sarathi_workspace(tmp_path):
    payload = _run_hook(tmp_path)

    assert payload == {}


def test_session_start_hook_detects_sarathi_workspace_and_injects_context(tmp_path):
    workspace = tmp_path / "repo"
    nested = workspace / "src" / "package"
    (workspace / "policy-pack").mkdir(parents=True)
    nested.mkdir(parents=True)

    payload = _run_hook(nested)

    assert "additionalContext" in payload
    context = payload["additionalContext"]
    assert "SARATHI_SESSION_START" in context
    assert f"Sarathi workspace detected at: {workspace}" in context
    assert "Below is the full content of your 'sarathi' skill" in context


def test_session_start_hook_uses_claude_hook_specific_output(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "SARATHI.md").write_text("# Sarathi\n")

    payload = _run_hook(workspace, CLAUDE_PLUGIN_ROOT=str(REPO_ROOT / "skill"))

    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "SARATHI_SESSION_START" in hook_output["additionalContext"]


def test_hook_assets_are_in_packaging_config():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    manifest = (REPO_ROOT / "MANIFEST.in").read_text()

    assert "share/sarathi/skill/hooks" in pyproject
    assert "skill/hooks/session-start" in pyproject
    assert "share/sarathi/skill/.opencode/plugins" in pyproject
    assert "skill/.opencode/plugins/sarathi.js" in pyproject
    assert "recursive-include skill/hooks *" in manifest
    assert "recursive-include skill/.opencode *" in manifest


def test_opencode_plugin_bootstrap_asset_exists():
    plugin = REPO_ROOT / "skill" / ".opencode" / "plugins" / "sarathi.js"

    text = plugin.read_text()

    assert "experimental.chat.messages.transform" in text
    assert "SARATHI_SESSION_START" in text
    assert "policy-pack" in text
    assert "config.skills.paths" in text
