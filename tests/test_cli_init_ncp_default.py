"""Tests for NCP-by-default `sarathi init` behavior.

NCP bounds context (max_chunk_tokens) and routes whispers between graph
nodes instead of every phase/node replaying full context, so it's now
bootstrapped by default rather than requiring an explicit --ncp flag.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from unittest.mock import patch

from src.cli import _bootstrap_ncp, handle_init


def _init_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = dict(
        target_path=str(tmp_path),
        engine="markdown",
        no_wiki=True,
        no_index=True,
        from_source=None,
        force=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_init_bootstraps_ncp_by_default(tmp_path: Path):
    handle_init(_init_args(tmp_path))

    ncp_dir = tmp_path / ".ncp"
    assert (ncp_dir / "config.toml").exists()
    assert (ncp_dir / "run.py").exists()
    assert (ncp_dir / "WELCOME.md").exists()


def test_init_no_ncp_flag_skips_bootstrap(tmp_path: Path):
    handle_init(_init_args(tmp_path, no_ncp=True))

    assert not (tmp_path / ".ncp").exists()


def test_init_sarathi_optimized_config_present_by_default(tmp_path: Path):
    handle_init(_init_args(tmp_path))

    config = (tmp_path / ".ncp" / "config.toml").read_text()
    assert "Sarathi-optimized" in config
    assert "max_chunk_tokens = 400" in config


def test_bootstrap_ncp_degrades_gracefully_when_ncp_binary_missing(tmp_path: Path, capsys):
    """A missing `ncp` CLI must warn, not crash init -- Sarathi's own sidecar
    files come from bundled templates and don't need the binary at all."""
    with patch("subprocess.run", side_effect=FileNotFoundError("no such file: ncp")):
        _bootstrap_ncp(tmp_path, step_label="[5/5]")

    output = capsys.readouterr().out
    assert "NCP init skipped" in output
    assert (tmp_path / ".ncp" / "config.toml").exists()
    assert (tmp_path / ".ncp" / "run.py").exists()


def test_bootstrap_ncp_warns_on_nonzero_exit_but_still_writes_sidecar(tmp_path: Path, capsys):
    fake_result = subprocess.CompletedProcess(args=["ncp", "init"], returncode=1, stdout="", stderr="boom")
    with patch("subprocess.run", return_value=fake_result):
        _bootstrap_ncp(tmp_path, step_label="[5/5]")

    output = capsys.readouterr().out
    assert "NCP init warning" in output
    assert (tmp_path / ".ncp" / "config.toml").exists()


def test_init_from_import_also_bootstraps_ncp_by_default(tmp_path: Path):
    source = tmp_path / "source-pack"
    (source / "policy-pack").mkdir(parents=True)
    (source / "policy-pack" / "commands.md").write_text("# Commands\n")

    target = tmp_path / "target"
    target.mkdir()
    handle_init(_init_args(target, from_source=str(source / "policy-pack")))

    assert (target / ".ncp" / "config.toml").exists()


def test_init_from_import_no_ncp_skips_bootstrap(tmp_path: Path):
    source = tmp_path / "source-pack"
    (source / "policy-pack").mkdir(parents=True)
    (source / "policy-pack" / "commands.md").write_text("# Commands\n")

    target = tmp_path / "target"
    target.mkdir()
    handle_init(_init_args(target, from_source=str(source / "policy-pack"), no_ncp=True))

    assert not (target / ".ncp").exists()
