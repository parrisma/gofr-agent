#!/bin/bash
# Build Open WebUI Production Docker image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="gofr-openwebui"
IMAGE_TAG="0.4.8"

echo "======================================================================="
echo "Building Open WebUI Production Docker image"
echo "======================================================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.openwebui.prod" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "${SCRIPT_DIR}"

echo ""
echo "======================================================================="
echo "Build complete!"
echo "======================================================================="
echo ""
echo "Image tags:"
docker images "${IMAGE_NAME}" --format "{{.Repository}}:{{.Tag}} ({{.Size}})" | grep -E "${IMAGE_TAG}|prod"
echo ""
echo "To run production Open WebUI:"
echo "  ./run-openwebui-prod.sh"
