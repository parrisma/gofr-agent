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

TAG="${1:-latest}"
IMAGE="gofr-agent-fixtures:${TAG}"

# Must be run from the project root so Docker can resolve all COPY paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
echo "  docker stack deploy -c docker/compose.fixtures.yml gofr-fixtures"
echo ""
echo "Remove stack:"
echo "  docker stack rm gofr-fixtures"
