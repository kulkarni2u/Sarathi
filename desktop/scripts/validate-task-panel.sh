#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export BASE_URL="${BASE_URL:-http://127.0.0.1:5173}"
export SARATHI_REPO_ROOT="${SARATHI_REPO_ROOT:-${REPO_ROOT}}"
export CLEANUP_DB_PATH="${CLEANUP_DB_PATH:-true}"

node "${SCRIPT_DIR}/validate-task-panel.mjs"
