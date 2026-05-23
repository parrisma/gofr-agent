#!/usr/bin/env bash
# =============================================================================
# Build the gofr-agent CLI Docker image.
#
# Usage:
#   docker/build-cli.sh [TAG]
#
#   TAG defaults to "latest".
#
# Examples:
#   docker/build-cli.sh
#   docker/build-cli.sh v1.2.3
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TAG="${1:-${GOFR_AGENT_CLI_IMAGE_TAG:-latest}}"
IMAGE_NAME="${GOFR_AGENT_CLI_IMAGE_NAME:-gofr-agent-cli}"
IMAGE="${IMAGE_NAME}:${TAG}"

cd "${PROJECT_ROOT}"

echo "================================================================="
echo "Building image: ${IMAGE}"
echo "Context:        ${PROJECT_ROOT}"
echo "Dockerfile:     docker/Dockerfile.cli"
echo "================================================================="

docker build \
    --file docker/Dockerfile.cli \
    --tag "${IMAGE}" \
    .

echo ""
echo "Build complete: ${IMAGE}"
