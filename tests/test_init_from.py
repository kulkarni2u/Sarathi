"""Tests for sarathi init --from feature."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _repo_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_pythonpath
        else str(PROJECT_ROOT) + os.pathsep + existing_pythonpath
    )
    return env


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd or PROJECT_ROOT),
        env=_repo_env(),
    )


def _make_source_pack(tmp_path: Path, name: str = "source", files: list[str] | None = None) -> Path:
    """Helper to create a minimal policy-pack source directory."""
    if files is None:
        files = ["complexity.md", "commands.md"]
    source_pack = tmp_path / name
    source_pack.mkdir()
    for f in files:
        (source_pack / f).write_text(f"# {f}\n\ntest content")
    return source_pack


def test_init_from_local_directory(tmp_path: Path):
    """Test importing from a local directory containing policy files."""
    # Create a source pack with minimal files
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")
    (source_pack / "commands.md").write_text("# Commands\n\ntest")

    # Create target directory
    target = tmp_path / "target"
    target.mkdir()

    # Run init with --from
    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()
    # Should have filled in missing files with defaults
    assert (target / "policy-pack" / "review.md").exists()
    assert (target / "policy-pack" / "escalation.md").exists()


def test_init_from_recipe_bakeoff(tmp_path: Path):
    """Test importing from a shipped recipe by name."""
    target = tmp_path / "target"
    target.mkdir()

    # Run init with --from bakeoff (the shipped recipe)
    result = _run_cli("init", str(target), "--from", "bakeoff")

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Bakeoff recipe files should be copied
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()
    assert (target / "policy-pack" / "workflow-patterns.md").exists()


def test_init_from_with_agents_subdir(tmp_path: Path):
    """Test that agents/ subdirectory is copied."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")
    agents_dir = source_pack / "agents"
    agents_dir.mkdir()
    (agents_dir / "custom.md").write_text("# Custom Agent\n\ntest")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    assert (target / "policy-pack" / "agents" / "custom.md").exists()


def test_init_from_refuses_overwrite_without_force(tmp_path: Path):
    """Test that --from refuses to overwrite without --force."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")

    target = tmp_path / "target"
    target.mkdir()
    pack = target / "policy-pack"
    pack.mkdir()
    (pack / "existing.md").write_text("# Existing\n\nkeep me")

    # Try without --force
    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 1
    assert "Error" in result.stdout or "Error" in result.stderr
    # Existing file should remain
    assert (pack / "existing.md").exists()
    assert (pack / "existing.md").read_text() == "# Existing\n\nkeep me"


def test_init_from_with_force_overwrites(tmp_path: Path):
    """Test that --force overwrites existing pack."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity from source\n\ntest")

    target = tmp_path / "target"
    target.mkdir()
    pack = target / "policy-pack"
    pack.mkdir()
    (pack / "complexity.md").write_text("# Complexity from target\n\nold")

    # Run with --force
    result = _run_cli("init", str(target), "--from", str(source_pack), "--force")

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # File should be overwritten
    assert (pack / "complexity.md").read_text() == "# Complexity from source\n\ntest"


def test_init_from_git_url_file(tmp_path: Path):
    """Test importing from a git URL using file:// for local testing."""
    # Create a git repo with a policy pack
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Initialize as git repo
    subprocess.run(
        ["git", "init"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )

    # Add policy files
    pack_dir = repo_dir / "policy-pack"
    pack_dir.mkdir()
    (pack_dir / "complexity.md").write_text("# Complexity\n\nfrom git")
    (pack_dir / "commands.md").write_text("# Commands\n\nfrom git")

    # Commit
    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )

    # Create target
    target = tmp_path / "target"
    target.mkdir()

    # Use file:// URL to reference the local repo
    git_url = f"file://{repo_dir}"

    result = _run_cli("init", str(target), "--from", git_url)

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Files should be imported from the git repo
    assert (target / "policy-pack" / "complexity.md").exists()
    content = (target / "policy-pack" / "complexity.md").read_text()
    assert "from git" in content


