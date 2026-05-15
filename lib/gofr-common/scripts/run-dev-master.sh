#!/bin/bash
# Run GOFR master development container from a workspace root that contains
# multiple sibling GOFR repos. Mounts selected repos as read-write for
# cross-project consistency work.
#
# Image source:
#   - gofr-dig/lib/gofr-common/docker/Dockerfile.dev
#
# Usage:
#   - Run from /home/gofr/devroot (recommended), OR pass --workspace-root
#
# IMPORTANT:
#   This script expects to be run from (or pointed at) a workspace root directory
#   that contains all required GOFR repos checked out as siblings:
#     - gofr-dig
#     - gofr-doc
#     - gofr-np
#     - gofr-iq
#     - gofr-console
#   If any are missing, the script will fail fast.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_usage() {
    echo "Usage: $0 [--workspace-root PATH] [--network NAME]"
    echo ""
    echo "Defaults:"
    echo "  --workspace-root: current working directory (pwd)"
    echo "  --network:        gofr-test-net (or GOFRDIG_DOCKER_NETWORK)"
}

# Detect host user's UID/GID (the dev container must match so bind-mounted
# files have the right ownership). Prod/test images always use 1000:1000.
GOFR_USER="gofr"
GOFR_UID=$(id -u)
GOFR_GID=$(id -g)

# Container and image names
CONTAINER_NAME="gofr-dev-master"
IMAGE_NAME="gofr-dev-master:latest"

# Workspace root (directory containing gofr-dig, gofr-doc, etc.)
WORKSPACE_ROOT="$PWD"

# Primary network for testing; also connects to gofr-net for Vault access
DOCKER_NETWORK="${GOFRDIG_DOCKER_NETWORK:-gofr-test-net}"
GOFR_NETWORK="gofr-net"

# Parse command line arguments
while [ $# -gt 0 ]; do
    case $1 in
        --workspace-root)
            WORKSPACE_ROOT="$2"
            shift 2
            ;;
        --network)
            DOCKER_NETWORK="$2"
            shift 2
            ;;
        -h|--help)
            _usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1"
            echo ""
            _usage
            exit 1
            ;;
    esac
done

WORKSPACE_ROOT="$(cd "$WORKSPACE_ROOT" && pwd)"

REPO_DIG="${WORKSPACE_ROOT}/gofr-dig"
REPO_DOC="${WORKSPACE_ROOT}/gofr-doc"
REPO_NP="${WORKSPACE_ROOT}/gofr-np"
REPO_IQ="${WORKSPACE_ROOT}/gofr-iq"
REPO_CONSOLE="${WORKSPACE_ROOT}/gofr-console"

GOFR_COMMON_HOST_DIR="${REPO_DIG}/lib/gofr-common"
GOFR_COMMON_DOCKERFILE="${GOFR_COMMON_HOST_DIR}/docker/Dockerfile.dev"

echo "======================================================================="
echo "Starting GOFR Dev Master Container"
echo "======================================================================="
echo "Host user: $(whoami) (UID=${GOFR_UID}, GID=${GOFR_GID})"
if [ "$GOFR_UID" != "1000" ] || [ "$GOFR_GID" != "1000" ]; then
    echo "NOTE: Host UID/GID differs from image default (1000:1000)."
    echo "      Container will run with --user ${GOFR_UID}:${GOFR_GID}"
fi
echo "Workspace root: ${WORKSPACE_ROOT}"
echo "Networks: $DOCKER_NETWORK, $GOFR_NETWORK"
echo "Ports: none (dev container is for code editing; prod owns service ports)"
echo "======================================================================="

# Create docker network if it doesn't exist
if ! docker network inspect $DOCKER_NETWORK >/dev/null 2>&1; then
    echo "Creating network: $DOCKER_NETWORK"
    docker network create $DOCKER_NETWORK
fi

