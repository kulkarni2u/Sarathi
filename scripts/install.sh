#!/usr/bin/env bash
#
# Sarathi one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/kulkarni2u/Sarathi/main/scripts/install.sh | bash
#
# Or from a local checkout:
#   bash scripts/install.sh
#
# Environment overrides:
#   SARATHI_HOME           Install prefix (default: $HOME/.sarathi). A venv is
#                          created at $SARATHI_HOME/venv.
#   SARATHI_INSTALL_SPEC   pip install spec to use instead of the auto-detected
#                          one (e.g. a specific git ref or a local path).
#   SARATHI_DRY_RUN=1      Print the plan and exit 0 without touching anything.
#
# Flags:
#   --dry-run              Same as SARATHI_DRY_RUN=1.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GIT_SPEC_DEFAULT="git+https://github.com/kulkarni2u/Sarathi.git"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
info()  { printf '==> %s\n' "$*"; }
warn()  { printf 'WARNING: %s\n' "$*" >&2; }
die()   { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument / environment parsing
# ---------------------------------------------------------------------------
DRY_RUN="${SARATHI_DRY_RUN:-0}"
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die "Unknown argument: $arg" ;;
    esac
done

SARATHI_HOME="${SARATHI_HOME:-$HOME/.sarathi}"
VENV_DIR="$SARATHI_HOME/venv"

# ---------------------------------------------------------------------------
# Resolve the script's repo root (so we can detect a local checkout)
# ---------------------------------------------------------------------------
# When piped via `curl | bash`, $0 is "bash" and there is no script file on
# disk; that is fine, we just fall back to the git install spec.
resolve_repo_root() {
    local src dir
    src="${BASH_SOURCE[0]:-}"
    [ -n "$src" ] || return 1
    [ -f "$src" ] || return 1
    dir="$(cd "$(dirname "$src")" >/dev/null 2>&1 && pwd)" || return 1
    # script lives at <repo>/scripts/install.sh -> repo root is one level up
    printf '%s\n' "$(cd "$dir/.." >/dev/null 2>&1 && pwd)"
}

# ---------------------------------------------------------------------------
# Detect a Python >= 3.10 interpreter
# ---------------------------------------------------------------------------
py_is_recent_enough() {
    # $1 = interpreter path/name. Returns 0 if version >= MIN.
    local interp="$1"
    "$interp" - "$MIN_PY_MAJOR" "$MIN_PY_MINOR" <<'PYEOF' >/dev/null 2>&1
import sys
need_major, need_minor = int(sys.argv[1]), int(sys.argv[2])
sys.exit(0 if sys.version_info[:2] >= (need_major, need_minor) else 1)
PYEOF
}

detect_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if py_is_recent_enough "$candidate"; then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(detect_python || true)"
if [ -z "$PYTHON" ]; then
    die "No Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR} found. Tried 'python3' and 'python'. Install Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ and retry."
fi
PY_VERSION="$("$PYTHON" --version 2>&1 || true)"

# ---------------------------------------------------------------------------
# Decide the install spec
# ---------------------------------------------------------------------------
REPO_ROOT="$(resolve_repo_root || true)"
INSTALL_SPEC=""
INSTALL_SOURCE=""

if [ -n "${SARATHI_INSTALL_SPEC:-}" ]; then
    INSTALL_SPEC="$SARATHI_INSTALL_SPEC"
    INSTALL_SOURCE="SARATHI_INSTALL_SPEC override"
elif [ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/pyproject.toml" ] \
        && grep -Eq '^[[:space:]]*name[[:space:]]*=[[:space:]]*"sarathi"' "$REPO_ROOT/pyproject.toml"; then
    INSTALL_SPEC="$REPO_ROOT"
    INSTALL_SOURCE="local checkout"
else
    INSTALL_SPEC="$GIT_SPEC_DEFAULT"
    INSTALL_SOURCE="git"
fi

# ---------------------------------------------------------------------------
# Dry run: print the plan and exit without side effects
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
    info "Sarathi installer (dry run) -- no changes will be made"
    printf '    python       : %s (%s)\n' "$PYTHON" "$PY_VERSION"
    printf '    install home : %s\n' "$SARATHI_HOME"
    printf '    venv         : %s\n' "$VENV_DIR"
    printf '    install spec : %s\n' "$INSTALL_SPEC"
    printf '    spec source  : %s\n' "$INSTALL_SOURCE"
    info "Dry run complete. Re-run without --dry-run / SARATHI_DRY_RUN to install."
    exit 0
fi

# ---------------------------------------------------------------------------
# Real install
# ---------------------------------------------------------------------------
info "Using Python: $PYTHON ($PY_VERSION)"
info "Install home : $SARATHI_HOME"
info "Install spec : $INSTALL_SPEC ($INSTALL_SOURCE)"

mkdir -p "$SARATHI_HOME"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    info "Creating virtual environment at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR" \
        || die "Failed to create venv. Ensure the 'venv' module is available (e.g. install python3-venv)."
else
    info "Reusing existing virtual environment at $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || die "venv python not found at $VENV_PY"

info "Upgrading pip"
"$VENV_PY" -m pip install --quiet --upgrade pip \
    || die "Failed to upgrade pip inside the venv."

info "Installing Sarathi (this may take a moment)"
"$VENV_PY" -m pip install --upgrade "$INSTALL_SPEC" \
    || die "pip install failed for spec: $INSTALL_SPEC"

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
SARATHI_BIN="$VENV_DIR/bin/sarathi"
DESKTOP_BIN="$VENV_DIR/bin/sarathi-desktop"

smoke_failed=0
for bin in "$SARATHI_BIN" "$DESKTOP_BIN"; do
    if [ ! -x "$bin" ]; then
        warn "Expected executable not found: $bin"
        smoke_failed=1
        continue
    fi
    if "$bin" --help >/dev/null 2>&1; then
        info "Smoke test passed: $(basename "$bin") --help"
    else
        warn "Smoke test FAILED: $(basename "$bin") --help returned non-zero"
        smoke_failed=1
    fi
done

if [ "$smoke_failed" -ne 0 ]; then
    die "Installation completed but smoke tests failed. See warnings above."
fi

# ---------------------------------------------------------------------------
# Next-step guidance
# ---------------------------------------------------------------------------
info "Sarathi installed successfully."

LOCAL_BIN="$HOME/.local/bin"
linked=0
case ":${PATH}:" in
    *":$LOCAL_BIN:"*)
        if [ -d "$LOCAL_BIN" ]; then
            if ln -sf "$SARATHI_BIN" "$LOCAL_BIN/sarathi" \
               && ln -sf "$DESKTOP_BIN" "$LOCAL_BIN/sarathi-desktop"; then
                info "Symlinked 'sarathi' and 'sarathi-desktop' into $LOCAL_BIN (already on PATH)."
                linked=1
            fi
        fi
        ;;
esac

printf '\n'
if [ "$linked" -eq 1 ]; then
    info "You can now run:  sarathi --help"
else
    info "Add the venv bin directory to your PATH, e.g.:"
    printf '    export PATH="%s/bin:$PATH"\n' "$VENV_DIR"
    info "Then reload your shell, or call the binary directly:"
    printf '    %s --help\n' "$SARATHI_BIN"
fi

printf '\n'
info "Launch the desktop cockpit with:"
if [ "$linked" -eq 1 ]; then
    printf '    sarathi-desktop\n'
else
    printf '    %s\n' "$DESKTOP_BIN"
fi
