#!/bin/bash
# Build n8n Production Docker image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="gofr-n8n"
IMAGE_TAG="2.3.6"

echo "======================================================================="
echo "Building n8n Production Docker image"
echo "======================================================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.n8n.prod" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    -t "${IMAGE_NAME}:prod" \
    "${SCRIPT_DIR}"

echo ""
echo "======================================================================="
echo "Build complete!"
echo "======================================================================="
echo ""
echo "Image tags:"
docker images "${IMAGE_NAME}" --format "{{.Repository}}:{{.Tag}} ({{.Size}})" | grep -E "${IMAGE_TAG}|latest"
echo ""
echo "To run production n8n:"
echo "  ./run-n8n-prod.sh"
