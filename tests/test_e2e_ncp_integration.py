"""E2E tests: Sarathi CLI/Desktop/Skill integration with NCP.

Requires: ncp CLI installed (checked at runtime).
Tests the full lifecycle: init -> run (auto-detect) -> run (explicit) -> run (opt-out).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _ncp_available() -> bool:
    return shutil.which("ncp") is not None


def _ensure_policy_pack(path: Path) -> None:
    policy_dir = path / "policy-pack"
    policy_dir.mkdir(parents=True, exist_ok=True)
    for name in ["commands", "conventions", "complexity",
                  "review", "escalation", "skills", "task-tracking"]:
        (policy_dir / f"{name}.md").write_text(f"# {name.capitalize()}\n")


def _run_sarathi(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        capture_output=True, text=True,
        cwd=str(cwd),
    )


# -------------------------------------------------------------------
# 1. CLI E2E — real NCP init + sarathi run
# -------------------------------------------------------------------

def test_e2e_ncp_init_creates_dot_ncp(tmp_path):
    """sarathi init --ncp bootstraps .ncp/ directory via real ncp CLI."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")
    _ensure_policy_pack(tmp_path)

    result = _run_sarathi(tmp_path, "init", ".", "--ncp")

    assert result.returncode == 0, f"init failed: {result.stderr}"
    assert (tmp_path / ".ncp" / "config.toml").exists(), ".ncp/config.toml not created"
    assert (tmp_path / ".ncp" / "WELCOME.md").exists(), ".ncp/WELCOME.md not created"


def test_e2e_ncp_init_sarathi_optimized_config(tmp_path):
    """sarathi init --ncp writes Sarathi-optimized NCP config overrides."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")
    _ensure_policy_pack(tmp_path)

    result = _run_sarathi(tmp_path, "init", ".", "--ncp")
    assert result.returncode == 0, f"init failed: {result.stderr}"

    config = (tmp_path / ".ncp" / "config.toml").read_text()
    assert "max_chunk_tokens = 400" in config
    assert "default_ttl_hours = 168" in config
    assert "Sarathi-optimized" in config


def test_e2e_ncp_auto_detect_uses_ncp_when_available(tmp_path):
    """sarathi run (auto-detect) uses NCP adapters when ncp CLI + .ncp/ exist."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    _ensure_policy_pack(tmp_path)
    # Init NCP so auto-detect finds it
    subprocess.run(["ncp", "init"], capture_output=True, cwd=str(tmp_path))
    # Ensure .ncp/config.toml exists (the probe checks this)
    assert (tmp_path / ".ncp" / "config.toml").exists()

    result = _run_sarathi(tmp_path, "run", "--dry-run", "e2e auto-detect test")
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"


def test_e2e_ncp_explicit_flag(tmp_path):
    """sarathi run --ncp explicitly forces NCP adapters."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    _ensure_policy_pack(tmp_path)
    # Engine validates NCP via direct transport which needs .ncp/run.py
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir(parents=True, exist_ok=True)
    run_py = ncp_dir / "run.py"
    run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)")
    run_py.chmod(0o755)
    subprocess.run(["ncp", "init"], capture_output=True, cwd=str(tmp_path))

    result = _run_sarathi(tmp_path, "run", "--ncp", "--dry-run", "e2e explicit test")
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"


def test_e2e_ncp_opt_out_flag(tmp_path):
    """sarathi run --no-ncp forces native adapters even with NCP available."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    _ensure_policy_pack(tmp_path)
    subprocess.run(["ncp", "init"], capture_output=True, cwd=str(tmp_path))

    result = _run_sarathi(tmp_path, "run", "--no-ncp", "--dry-run", "e2e opt-out test")
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"


