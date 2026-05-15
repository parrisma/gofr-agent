#!/bin/bash
# Compatibility shim: the canonical dev container entrypoint is now scripts/run-dev-container.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec bash "$PROJECT_ROOT/scripts/run-dev-container.sh" "$@"