def test_init_from_invalid_source(tmp_path: Path):
    """Test that invalid source gives clear error."""
    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", "/nonexistent/path/to/pack")

    assert result.returncode == 1
    assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


def test_init_from_fills_missing_standard_files(tmp_path: Path):
    """Test that missing standard files are filled with generated defaults."""
    # Create minimal source pack
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\nminimal pack")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    # All standard files should exist
    required_files = [
        "complexity.md",
        "commands.md",
        "review.md",
        "escalation.md",
        "model-routing.md",
        "permissions.md",
        "notifications.md",
    ]
    for fname in required_files:
        fpath = target / "policy-pack" / fname
        assert fpath.exists(), f"Missing {fname}"
        assert fpath.stat().st_size > 0, f"{fname} is empty"


def test_init_from_validates_after_import(tmp_path: Path):
    """Test that validation runs after import."""
    source_pack = tmp_path / "source"
    source_pack.mkdir()
    (source_pack / "complexity.md").write_text("# Complexity\n\ntest")

    target = tmp_path / "target"
    target.mkdir()

    result = _run_cli("init", str(target), "--from", str(source_pack))

    assert result.returncode == 0
    # Output should include validation results
    output = result.stdout + result.stderr
    assert "Validate" in output or "validate" in output or "PASS" in output


# ── Registry tests ──────────────────────────────────────────────────────────


def test_init_from_registry_resolves_named_entry(tmp_path: Path):
    """Test that registry:<name> resolves to a valid source."""
    target = tmp_path / "target"
    target.mkdir()
    result = _run_cli("init", str(target), "--from", "registry:bakeoff")
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "workflow-patterns.md").exists()


