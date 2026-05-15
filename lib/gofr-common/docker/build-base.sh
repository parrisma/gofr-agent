#!/bin/bash
# Build the GOFR base Docker image
# Usage: ./build-base.sh [--no-cache] [--push]
#
# This image is shared by all GOFR projects:
#   - gofr-dig
#   - gofr-plot
#   - gofr-np
#   - gofr-doc

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="gofr-base"
IMAGE_TAG="latest"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

# Parse arguments
NO_CACHE=""
PUSH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --tag)
            IMAGE_TAG="$2"
            FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--no-cache] [--push] [--tag TAG]"
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Building GOFR Base Image"
echo "======================================================================="
echo "Image: ${FULL_IMAGE}"
echo "Context: ${PROJECT_ROOT}"
echo "Dockerfile: ${SCRIPT_DIR}/Dockerfile.base"
echo "======================================================================="

cd "$PROJECT_ROOT"

docker build \
    ${NO_CACHE} \
    -t "${FULL_IMAGE}" \
    -f docker/Dockerfile.base \
    .

echo ""
echo "======================================================================="
echo "Build complete: ${FULL_IMAGE}"
echo "======================================================================="

# Verify the image
echo ""
echo "Verifying image..."
docker run --rm "${FULL_IMAGE}" python --version
docker run --rm "${FULL_IMAGE}" uv --version

echo ""
echo "Image size:"
docker images "${IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

if [ "$PUSH" = true ]; then
    echo ""
    echo "Pushing image..."
    docker push "${FULL_IMAGE}"
fi

echo ""
echo "To use this image in project Dockerfiles:"
echo "  FROM ${FULL_IMAGE}"