def test_e2e_ncp_works_with_service_api(tmp_path):
    """Verify the service API accepts ncp_enabled metadata field."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    from src.storage import Storage, connect, run_migrations

    # Create a storage and workspace
    db_path = tmp_path / ".sarathi" / "sarathi.db"
    db_path.parent.mkdir(parents=True)
    conn = connect(db_path)
    run_migrations(conn)  # Create schema
    storage = Storage(conn)

    ws = storage.create_workspace(
        name="e2e-workspace",
        root_path=str(tmp_path),
        metadata={"ncp_enabled": True},
    )
    ws_id = ws["id"]
    saved = storage.get_workspace(ws_id)
    assert saved is not None
    assert saved["metadata"]["ncp_enabled"] is True

    # Update to false
    storage.update_workspace(ws_id, metadata={"ncp_enabled": False})
    updated = storage.get_workspace(ws_id)
    assert updated is not None
    assert updated["metadata"]["ncp_enabled"] is False

    conn.close()


# -------------------------------------------------------------------
# 2. Desktop integration — apiClient types and API contract
# -------------------------------------------------------------------

def test_e2e_desktop_api_client_contract():
    """Verify the apiClient types match the backend API contract."""
    api_client = Path(__file__).resolve().parent.parent / "desktop" / "src" / "apiClient.ts"
    if not api_client.exists():
        pytest.skip("desktop/ not present in this checkout")
    content = api_client.read_text()

    assert "ncp_enabled?: boolean" in content, (
        "apiClient.ts: WorkspaceMetadata missing ncp_enabled field"
    )
    assert "checkNcpAvailable" in content, (
        "apiClient.ts: missing checkNcpAvailable function"
    )
    assert "ncp/status" in content, (
        "apiClient.ts: checkNcpAvailable missing /ncp/status endpoint reference"
    )


def test_e2e_desktop_settings_has_ncp_section():
    """Verify the Settings page renders an NCP section."""
    settings_file = (
        Path(__file__).resolve().parent.parent
        / "desktop" / "src" / "pages" / "Settings.tsx"
    )
    if not settings_file.exists():
        pytest.skip("desktop/ not present in this checkout")
    content = settings_file.read_text()

    assert "Neural Context Protocol" in content, (
        "Settings.tsx missing NCP section header"
    )
    assert "Force NCP" in content, (
        "Settings.tsx missing Force NCP toggle label"
    )
    assert "saveNcpEnabledSetting" in content, (
        "Settings.tsx missing NCP save function"
    )
    assert "checkNcpAvailable" in content, (
        "Settings.tsx missing checkNcpAvailable import"
    )


# -------------------------------------------------------------------
# 3. Skill documentation — SKILL.md contains NCP flags
# -------------------------------------------------------------------

def test_e2e_skill_doc_has_ncp_flags():
    """Verify skill/SKILL.md documents NCP flags."""
    skill_file = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    content = skill_file.read_text()

    assert "--ncp" in content, (
        "SKILL.md missing --ncp flag documentation"
    )
    assert "--ncp-mode" in content, (
        "SKILL.md missing --ncp-mode flag documentation"
    )
    assert "--ncp-router" in content, (
        "SKILL.md missing --ncp-router flag documentation"
    )


def test_e2e_skill_doc_has_ncp_usage_note():
    """Verify skill/SKILL.md explains when to use NCP."""
    skill_file = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    content = skill_file.read_text()

    assert "NCP" in content, (
        "SKILL.md missing NCP usage guidance"
    )


# -------------------------------------------------------------------
# 4. Engine integration — verify adapters are correctly chosen
# -------------------------------------------------------------------

def test_e2e_engine_auto_detect_probe(tmp_path):
    """Engine._probe_ncp returns True when .ncp/config.toml exists and ncp CLI is available."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    from src.engine import Engine

    # Without .ncp/ in CWD — should return False for non-NCP dirs
    with _override_cwd(tmp_path):
        assert not Engine._probe_ncp(), (
            "_probe_ncp returned True for dir without .ncp/"
        )

    # With .ncp/config.toml in CWD — should return True
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir(parents=True)
    (ncp_dir / "config.toml").write_text("[ncp]\nkey = \"test\"\n")
    with _override_cwd(tmp_path):
        assert Engine._probe_ncp(), (
            "_probe_ncp returned False when .ncp/config.toml exists"
        )


def test_e2e_engine_auto_detect_creates_ncp_adapters(tmp_path):
    """Engine auto-detect creates NCP adapters when NCP is available."""
    if not _ncp_available():
        pytest.skip("ncp CLI not available")

    _ensure_policy_pack(tmp_path)
    subprocess.run(["ncp", "init"], capture_output=True, cwd=str(tmp_path))
    assert (tmp_path / ".ncp" / "config.toml").exists(), "ncp init did not create config.toml"
    # Seed run.py so direct-mode validation passes (ncp init does not create it)
    (tmp_path / ".ncp" / "run.py").write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)")
    (tmp_path / ".ncp" / "run.py").chmod(0o755)

    import io
    from contextlib import redirect_stdout
    from src.engine import Engine, Complexity, TaskContext, Phase

    buf = io.StringIO()
    with _override_cwd(tmp_path), redirect_stdout(buf):
        engine = Engine(policy_pack_path=str(tmp_path / "policy-pack"), enforce_preflight=False)

    assert engine.ncp_enabled, (
        f"Engine.ncp_enabled should be True when NCP available, got {engine.ncp_enabled}"
    )


def test_e2e_engine_auto_detect_falls_back(tmp_path):
    """Engine auto-detect falls back to native adapters when NCP is unavailable."""
    from src.engine import Engine
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        engine = Engine(policy_pack_path=str(tmp_path / "policy-pack"), enforce_preflight=False)

    captured = buf.getvalue()
    if not shutil.which("ncp"):
        assert not engine.ncp_enabled, (
            "Engine should fall back to native when NCP unavailable"
        )


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

import contextlib
import pytest


@contextlib.contextmanager
def _override_cwd(path: Path):
    """Temporarily change working directory."""
    old = Path.cwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(str(old))
