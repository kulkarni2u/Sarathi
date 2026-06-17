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
