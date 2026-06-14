"""Tests for src.service.static_files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.service.static_files import (
    StaticFileResult,
    content_type_for,
    resolve_static_file,
)


@pytest.fixture()
def dist_root(tmp_path: Path) -> Path:
    """Build a fake web/dist tree with index.html and assets/app.js."""

    (tmp_path / "index.html").write_text("<html>index</html>", encoding="utf-8")

    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('app');", encoding="utf-8")
    (assets / "app.css").write_text("body { color: red; }", encoding="utf-8")

    # A file outside of dist_root, used for symlink-escape tests.
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("top secret", encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# content_type_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("index.html", "text/html; charset=utf-8"),
        ("assets/app.js", "text/javascript; charset=utf-8"),
        ("assets/app.mjs", "text/javascript; charset=utf-8"),
        ("assets/app.css", "text/css; charset=utf-8"),
        ("data.json", "application/json"),
        ("icon.svg", "image/svg+xml"),
        ("logo.png", "image/png"),
        ("photo.jpg", "image/jpeg"),
        ("photo.jpeg", "image/jpeg"),
        ("favicon.ico", "image/x-icon"),
        ("font.woff2", "font/woff2"),
        ("app.js.map", "application/json"),
        ("notes.txt", "text/plain; charset=utf-8"),
        ("unknownfile.xyz", "application/octet-stream"),
        ("no_extension", "application/octet-stream"),
    ],
)
def test_content_type_for(path: str, expected: str) -> None:
    assert content_type_for(path) == expected


# ---------------------------------------------------------------------------
# Existing files
# ---------------------------------------------------------------------------


def test_resolve_root_serves_index(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/")

    assert isinstance(result, StaticFileResult)
    assert result.status == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.body == b"<html>index</html>"


def test_resolve_index_html_explicit(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/index.html")

    assert result is not None
    assert result.status == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.body == b"<html>index</html>"


def test_resolve_existing_asset(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/assets/app.js")

    assert result is not None
    assert result.status == 200
    assert result.content_type == "text/javascript; charset=utf-8"
    assert result.body == b"console.log('app');"


def test_resolve_existing_css_asset(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/assets/app.css")

    assert result is not None
    assert result.status == 200
    assert result.content_type == "text/css; charset=utf-8"
    assert result.body == b"body { color: red; }"


# ---------------------------------------------------------------------------
# SPA history fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url_path", ["/usage", "/task/123", "/some/deep/route"])
def test_spa_route_falls_back_to_index(dist_root: Path, url_path: str) -> None:
    result = resolve_static_file(dist_root, url_path)

    assert result is not None
    assert result.status == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.body == b"<html>index</html>"


# ---------------------------------------------------------------------------
# Missing assets that look like files -> None (caller 404s)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_path",
    [
        "/assets/missing.js",
        "/missing.css",
        "/assets/app.js.bak.png",
        "/favicon.ico",
    ],
)
def test_missing_asset_with_extension_returns_none(dist_root: Path, url_path: str) -> None:
    assert resolve_static_file(dist_root, url_path) is None


# ---------------------------------------------------------------------------
# Path traversal protections
# ---------------------------------------------------------------------------


def test_traversal_dotdot_blocked(dist_root: Path) -> None:
    assert resolve_static_file(dist_root, "/../outside_secret.txt") is None


def test_traversal_deep_dotdot_blocked(dist_root: Path) -> None:
    assert resolve_static_file(dist_root, "/assets/../../outside_secret.txt") is None


def test_traversal_encoded_dotdot_blocked(dist_root: Path) -> None:
    # "%2e%2e%2f" decodes to "../"
    assert resolve_static_file(dist_root, "/%2e%2e/outside_secret.txt") is None


def test_traversal_encoded_dotdot_slash_variant_blocked(dist_root: Path) -> None:
    assert resolve_static_file(dist_root, "/assets/%2e%2e%2f%2e%2e/outside_secret.txt") is None


def test_absolute_path_outside_root_blocked(dist_root: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_secret.txt"
    # An absolute filesystem path used as the url_path must not escape dist_root.
    assert resolve_static_file(dist_root, str(outside)) is None


def test_absolute_etc_passwd_treated_as_relative_spa_route(dist_root: Path) -> None:
    # "/etc/passwd" has no file extension and is normalized to a path
    # relative to dist_root (it cannot escape to the real filesystem root),
    # so it is treated like any other unknown SPA route and falls back to
    # index.html rather than ever touching the real /etc/passwd.
    result = resolve_static_file(dist_root, "/etc/passwd")

    assert result is not None
    assert result.status == 200
    assert result.body == b"<html>index</html>"


def test_absolute_path_with_extension_outside_root_returns_none(dist_root: Path) -> None:
    # Even though "/etc/shadow.conf" is normalized to be relative to
    # dist_root, since it looks like a file (has an extension) and doesn't
    # exist under dist_root, the caller should 404 rather than fall back.
    assert resolve_static_file(dist_root, "/etc/shadow.conf") is None


def test_symlink_escape_blocked(dist_root: Path, tmp_path: Path) -> None:
    target = tmp_path.parent / "outside_secret.txt"
    link = dist_root / "escape.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    assert resolve_static_file(dist_root, "/escape.txt") is None


def test_symlink_dir_escape_blocked(dist_root: Path, tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.js").write_text("secret", encoding="utf-8")

    link = dist_root / "escape_dir"
    try:
        os.symlink(outside_dir, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    assert resolve_static_file(dist_root, "/escape_dir/secret.js") is None


# ---------------------------------------------------------------------------
# Misc edge cases
# ---------------------------------------------------------------------------


def test_missing_dist_root_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert resolve_static_file(missing, "/") is None


def test_query_string_and_fragment_stripped(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/assets/app.js?v=123")

    assert result is not None
    assert result.body == b"console.log('app');"


def test_directory_path_without_trailing_file_falls_back_to_index(dist_root: Path) -> None:
    result = resolve_static_file(dist_root, "/assets")

    # "/assets" is an existing directory (no extension) - SPA fallback.
    assert result is not None
    assert result.status == 200
    assert result.body == b"<html>index</html>"