# Ensure gofr-net exists for Vault/service access
if ! docker network inspect $GOFR_NETWORK >/dev/null 2>&1; then
    echo "Creating network: $GOFR_NETWORK"
    docker network create $GOFR_NETWORK
fi

# Create shared secrets volume (shared across all GOFR projects)
SECRETS_VOLUME="gofr-secrets"
if ! docker volume inspect $SECRETS_VOLUME >/dev/null 2>&1; then
    echo "Creating volume: $SECRETS_VOLUME"
    docker volume create $SECRETS_VOLUME
fi

# Stop and remove existing container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing container: $CONTAINER_NAME"
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

# Detect Docker socket GID for group mapping
DOCKER_SOCKET="/var/run/docker.sock"
DOCKER_GID_ARGS=""
if [ -S "$DOCKER_SOCKET" ]; then
    DOCKER_GID=$(stat -c '%g' "$DOCKER_SOCKET")
    echo "Docker socket GID: $DOCKER_GID"
    DOCKER_GID_ARGS="-v $DOCKER_SOCKET:$DOCKER_SOCKET:rw --group-add $DOCKER_GID"
else
    echo "Warning: Docker socket not found at $DOCKER_SOCKET - docker commands will not work inside container"
fi

# ---- Pre-flight checks ------------------------------------------------------

_require_dir() {
    local path="$1"
    local label="$2"
    if [ ! -d "$path" ]; then
        echo ""
        echo "ERROR: Required directory not found: $path"
        echo "  Cause: expected ${label} repo under workspace root"
        echo "  Recovery: run from ${WORKSPACE_ROOT} or pass --workspace-root to the directory containing all GOFR repos"
        echo ""
        exit 1
    fi
}

_require_file() {
    local path="$1"
    local label="$2"
    if [ ! -f "$path" ]; then
        echo ""
        echo "ERROR: Required file not found: $path"
        echo "  Cause: ${label}"
        echo "  Recovery: ensure gofr-dig is checked out with lib/gofr-common initialised"
        echo ""
        exit 1
    fi
}

_require_dir "$REPO_DIG" "gofr-dig"
_require_dir "$REPO_DOC" "gofr-doc"
_require_dir "$REPO_NP" "gofr-np"
_require_dir "$REPO_IQ" "gofr-iq"
_require_dir "$REPO_CONSOLE" "gofr-console"
_require_dir "$GOFR_COMMON_HOST_DIR" "gofr-common (as submodule under gofr-dig/lib/gofr-common)"
_require_file "$GOFR_COMMON_DOCKERFILE" "gofr-common dev Dockerfile missing"

# Ensure base image exists (required by Dockerfile.dev)
if ! docker image inspect gofr-base:latest >/dev/null 2>&1; then
    echo ""
    echo "ERROR: Base image gofr-base:latest not found."
    echo "  Cause: gofr-common Dockerfile.dev is FROM gofr-base:latest"
    echo "  Recovery: build it first: cd ${GOFR_COMMON_HOST_DIR}/docker && ./build-base.sh"
    echo ""
    exit 1
fi

# Build image if missing
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Image '$IMAGE_NAME' not found - building now..."
    echo "  Dockerfile: $GOFR_COMMON_DOCKERFILE"
    echo "  Context:    $GOFR_COMMON_HOST_DIR"
    docker build \
        -t "$IMAGE_NAME" \
        -f "$GOFR_COMMON_DOCKERFILE" \
        "$GOFR_COMMON_HOST_DIR"
fi

# ---- Run container ----------------------------------------------------------
# NOTE: No host port bindings — the dev container is for code editing.
# Production containers (via start-prod.sh) own the service ports.
# Build --user flag: only override when host UID/GID != image default (1000)
USER_ARGS=""
if [ "$GOFR_UID" != "1000" ] || [ "$GOFR_GID" != "1000" ]; then
    USER_ARGS="--user ${GOFR_UID}:${GOFR_GID}"
fi

