"""Tests for NCP-by-default `sarathi init` behavior.

NCP bounds context (its [budget] token budget) and routes whispers between graph
nodes instead of every phase/node replaying full context, so it's now
bootstrapped by default rather than requiring an explicit --ncp flag.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from unittest.mock import patch

import tomllib

from src.cli import _apply_ncp_config_overrides, _bootstrap_ncp, handle_init


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

    config = tomllib.loads((tmp_path / ".ncp" / "config.toml").read_text())
    assert config["pipeline"]["default_ttl_hours"] == 168
    assert config["tools"]["profile"] == "standard"
    assert "max_chunk_tokens" not in str(config)


def test_ncp_overrides_go_into_existing_tables(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[pipeline]\nmax_working_chunks = 500\n\n[embedding]\nenabled = true\n"
    )

    applied = _apply_ncp_config_overrides(config_path)

    config = tomllib.loads(config_path.read_text())
    assert applied == ["pipeline.default_ttl_hours=168", "tools.profile=standard"]
    assert config["pipeline"] == {"default_ttl_hours": 168, "max_working_chunks": 500}
    assert config["tools"] == {"profile": "standard"}
    assert config["embedding"] == {"enabled": True}


def test_ncp_overrides_keep_user_values_and_are_idempotent(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[pipeline]\ndefault_ttl_hours = 72\n\n[tools]\nprofile = "full"\n')

    assert _apply_ncp_config_overrides(config_path) == []
    assert _apply_ncp_config_overrides(config_path) == []

    config = tomllib.loads(config_path.read_text())
    assert config["pipeline"]["default_ttl_hours"] == 72
    assert config["tools"]["profile"] == "full"


def test_ncp_overrides_replace_ncp_generated_default_in_place(tmp_path: Path):
    """`ncp init` writes default_ttl_hours = 24 explicitly; that is NCP's default, not a user choice."""
    config_path = tmp_path / "config.toml"
    config_path.write_text("[pipeline]\ndefault_ttl_hours = 24\nmax_working_chunks = 500\n")

    assert _apply_ncp_config_overrides(config_path) == [
        "pipeline.default_ttl_hours=168",
        "tools.profile=standard",
    ]
    assert _apply_ncp_config_overrides(config_path) == []

    text = config_path.read_text()
    assert text.count("default_ttl_hours") == 1
    assert tomllib.loads(text)["pipeline"] == {"default_ttl_hours": 168, "max_working_chunks": 500}


def test_ncp_overrides_remove_legacy_block_that_landed_in_last_table(tmp_path: Path):
    """Earlier releases appended the keys after [embedding], where NCP ignored them."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[pipeline]\nmax_working_chunks = 500\n\n[embedding]\nenabled = true\n"
        "# Sarathi-optimized overrides\nmax_chunk_tokens = 400\ndefault_ttl_hours = 168\n"
    )

    _apply_ncp_config_overrides(config_path)

    text = config_path.read_text()
    config = tomllib.loads(text)
    assert "Sarathi-optimized" not in text
    assert config["embedding"] == {"enabled": True}
    assert config["pipeline"]["default_ttl_hours"] == 168


def test_ncp_overrides_skip_invalid_toml(tmp_path: Path, capsys):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[pipeline\n")

    assert _apply_ncp_config_overrides(config_path) == []
    assert config_path.read_text() == "[pipeline\n"
    assert "not valid TOML" in capsys.readouterr().out


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
