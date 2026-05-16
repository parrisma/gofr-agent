#!/usr/bin/env bash
# =============================================================================
# Manage the gofr-agent MCP fixture services Swarm stack.
#
# Usage:
#   docker/fixtures-stack.sh build
#   docker/fixtures-stack.sh start     # deploys stack + joins dev container
#   docker/fixtures-stack.sh status
#   docker/fixtures-stack.sh logs [mcp-instruments|mcp-clients|mcp-trades|mcp-analytics]
#   docker/fixtures-stack.sh stop      # leaves dev container then removes stack
#   docker/fixtures-stack.sh restart
#
# Defaults (override via env):
#   GOFR_FIXTURE_STACK_NAME   = gofr-agent-mcp-fixtures
#   GOFR_FIXTURE_IMAGE_NAME   = gofr-agent-mcp-fixtures
#   GOFR_FIXTURE_OVERLAY_NET  = gofr-agent-mcp-fixtures-net
#   GOFR_DEV_CONTAINER        = gofr-agent-dev
#
# Network behaviour:
#   Swarm services can't join a local bridge (gofr-net), so on `start` the
#   dev container is connected to the attachable overlay network created by
#   the stack.  Services are then reachable inside the dev container by their
#   hostnames (gofr-agent-mcp-instruments, gofr-agent-mcp-clients, etc.).
#   On `stop` the dev container is disconnected before the stack is removed.
# =============================================================================
set -euo pipefail

ACTION="${1:-status}"
SERVICE="${2:-mcp-instruments}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.fixtures.yml"
PORTS_ENV="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
STACK_NAME="${GOFR_FIXTURE_STACK_NAME:-gofr-agent-mcp-fixtures}"

# Overlay network created by the stack — must match compose.fixtures.yml `name:`
OVERLAY_NET="${GOFR_FIXTURE_OVERLAY_NET:-${STACK_NAME}-net}"

# The dev container that should be bridged into the overlay so it can reach
# the fixture services by hostname.  Override via env if your container has a
# different name.
DEV_CONTAINER="${GOFR_DEV_CONTAINER:-gofr-agent-dev}"

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

force_refresh_services() {
    local service_names
    service_names="$(docker service ls \
        --filter "label=com.docker.stack.namespace=${STACK_NAME}" \
        --format '{{.Name}}')"

    if [[ -z "${service_names}" ]]; then
        return 0
    fi

    while IFS= read -r service_name; do
        [[ -n "${service_name}" ]] || continue
        echo "Refreshing fixture service '${service_name}' to pick up rebuilt image."
        docker service update --force --update-order stop-first --detach=false "${service_name}"
    done <<< "${service_names}"
}

# ---------------------------------------------------------------------------
# Dev container ↔ overlay network bridge
# ---------------------------------------------------------------------------
# After the stack deploys its attachable overlay, connect the dev container so
# it can reach fixture services by hostname (gofr-agent-mcp-instruments, etc.).
# Swarm services cannot join a local bridge (gofr-net) directly, so we go the
# other way: connect the dev container to the overlay.

connect_dev_container() {
    if ! docker ps -q --filter "name=^/${DEV_CONTAINER}$" | grep -q .; then
        echo "Dev container '${DEV_CONTAINER}' not running — skipping network attach."
        return 0
    fi

    # Wait up to 15 s for the overlay to appear after stack deploy
    local i=0
    printf "Waiting for overlay '%s' " "${OVERLAY_NET}"
    until docker network inspect "${OVERLAY_NET}" >/dev/null 2>&1; do
        printf "."
        sleep 1
        i=$((i + 1))
        if [[ ${i} -ge 15 ]]; then
            echo " timed out." >&2
            return 1
        fi
    done
    echo " ready."

    # Idempotent: skip if already connected
    if docker network inspect "${OVERLAY_NET}" \
            --format '{{range .Containers}}{{.Name}} {{end}}' \
            | grep -qw "${DEV_CONTAINER}"; then
        echo "Dev container '${DEV_CONTAINER}' already on '${OVERLAY_NET}'."
    else
        docker network connect "${OVERLAY_NET}" "${DEV_CONTAINER}"
        echo "Dev container '${DEV_CONTAINER}' connected to '${OVERLAY_NET}'."
    fi
}

disconnect_dev_container() {
    if docker network inspect "${OVERLAY_NET}" >/dev/null 2>&1; then
        docker network disconnect "${OVERLAY_NET}" "${DEV_CONTAINER}" 2>/dev/null \
            && echo "Dev container '${DEV_CONTAINER}' disconnected from '${OVERLAY_NET}'." \
            || true
    fi
}

start_stack() {
    load_ports_env
    ensure_swarm_manager
    docker stack deploy -c "${COMPOSE_FILE}" "${STACK_NAME}"
    force_refresh_services
    connect_dev_container
}

stop_stack() {
    disconnect_dev_container
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