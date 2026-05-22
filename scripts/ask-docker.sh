#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_NAME="${GOFR_AGENT_CLI_IMAGE:-gofr-agent-cli:latest}"
NETWORK_NAME="${GOFR_AGENT_CLI_NETWORK:-gofr-dev-net}"
AGENT_URL="${GOFR_AGENT_CLI_URL:-${GOFR_AGENT_URL:-http://gofr-agent-dev:8090/mcp}}"
AGENT_TOKEN="${GOFR_AGENT_CLI_TOKEN:-${GOFR_AGENT_TOKEN:-dev-admin-token}}"
FORCE_BUILD="${GOFR_AGENT_CLI_BUILD:-0}"

usage() {
    cat <<EOF
Run app.cli.ask inside a disposable Docker container attached to the compose dev network.

Usage:
  $(basename "$0") [app.cli.ask args...]

Environment overrides:
  GOFR_AGENT_CLI_IMAGE     Docker image name (default: ${IMAGE_NAME})
  GOFR_AGENT_CLI_NETWORK   Docker network name (default: ${NETWORK_NAME})
  GOFR_AGENT_CLI_URL       MCP URL passed to the container (default: ${AGENT_URL})
  GOFR_AGENT_CLI_TOKEN     Bearer token passed to the container (default: ${AGENT_TOKEN})
  GOFR_AGENT_CLI_BUILD=1   Force a rebuild of the CLI image before running

Examples:
  $(basename "$0") "What services are available?"
  $(basename "$0") --verbose --max-steps 20 "Summarize healthy services"
  $(basename "$0") --reset session-123
EOF
}

if [[ $# -eq 0 ]]; then
    usage >&2
    exit 1
fi

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    echo "Error: Docker network '${NETWORK_NAME}' not found." >&2
    echo "Start docker compose -f docker/compose.dev.yml --profile runtime up -d --build" >&2
    echo "or docker compose -f docker/compose.dev.yml --profile workspace up -d --build first." >&2
    exit 1
fi

if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1 || [[ "${FORCE_BUILD}" == "1" ]]; then
    docker build -f "${PROJECT_ROOT}/docker/Dockerfile.cli" -t "${IMAGE_NAME}" "${PROJECT_ROOT}"
fi

docker_args=(
    run
    --rm
    --network "${NETWORK_NAME}"
    -e "GOFR_AGENT_URL=${AGENT_URL}"
    -e "GOFR_AGENT_TOKEN=${AGENT_TOKEN}"
)

if [[ -t 0 && -t 1 ]]; then
    docker_args+=( -it )
elif [[ -t 0 ]]; then
    docker_args+=( -i )
fi

exec docker "${docker_args[@]}" "${IMAGE_NAME}" "$@"