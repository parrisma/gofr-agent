#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.dev.yml"
MANIFEST_FILE="${PROJECT_ROOT}/docker/services.compose.dev.yml"
RUNTIME_CONTAINER="gofr-agent-runtime"
NETWORK_NAME="gofr-net"
DEFAULT_MODEL="openai:deepseek/deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS="600"
DEFAULT_MAX_STEPS="100"
DEFAULT_MAX_STEPS_HARD_CAP="200"
START_WAIT_SECONDS="${GOFR_AGENT_START_WAIT_SECONDS:-120}"
DEFAULT_ALLOWED_HOSTS="gofr-agent-dev,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,gofr-agent-runtime,gofr-agent-runtime:8090,gofr-agent-workspace,gofr-agent-workspace:8090,gofr-agent-manual,gofr-agent-manual:8090,127.0.0.1,127.0.0.1:*,localhost,localhost:*,[::1],[::1]:*"
DEFAULT_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000"
LEGACY_ALLOWED_HOSTS_RUN_DEV="gofr-agent-dev,gofr-agent-dev:8040,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,127.0.0.1:*,localhost:*,[::1]:*"
LEGACY_ALLOWED_HOSTS_COMPOSE="gofr-agent-dev,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,gofr-agent-runtime,gofr-agent-runtime:8090,gofr-agent-workspace,gofr-agent-workspace:8090,gofr-agent-manual,gofr-agent-manual:8090,127.0.0.1:*,localhost:*,[::1]:*"

usage() {
    cat <<EOF
Manage the compose dev runtime stack for gofr-agent.

Usage:
  $(basename "$0") start [OPENROUTER_API_KEY]
  $(basename "$0") stop
  $(basename "$0") status

The runtime service in ${COMPOSE_FILE} already starts gofr-agent with:
  --services-file ${MANIFEST_FILE}

For 'start', pass the OpenRouter API key as the first positional argument or set
OPENROUTER_API_KEY in the environment. No other input is required.

Optional environment overrides for 'start':
  GOFR_AGENT_LLM_MODEL                  Default: ${DEFAULT_MODEL}
  GOFR_AGENT_AGENT_TIMEOUT_SECONDS      Default: ${DEFAULT_TIMEOUT_SECONDS}
  GOFR_AGENT_MAX_STEPS                  Default: ${DEFAULT_MAX_STEPS}
  GOFR_AGENT_MAX_STEPS_HARD_CAP         Default: ${DEFAULT_MAX_STEPS_HARD_CAP}
  GOFR_AGENT_START_WAIT_SECONDS         Default: ${START_WAIT_SECONDS}

The stack uses the shared Docker network ${NETWORK_NAME}. If that network does
not exist yet, this script creates it before running docker compose.
EOF
}

ensure_network() {
    if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
        return 0
    fi

    echo "Creating shared Docker network '${NETWORK_NAME}'"
    docker network create "${NETWORK_NAME}" >/dev/null
}

health_status() {
    docker inspect "${RUNTIME_CONTAINER}" \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        2>/dev/null || true
}

wait_for_runtime() {
    local deadline
    local status

    deadline=$((SECONDS + START_WAIT_SECONDS))
    while (( SECONDS < deadline )); do
        status="$(health_status)"
        case "${status}" in
            healthy)
                return 0
                ;;
            unhealthy|exited|dead)
                echo "Runtime container entered status '${status}'." >&2
                docker compose -f "${COMPOSE_FILE}" logs --tail=80 "${RUNTIME_CONTAINER}" >&2 || true
                return 1
                ;;
        esac
        sleep 2
    done

    echo "Timed out waiting for ${RUNTIME_CONTAINER} to become healthy." >&2
    docker compose -f "${COMPOSE_FILE}" logs --tail=80 "${RUNTIME_CONTAINER}" >&2 || true
    return 1
}

normalize_allowed_hosts() {
    local current

    current="${GOFR_AGENT_MCP_ALLOWED_HOSTS:-}"
    case "${current}" in
        ""|"${LEGACY_ALLOWED_HOSTS_RUN_DEV}"|"${LEGACY_ALLOWED_HOSTS_COMPOSE}")
            printf '%s' "${DEFAULT_ALLOWED_HOSTS}"
            ;;
        *)
            printf '%s' "${current}"
            ;;
    esac
}

start_stack() {
    local api_key

    api_key="${1:-${OPENROUTER_API_KEY:-}}"
    if [[ -z "${api_key}" ]]; then
        echo "Error: start requires an OpenRouter API key." >&2
        usage >&2
        exit 1
    fi
    if [[ ! -f "${MANIFEST_FILE}" ]]; then
        echo "Error: services manifest not found at ${MANIFEST_FILE}" >&2
        exit 1
    fi

    export OPENROUTER_API_KEY="${api_key}"
    export GOFR_AGENT_LLM_MODEL="${GOFR_AGENT_LLM_MODEL:-${DEFAULT_MODEL}}"
    export GOFR_AGENT_AGENT_TIMEOUT_SECONDS="${GOFR_AGENT_AGENT_TIMEOUT_SECONDS:-${DEFAULT_TIMEOUT_SECONDS}}"
    export GOFR_AGENT_MAX_STEPS="${GOFR_AGENT_MAX_STEPS:-${DEFAULT_MAX_STEPS}}"
    export GOFR_AGENT_MAX_STEPS_HARD_CAP="${GOFR_AGENT_MAX_STEPS_HARD_CAP:-${DEFAULT_MAX_STEPS_HARD_CAP}}"
    export GOFR_AGENT_MCP_ALLOWED_HOSTS="$(normalize_allowed_hosts)"
    export GOFR_AGENT_MCP_ALLOWED_ORIGINS="${GOFR_AGENT_MCP_ALLOWED_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"
    export GOFR_AGENT_CORS_ORIGINS="${GOFR_AGENT_CORS_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"

    ensure_network
    docker compose -f "${COMPOSE_FILE}" --profile runtime up -d --build --force-recreate
    wait_for_runtime

    echo "======================================================================="
    echo "Compose runtime stack is healthy"
    echo "======================================================================="
    echo "Compose file:      ${COMPOSE_FILE}"
    echo "Services manifest: ${MANIFEST_FILE}"
    echo "Docker network:    ${NETWORK_NAME}"
    echo "Model:             ${GOFR_AGENT_LLM_MODEL}"
    echo "Timeout:           ${GOFR_AGENT_AGENT_TIMEOUT_SECONDS}"
    echo "Max steps:         ${GOFR_AGENT_MAX_STEPS}"
    echo "Max steps cap:     ${GOFR_AGENT_MAX_STEPS_HARD_CAP}"
    echo "Health URL:        http://localhost:8090/health"
    echo "Curl example:      curl -sf http://localhost:8090/ping"
    echo "Ask example:       ${PROJECT_ROOT}/scripts/ask-docker.sh \"What services are available?\""
}

stop_stack() {
    docker compose -f "${COMPOSE_FILE}" down
}

status_stack() {
    docker compose -f "${COMPOSE_FILE}" --profile runtime ps
}

COMMAND="${1:-}"
case "${COMMAND}" in
    start)
        shift
        start_stack "$@"
        ;;
    stop)
        stop_stack
        ;;
    status)
        status_stack
        ;;
    -h|--help|help|"")
        usage
        ;;
    *)
        echo "Unknown command: ${COMMAND}" >&2
        usage >&2
        exit 1
        ;;
esac