def test_init_from_registry_versioned_entry(tmp_path: Path):
    """Test that <name>@<version> resolves through the registry."""
    source_pack = _make_source_pack(tmp_path, "versioned-source")
    (source_pack / "complexity.md").write_text("# Complexity\n\nfrom versioned entry")
    manifest = {
        "registries": {
            "test": {
                "entries": {
                    "versioned-pack": {
                        "source": str(source_pack),
                        "version": "v1",
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "reg-versioned.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    target = tmp_path / "target"
    target.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "versioned-pack@v1"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert "from versioned entry" in (target / "policy-pack" / "complexity.md").read_text()


def test_init_from_registry_unknown_entry(tmp_path: Path):
    """Test that an unknown registry entry gives a clear error."""
    target = tmp_path / "target"
    target.mkdir()
    result = _run_cli("init", str(target), "--from", "registry:nonexistent-pack")
    assert result.returncode == 1
    output = (result.stdout + result.stderr).lower()
    assert "not found" in output or "unknown" in output or "registry" in output


def test_init_from_registry_unknown_name_at_version(tmp_path: Path):
    """Test that an unknown <name>@<version> gives a clear error."""
    target = tmp_path / "target"
    target.mkdir()
    result = _run_cli("init", str(target), "--from", "completely-unknown-pack@v1")
    assert result.returncode == 1
    output = (result.stdout + result.stderr).lower()
    assert "not found" in output or "unknown" in output


def test_init_from_registry_external_manifest(tmp_path: Path):
    """Test loading a custom registry manifest from a JSON file."""
    # Create a custom source pack
    source_pack = _make_source_pack(tmp_path, "custom-source")
    # Create external registry manifest
    manifest = {
        "registries": {
            "custom": {
                "description": "Custom test registry",
                "entries": {
                    "my-custom-pack": {
                        "description": "A custom pack",
                        "source": str(source_pack),
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "registry-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    target = tmp_path / "target-ext"
    target.mkdir()
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:my-custom-pack"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()


def test_init_from_local_dir_still_works(tmp_path: Path):
    """Existing local directory import still works after registry addition."""
    source_pack = _make_source_pack(tmp_path, "src-pack")
    target = tmp_path / "target-local"
    target.mkdir()
    result = _run_cli("init", str(target), "--from", str(source_pack))
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
    assert (target / "policy-pack" / "commands.md").exists()


def test_init_from_recipe_name_still_works(tmp_path: Path):
    """Existing bare recipe name lookup still works after registry addition."""
    target = tmp_path / "target-recipe"
    target.mkdir()
    result = _run_cli("init", str(target), "--from", "bakeoff")
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()


def test_init_from_registry_external_manifest_versions(tmp_path: Path):
    """Test external manifest with versioned entries (versions dict + default source)."""
    source_latest = _make_source_pack(tmp_path, "my-pack-latest")
    (source_latest / "complexity.md").write_text("# Complexity\n\nlatest version")
    source_v1 = _make_source_pack(tmp_path, "my-pack-v1")
    (source_v1 / "complexity.md").write_text("# Complexity\n\nv1 content")
    source_v2 = _make_source_pack(tmp_path, "my-pack-v2")
    (source_v2 / "complexity.md").write_text("# Complexity\n\nv2 content")

    manifest = {
        "registries": {
            "test": {
                "description": "Versioned test registry",
                "entries": {
                    "my-pack": {
                        "description": "A versioned pack",
                        "source": str(source_latest),
                        "versions": {
                            "v1": {"source": str(source_v1)},
                            "v2": {"source": str(source_v2)},
                        },
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "registry-versions.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    # registry:my-pack resolves to default (latest) source
    t1 = tmp_path / "t-default"
    t1.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(t1), "--from", "registry:my-pack"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "latest version" in (t1 / "policy-pack" / "complexity.md").read_text()

    # my-pack@v2 resolves to v2 source
    t2 = tmp_path / "t-v2"
    t2.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(t2), "--from", "my-pack@v2"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "v2 content" in (t2 / "policy-pack" / "complexity.md").read_text()

    # my-pack@v1 resolves to v1 source
    t3 = tmp_path / "t-v1"
    t3.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(t3), "--from", "my-pack@v1"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "v1 content" in (t3 / "policy-pack" / "complexity.md").read_text()


def test_init_from_registry_missing_version_error(tmp_path: Path):
    """Known pack with missing version fails with a clear error."""
    source_pack = _make_source_pack(tmp_path, "my-pack")
    manifest = {
        "registries": {
            "test": {
                "entries": {
                    "my-pack": {
                        "source": str(source_pack),
                        "versions": {
                            "v1": {"source": str(source_pack)},
                            "v2": {"source": str(source_pack)},
                        },
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "registry-missing-version.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    target = tmp_path / "t-missing"
    target.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "my-pack@v3"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 1
    output = (r.stdout + r.stderr).lower()
    assert "v3" in output and "not found" in output


def test_init_from_registry_versions_only_no_default(tmp_path: Path):
    """Registry entry with only versions dict, no default source."""
    source_v1 = _make_source_pack(tmp_path, "ver-only-v1")
    (source_v1 / "complexity.md").write_text("# Complexity\n\nv1 only")
    source_v2 = _make_source_pack(tmp_path, "ver-only-v2")
    (source_v2 / "complexity.md").write_text("# Complexity\n\nv2 only")

    manifest = {
        "registries": {
            "test": {
                "entries": {
                    "ver-only": {
                        "versions": {
                            "v1": {"source": str(source_v1)},
                            "v2": {"source": str(source_v2)},
                        },
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "registry-versions-only.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    # registry:ver-only falls back to first version (v1) since no default
    t1 = tmp_path / "t-ver-default"
    t1.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(t1), "--from", "registry:ver-only"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "v1 only" in (t1 / "policy-pack" / "complexity.md").read_text()

    # ver-only@v2 resolves to v2
    t2 = tmp_path / "t-ver-v2"
    t2.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(t2), "--from", "ver-only@v2"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "v2 only" in (t2 / "policy-pack" / "complexity.md").read_text()


def test_init_from_registry_with_force(tmp_path: Path):
    """Registry import respects --force like other imports."""
    source_pack = _make_source_pack(tmp_path, "force-source")
    manifest = {
        "registries": {
            "test": {
                "entries": {
                    "force-pack": {
                        "source": str(source_pack),
                    },
                },
            }
        }
    }
    manifest_path = tmp_path / "registry-force.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    target = tmp_path / "target-force"
    target.mkdir()
    pack = target / "policy-pack"
    pack.mkdir()
    (pack / "complexity.md").write_text("# Original\noriginal")

    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)
    # Without --force
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:force-pack"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert result.returncode == 1
    assert (pack / "complexity.md").read_text() == "# Original\noriginal"

    # With --force
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:force-pack", "--force"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (pack / "complexity.md").read_text() == "# complexity.md\n\ntest content"


# ── Registry error-handling tests ────────────────────────────────────────────


def test_init_from_registry_missing_manifest_file(tmp_path: Path):
    """SARATHI_REGISTRY pointing at a missing file returns clear error, no traceback."""
    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(tmp_path / "no-such-file.json")

    target = tmp_path / "t-missing-file"
    target.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:bakeoff"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "Traceback" not in combined, "Registry file-not-found must not produce a traceback"
    lower = combined.lower()
    assert "error" in lower
    assert any(w in lower for w in ("no such file", "not found", "missing", "exist"))


def test_init_from_registry_malformed_json(tmp_path: Path):
    """SARATHI_REGISTRY pointing at malformed JSON returns clear error, no traceback."""
    manifest_path = tmp_path / "bad.json"
    manifest_path.write_text("{invalid json!!!}")

    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    target = tmp_path / "t-bad-json"
    target.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:bakeoff"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "Traceback" not in combined, "Registry malformed JSON must not produce a traceback"
    lower = combined.lower()
    assert "error" in lower
    assert any(w in lower for w in ("json", "parse", "decode", "invalid"))


def test_init_from_registry_invalid_manifest_shape(tmp_path: Path):
    """SARATHI_REGISTRY with entries as non-dict returns clear error, no traceback.

    When entry_body is not a dict (e.g. a string), the manifest parser
    must not crash with AttributeError.
    """
    manifest = {
        "registries": {
            "test": {
                "entries": {
                    "bad-pack": "not-a-dict",
                },
            },
        },
    }
    manifest_path = tmp_path / "bad-shape.json"
    manifest_path.write_text(json.dumps(manifest))

    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(manifest_path)

    target = tmp_path / "t-bad-shape"
    target.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "registry:bakeoff"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "Traceback" not in combined, "Registry invalid shape must not produce a traceback"
    lower = combined.lower()
    assert "error" in lower
    assert any(w in lower for w in ("invalid", "shape", "entry", "manifest", "format"))


# ── Non-registry behaviour unchanged ─────────────────────────────────────────


def test_init_from_local_directory_still_works_with_bad_registry(tmp_path: Path):
    """Local directory import must not be affected by a bad SARATHI_REGISTRY."""
    source_pack = _make_source_pack(tmp_path, "src-pack")
    target = tmp_path / "t-bad-reg"
    target.mkdir()

    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(tmp_path / "nonexistent.json")

    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", str(source_pack)],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()


def test_init_from_recipe_name_still_works_with_bad_registry(tmp_path: Path):
    """Recipe name import must not be affected by a bad SARATHI_REGISTRY."""
    target = tmp_path / "t-bad-reg-recipe"
    target.mkdir()

    env = _repo_env()
    env["SARATHI_REGISTRY"] = str(tmp_path / "nonexistent.json")

    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "init", str(target), "--from", "bakeoff"],
        check=False, capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert (target / "policy-pack" / "complexity.md").exists()