echo "Running: docker run -d --name $CONTAINER_NAME ..."
CONTAINER_ID=$(docker run -d \
    --name "$CONTAINER_NAME" \
    --network "$DOCKER_NETWORK" \
    $USER_ARGS \
    -v "$REPO_DIG:/home/${GOFR_USER}/devroot/gofr-dig:rw" \
    -v "$REPO_DOC:/home/${GOFR_USER}/devroot/gofr-doc:rw" \
    -v "$REPO_NP:/home/${GOFR_USER}/devroot/gofr-np:rw" \
    -v "$REPO_IQ:/home/${GOFR_USER}/devroot/gofr-iq:rw" \
    -v "$REPO_CONSOLE:/home/${GOFR_USER}/devroot/gofr-console:rw" \
    -v "$GOFR_COMMON_HOST_DIR:/home/${GOFR_USER}/devroot/gofr-common:rw" \
    -v ${SECRETS_VOLUME}:/home/${GOFR_USER}/devroot/gofr-dig/secrets:rw \
    -v ${SECRETS_VOLUME}:/home/${GOFR_USER}/devroot/gofr-doc/secrets:rw \
    -v ${SECRETS_VOLUME}:/home/${GOFR_USER}/devroot/gofr-np/secrets:rw \
    -v ${SECRETS_VOLUME}:/home/${GOFR_USER}/devroot/gofr-iq/secrets:rw \
    $DOCKER_GID_ARGS \
    "$IMAGE_NAME" 2>&1) || {
    echo ""
    echo "ERROR: docker run failed."
    echo "  Output: $CONTAINER_ID"
    echo ""
    exit 1
}

# ---- Verify container is actually running -----------------------------------
echo "Waiting for container to stabilise..."
sleep 2

# Connect to gofr-net for Vault and other GOFR services
if ! docker network inspect $GOFR_NETWORK --format '{{range .Containers}}{{.Name}} {{end}}' | grep -q "$CONTAINER_NAME"; then
    echo "Connecting to $GOFR_NETWORK..."
    docker network connect $GOFR_NETWORK "$CONTAINER_NAME"
fi

CONTAINER_STATE=$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "not_found")
CONTAINER_RUNNING=$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo "false")

if [[ "$CONTAINER_STATE" != "running" || "$CONTAINER_RUNNING" != "true" ]]; then
    EXIT_CODE=$(docker inspect --format '{{.State.ExitCode}}' "$CONTAINER_NAME" 2>/dev/null || echo "?")
    echo ""
    echo "======================================================================="
    echo "ERROR: Container '$CONTAINER_NAME' is NOT running"
    echo "======================================================================="
    echo "  State:     $CONTAINER_STATE"
    echo "  Exit code: $EXIT_CODE"
    echo ""
    echo "  Container logs:"
    echo "  ---------------------------------"
    docker logs "$CONTAINER_NAME" 2>&1
    echo ""
    echo "  Full logs:  docker logs $CONTAINER_NAME"
    echo "  Inspect:    docker inspect $CONTAINER_NAME"
    echo ""
    exit 1
fi

# ---- Success ----------------------------------------------------------------
echo ""
echo "======================================================================="
echo "Container RUNNING: $CONTAINER_NAME"
echo "======================================================================="
echo "  ID:      ${CONTAINER_ID:0:12}"
echo "  State:   $CONTAINER_STATE"
echo "  Image:   $IMAGE_NAME"
echo "  Networks: $DOCKER_NETWORK, $GOFR_NETWORK"
echo "  Docker:  $( [ -n "$DOCKER_GID_ARGS" ] && echo 'socket mounted (DinD ready)' || echo 'socket NOT mounted' )"
echo ""
echo "Useful commands:"
echo "  docker logs -f $CONTAINER_NAME          # Follow logs"
echo "  docker exec -it $CONTAINER_NAME bash    # Shell access"
echo "  docker stop $CONTAINER_NAME             # Stop container"
