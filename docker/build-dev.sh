#!/bin/bash
# Build GOFR-AGENT development image
# Requires gofr-base:latest to be built first

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Get user's UID/GID for permission matching
USER_UID=$(id -u)
USER_GID=$(id -g)

echo "======================================================================="
echo "Building GOFR-AGENT Development Image"
echo "======================================================================="
echo "User UID: $USER_UID"
echo "User GID: $USER_GID"
echo "======================================================================="

# Check if base image exists
if ! docker image inspect gofr-base:latest >/dev/null 2>&1; then
    echo "Error: gofr-base:latest not found. Build it first:"
    echo "  cd lib/gofr-common/docker && ./build-base.sh"
    exit 1
fi

echo ""
echo "Building gofr-agent-dev:latest..."
docker build \
    -f "$SCRIPT_DIR/Dockerfile.dev" \
    -t gofr-agent-dev:latest \
    "$PROJECT_ROOT"

echo ""
echo "======================================================================="
echo "Build complete: gofr-agent-dev:latest"
echo "======================================================================="
echo ""
echo "Image size:"
docker images gofr-agent-dev:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
