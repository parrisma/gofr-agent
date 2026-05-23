#!/usr/bin/env bash
# =============================================================================
# Build all gofr-agent Docker images used for local development.
#
# Usage:
#   docker/build-all.sh [TAG]
#
#   TAG defaults to "latest" and is forwarded to the fixture and CLI image
#   builders. The development image continues to build as gofr-agent-dev:latest.
#
# Examples:
#   docker/build-all.sh
#   docker/build-all.sh v1.2.3
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${1:-latest}"

echo "================================================================="
echo "Building all gofr-agent Docker images"
echo "Tag for CLI/fixtures: ${TAG}"
echo "================================================================="

"${SCRIPT_DIR}/build-dev.sh"
"${SCRIPT_DIR}/build-fixtures.sh" "${TAG}"
"${SCRIPT_DIR}/build-cli.sh" "${TAG}"

echo ""
echo "All image builds completed successfully."
