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
echo "Deploy to Swarm:"
echo "  docker/fixtures-stack.sh start"
echo ""
echo "Remove stack:"
echo "  docker/fixtures-stack.sh stop"
