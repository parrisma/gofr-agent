#!/usr/bin/env bash
# =============================================================================
# Build the gofr-agent test MCP fixture services Docker image.
#
# Usage:
#   docker/build-fixtures.sh [TAG]
#
#   TAG defaults to "latest".
#
# Examples:
#   docker/build-fixtures.sh
#   docker/build-fixtures.sh v1.2.3
# =============================================================================
set -euo pipefail

# Must be run from the project root so Docker can resolve all COPY paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORTS_ENV="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"

if [[ -f "${PORTS_ENV}" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "${PORTS_ENV}"
    set +a
fi

TAG="${1:-${GOFR_FIXTURE_IMAGE_TAG:-latest}}"
IMAGE_NAME="${GOFR_FIXTURE_IMAGE_NAME:-gofr-agent-mcp-fixtures}"
IMAGE="${IMAGE_NAME}:${TAG}"

cd "${PROJECT_ROOT}"

echo "================================================================="
echo "Building image: ${IMAGE}"
echo "Context:        ${PROJECT_ROOT}"
echo "Dockerfile:     docker/Dockerfile.fixtures"
echo "================================================================="

docker build \
    --file docker/Dockerfile.fixtures \
    --tag  "${IMAGE}" \
    .

echo ""
echo "Build complete: ${IMAGE}"
echo ""
echo "Start the Compose dev stack dependencies:"
echo "  docker compose -f docker/compose.dev.yml up -d --build valkey mcp-instruments mcp-clients mcp-trades mcp-analytics"
echo ""
echo "Stop the Compose dev stack dependencies:"
echo "  docker compose -f docker/compose.dev.yml stop valkey mcp-instruments mcp-clients mcp-trades mcp-analytics"
