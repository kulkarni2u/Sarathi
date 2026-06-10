"""Cheap, non-API test for provider_cli_versions().

Unlike tests/live/, this runs in the default suite (no env var gate) since
it only invokes `<cli> --version` against whatever CLIs happen to be
installed, and tolerates all of them being missing.
"""
from __future__ import annotations

from src.runtime import provider_cli_versions
from src.runtime.preflight import _PROVIDER_VERSION_CLIS


def test_provider_cli_versions_returns_dict_for_known_providers():
    versions = provider_cli_versions()

    assert isinstance(versions, dict)
    assert set(versions.keys()) == set(_PROVIDER_VERSION_CLIS.keys())
    for provider, version in versions.items():
        assert version is None or isinstance(version, str)


def test_provider_cli_versions_tolerates_missing_cli(monkeypatch):
    monkeypatch.setattr("src.runtime.preflight.shutil.which", lambda _name: None)

    versions = provider_cli_versions()

    assert all(version is None for version in versions.values())


def test_provider_cli_versions_never_raises_on_subprocess_error(monkeypatch):
    import subprocess

    monkeypatch.setattr("src.runtime.preflight.shutil.which", lambda _name: f"/usr/bin/{_name}")

    def _boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=10)

    monkeypatch.setattr("src.runtime.preflight.subprocess.run", _boom)

    versions = provider_cli_versions()

    assert all(version is None for version in versions.values())
