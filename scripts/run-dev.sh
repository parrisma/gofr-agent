#!/bin/bash
# Description: Forward to the main development-container launcher for backward-compatible local usage.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-dev-container.sh" "$@"
