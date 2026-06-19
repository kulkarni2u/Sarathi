"""Tests for the one-line installer script."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_install_script_dry_run_detects_local_checkout():
    result = subprocess.run(
        ["bash", "scripts/install.sh", "--dry-run"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"install spec : {PROJECT_ROOT}" in output
    assert "spec source  : local checkout" in output


def test_install_script_python_floor_matches_ncp_dependency():
    content = (PROJECT_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert "MIN_PY_MAJOR=3" in content
    assert "MIN_PY_MINOR=11" in content
    assert "Python >= 3.11" in content
