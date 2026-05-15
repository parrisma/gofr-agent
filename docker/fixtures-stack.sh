#!/usr/bin/env bash
# =============================================================================
# Manage the gofr-agent MCP fixture services Swarm stack.
#
# Usage:
#   docker/fixtures-stack.sh build
#   docker/fixtures-stack.sh start
#   docker/fixtures-stack.sh status
#   docker/fixtures-stack.sh logs [mcp-instruments|mcp-clients|mcp-trades|mcp-analytics]
#   docker/fixtures-stack.sh stop
#   docker/fixtures-stack.sh restart
#
# Defaults:
#   Stack name: gofr-agent-mcp-fixtures
#   Image name: gofr-agent-mcp-fixtures:latest
# =============================================================================
set -euo pipefail

ACTION="${1:-status}"
SERVICE="${2:-mcp-instruments}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.fixtures.yml"
PORTS_ENV="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
STACK_NAME="${GOFR_FIXTURE_STACK_NAME:-gofr-agent-mcp-fixtures}"

load_ports_env() {
    if [[ -f "${PORTS_ENV}" ]]; then
        set -a
        # shellcheck disable=SC1090
        . "${PORTS_ENV}"
        set +a
    fi
}

ensure_swarm_manager() {
    local swarm_state manager_state
    swarm_state="$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || true)"
    manager_state="$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null || true)"

    if [[ "${swarm_state}" == "inactive" ]]; then
        docker swarm init --advertise-addr 127.0.0.1 >/dev/null
        return 0
    fi

    if [[ "${manager_state}" != "true" ]]; then
        echo "Docker is in swarm mode, but this node is not a manager." >&2
        echo "Run this on a manager node, or leave/re-init swarm intentionally." >&2
        return 1
    fi
}

build_image() {
    "${PROJECT_ROOT}/docker/build-fixtures.sh"
}

start_stack() {
    load_ports_env
    ensure_swarm_manager
    docker stack deploy -c "${COMPOSE_FILE}" "${STACK_NAME}"
}

stop_stack() {
    docker stack rm "${STACK_NAME}"
}

show_status() {
    echo "Stack: ${STACK_NAME}"
    echo ""
    docker stack services "${STACK_NAME}" 2>/dev/null || true
    echo ""
    docker stack ps "${STACK_NAME}" --no-trunc 2>/dev/null || true
}

show_logs() {
    docker service logs -f "${STACK_NAME}_${SERVICE}"
}

case "${ACTION}" in
    build)
        build_image
        ;;
    start|up|deploy)
        start_stack
        ;;
    stop|down|rm|remove)
        stop_stack
        ;;
    restart)
        stop_stack || true
        start_stack
        ;;
    status|ps|ls)
        show_status
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Unknown action: ${ACTION}" >&2
        echo "Expected: build, start, status, logs, stop, restart" >&2
        exit 2
        ;;
esac