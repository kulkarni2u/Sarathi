"""Pure helpers for serving the built web bundle (``web/dist``).

This module contains no I/O side-effects beyond reading files from disk and
performs no networking. It is meant to be used by an HTTP layer (eg.
``src/service/http.py``) which is responsible for translating the result of
:func:`resolve_static_file` into an actual HTTP response.

Public API
----------

``content_type_for(path) -> str``
    Map a file path (by extension) to a MIME type. Unknown extensions map to
    ``application/octet-stream``.

``resolve_static_file(dist_root, url_path) -> StaticFileResult | None``
    Safely resolve a request path under ``dist_root`` and return a
    :class:`StaticFileResult` describing the response, or ``None`` if the
    request should be treated as a 404 by the caller (eg. the path looks like
    a missing static asset, or the request attempted path traversal /
    escaped ``dist_root``).

``StaticFileResult``
    A small dataclass with three fields: ``status`` (int), ``content_type``
    (str), and ``body`` (bytes).

Path-traversal safety
----------------------

``resolve_static_file`` resolves the requested path against ``dist_root``
using :meth:`pathlib.Path.resolve` (which also resolves symlinks) and then
verifies that the resolved path is equal to, or a descendant of, the resolved
``dist_root``. Any request whose resolved path escapes ``dist_root`` -
whether via ``..`` segments, an absolute path, percent-encoded traversal
sequences, or a symlink that points outside the tree - is rejected and
``None`` is returned, so the caller can respond with a 404 (or 403) without
ever touching a file outside the dist directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

__all__ = ["StaticFileResult", "content_type_for", "resolve_static_file"]


_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

_DEFAULT_CONTENT_TYPE = "application/octet-stream"

_INDEX_FILE = "index.html"


@dataclass(frozen=True)
class StaticFileResult:
    """Result of resolving a static file request.

    Attributes:
        status: HTTP status code to send (eg. ``200``).
        content_type: Value for the ``Content-Type`` header.
        body: Raw response body bytes.
    """

    status: int
    content_type: str
    body: bytes


def content_type_for(path: str | Path) -> str:
    """Return the MIME type for ``path`` based on its file extension.

    Unknown or missing extensions return ``application/octet-stream``.
    """

    suffix = Path(path).suffix.lower()
    return _CONTENT_TYPES.get(suffix, _DEFAULT_CONTENT_TYPE)


def _is_within(root: Path, candidate: Path) -> bool:
    """Return True if ``candidate`` is ``root`` or a descendant of it."""

    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_static_file(dist_root: str | Path, url_path: str) -> StaticFileResult | None:
    """Resolve ``url_path`` to a static file under ``dist_root``.

    Returns a :class:`StaticFileResult` with ``status == 200`` for:

    - An existing file directly matching the request path.
    - A request path that has no file extension and does not exist as a
      file (a client-side/SPA route such as ``/usage`` or ``/task/123``),
      which falls back to serving ``index.html`` (history-mode fallback).

    Returns ``None`` when:

    - The request attempts path traversal, uses an absolute path, or
      otherwise resolves outside of ``dist_root`` (including via symlink
      escapes).
    - The request path looks like a file (has an extension) but no such
      file exists - the caller should respond with a 404.
    - ``dist_root`` does not exist, or ``index.html`` is missing for an
      SPA-fallback request.
    """

    root = Path(dist_root).resolve()
    if not root.is_dir():
        return None

    # Decode percent-encoding (eg. "%2e%2e" -> "..") before splitting, so
    # encoded traversal attempts are caught the same way as literal ones.
    decoded = unquote(url_path)

    # Drop query string / fragment if present.
    for sep in ("?", "#"):
        idx = decoded.find(sep)
        if idx != -1:
            decoded = decoded[:idx]

    # Normalize to a relative path: strip leading slashes so an absolute
    # path like "/etc/passwd" or "//etc/passwd" is treated as relative to
    # dist_root rather than the filesystem root.
    relative = decoded.lstrip("/")

    if relative == "":
        target = root / _INDEX_FILE
    else:
        # Reject any path containing a ".." segment outright. The
        # resolve()+containment check below also guards against escapes,
        # but this gives an explicit, early rejection for traversal
        # attempts.
        parts = Path(relative).parts
        if ".." in parts:
            return None

        target = root / relative

    try:
        resolved = target.resolve()
    except OSError:
        return None

    if not _is_within(root, resolved):
        return None

    if resolved.is_file():
        return StaticFileResult(
            status=200,
            content_type=content_type_for(resolved),
            body=resolved.read_bytes(),
        )

    # Not an existing file. Decide between SPA fallback and 404.
    if resolved.suffix:
        # Looks like a static asset request (has a file extension) but the
        # file doesn't exist -> let the caller 404.
        return None

    index_path = root / _INDEX_FILE
    try:
        index_resolved = index_path.resolve()
    except OSError:
        return None

    if not _is_within(root, index_resolved) or not index_resolved.is_file():
        return None

    return StaticFileResult(
        status=200,
        content_type=content_type_for(index_resolved),
        body=index_resolved.read_bytes(),
    )
