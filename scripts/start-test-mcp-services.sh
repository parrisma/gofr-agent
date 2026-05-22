#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST_PATH="${PROJECT_ROOT}/tmp/fixture-services.yml"
COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.dev.yml"
CANONICAL_MANIFEST_PATH="${PROJECT_ROOT}/docker/services.compose.dev.yml"
DEV_NETWORK="${GOFR_DEV_NETWORK:-gofr-dev-net}"
MANUAL_AGENT_ALIAS="${GOFR_AGENT_MANUAL_ALIAS:-gofr-agent-manual}"
CURRENT_CONTAINER_ID="$(hostname)"

COMPOSE_SERVICES=(
  valkey
  mcp-instruments
  mcp-clients
  mcp-trades
  mcp-analytics
)

usage() {
    cat <<EOF
Start the Compose-managed fixture services and Valkey, then write a manifest
that the real gofr-agent server can consume.

Usage:
  $(basename "$0") [--manifest-path PATH]

Options:
  --manifest-path PATH       Output manifest path (default: ${MANIFEST_PATH})
  -h, --help                 Show this help

This script does two things:
  1. Starts Valkey + the fixture services via docker/compose.dev.yml
  2. Connects the current dev container to ${DEV_NETWORK} as '${MANUAL_AGENT_ALIAS}'
  3. Writes a services manifest for manual real-server runs

After it completes, start the real server with:
  ${PROJECT_ROOT}/scripts/start-real-server.sh \
    --services-file <manifest-path> \
    --hub-url http://${MANUAL_AGENT_ALIAS}:8090/mcp
EOF
}

connect_current_container() {
    if ! docker ps -q --filter "id=${CURRENT_CONTAINER_ID}" | grep -q .; then
        echo "Current dev container '${CURRENT_CONTAINER_ID}' is not visible to Docker." >&2
        exit 1
    fi

    docker network disconnect "${DEV_NETWORK}" "${CURRENT_CONTAINER_ID}" >/dev/null 2>&1 || true
    docker network connect --alias "${MANUAL_AGENT_ALIAS}" "${DEV_NETWORK}" "${CURRENT_CONTAINER_ID}" >/dev/null
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest-path)
            MANIFEST_PATH="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

mkdir -p "$(dirname "${MANIFEST_PATH}")"

docker compose -f "${COMPOSE_FILE}" up -d --build "${COMPOSE_SERVICES[@]}"
connect_current_container

cp "${CANONICAL_MANIFEST_PATH}" "${MANIFEST_PATH}"

echo "======================================================================="
echo "Fixture MCP services and Valkey are running"
echo "======================================================================="
echo "Manifest written to: ${MANIFEST_PATH}"
echo "Current dev container attached to ${DEV_NETWORK} as: ${MANUAL_AGENT_ALIAS}"
echo ""
echo "Start the real server with:"
echo "  ${PROJECT_ROOT}/scripts/start-real-server.sh --services-file ${MANIFEST_PATH} --hub-url http://${MANUAL_AGENT_ALIAS}:8090/mcp"