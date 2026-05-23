#!/bin/bash
# Description: Start the real gofr-agent MCP server for local manual and UI testing workflows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_FIXTURE_MANIFEST="${PROJECT_ROOT}/tmp/fixture-services.yml"
DEFAULT_COMPOSE_MANIFEST="${PROJECT_ROOT}/docker/services.compose.dev.yml"
DEFAULT_LOCAL_MANIFEST="${PROJECT_ROOT}/services.yml"
COMMON_SRC="${PROJECT_ROOT}/lib/gofr-common/src"
OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL="openai:deepseek/deepseek-v4-pro"
DEFAULT_AGENT_TIMEOUT_SECONDS="240"
DEFAULT_MAX_STEPS="50"
DEFAULT_MAX_STEPS_HARD_CAP="100"
DEFAULT_HUB_ENABLED="true"
DEFAULT_HUB_HOST="gofr-agent-dev"
DEFAULT_HUB_STORE_BACKEND="memory"
DEFAULT_HUB_CACHE_URL="redis://gofr-agent-valkey:6379/0"
DEFAULT_EXTERNAL_CACHE_MEMORY_BUDGET_BYTES="268435456"
DEFAULT_EXTERNAL_CACHE_ACTIVE_SESSION_BUDGET="4"
DEFAULT_EXTERNAL_CACHE_MAX_RESULTS="64"

HOST="${GOFR_AGENT_HOST:-0.0.0.0}"
PORT="${GOFR_AGENT_MCP_PORT:-8090}"
MODEL="${GOFR_AGENT_LLM_MODEL:-${DEFAULT_LLM_MODEL}}"
LOG_LEVEL="${GOFR_AGENT_LOG_LEVEL:-INFO}"
SERVICES_FILE="${GOFR_AGENT_SERVICES_FILE:-}"
OPENROUTER_API_KEY_VALUE="${OPENROUTER_API_KEY:-}"
AGENT_TIMEOUT_SECONDS="${GOFR_AGENT_AGENT_TIMEOUT_SECONDS:-${DEFAULT_AGENT_TIMEOUT_SECONDS}}"
MAX_STEPS="${GOFR_AGENT_MAX_STEPS:-${DEFAULT_MAX_STEPS}}"
MAX_STEPS_HARD_CAP="${GOFR_AGENT_MAX_STEPS_HARD_CAP:-${DEFAULT_MAX_STEPS_HARD_CAP}}"
HUB_ENABLED_RAW="${GOFR_AGENT_HUB_ENABLED:-${DEFAULT_HUB_ENABLED}}"
HUB_HOST="${GOFR_AGENT_HUB_HOST:-${DEFAULT_HUB_HOST}}"
HUB_PORT="${GOFR_AGENT_HUB_PORT:-}"
HUB_URL="${GOFR_AGENT_HUB_URL:-}"
HUB_STORE_BACKEND="${GOFR_AGENT_HUB_STORE_BACKEND:-${DEFAULT_HUB_STORE_BACKEND}}"
HUB_CACHE_URL="${GOFR_AGENT_HUB_CACHE_URL:-}"

DEFAULT_ALLOWED_HOSTS="gofr-agent-dev,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,gofr-agent-runtime,gofr-agent-runtime:8090,gofr-agent-workspace,gofr-agent-workspace:8090,gofr-agent-manual,gofr-agent-manual:8090,127.0.0.1:*,localhost:*,[::1]:*"
DEFAULT_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000"

normalize_bool() {
    local value
    value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
    case "${value}" in
        1|true|yes|on)
            printf 'true'
            ;;
        0|false|no|off)
            printf 'false'
            ;;
        *)
            echo "Invalid boolean value: ${1}" >&2
            exit 1
            ;;
    esac
}

build_hub_url() {
    printf 'http://%s:%s/mcp' "$1" "$2"
}

usage() {
    cat <<EOF
Start the real gofr-agent MCP server for UI testing.

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --host HOST                Bind host (default: ${HOST})
  --port PORT                Bind port (default: ${PORT})
  --model MODEL              LLM model string (default: ${MODEL})
  --llm-model MODEL          Alias for --model
  --openrouter-api-key KEY   Export OpenRouter/OpenAI API env vars for this run
  --api-key KEY              Alias for --openrouter-api-key
  --log-level LEVEL          Server log level (default: ${LOG_LEVEL})
  --services-file PATH       Services manifest to load
  --no-services              Start without a services manifest
  --timeout SECONDS          Alias for --agent-timeout-seconds
  --agent-timeout-seconds    SECONDS Wall-clock timeout for a single agent run (default: ${AGENT_TIMEOUT_SECONDS})
  --max-steps COUNT          Default tool-call limit when callers omit max_steps (default: ${MAX_STEPS})
    --max-steps-hard-cap COUNT Upper bound for caller-provided max_steps (default: ${MAX_STEPS_HARD_CAP})
    --hub-enabled              Enable the built-in results hub (default: ${HUB_ENABLED_RAW})
    --hub-disabled             Disable the built-in results hub
    --hub-url URL              Public MCP URL advertised for hub callbacks
    --hub-host HOST            Host used to build the default hub URL (default: ${HUB_HOST})
    --hub-port PORT            Port used to build the default hub URL (default: ${HUB_PORT:-${PORT}})
    --hub-store-backend NAME   Hub store backend: memory or external_cache (default: ${HUB_STORE_BACKEND})
    --hub-cache-url URL        External cache URL when using external_cache
  -h, --help                 Show this help

Manifest selection order when --services-file is omitted:
  1. ${DEFAULT_FIXTURE_MANIFEST}
    2. ${DEFAULT_COMPOSE_MANIFEST}
    3. ${DEFAULT_LOCAL_MANIFEST}
    4. no services file

Environment defaults applied when not already set:
  GOFR_AGENT_AUTH_MODE=dev
    GOFR_AGENT_LLM_MODEL=${DEFAULT_LLM_MODEL}
    GOFR_AGENT_AGENT_TIMEOUT_SECONDS=${DEFAULT_AGENT_TIMEOUT_SECONDS}
    GOFR_AGENT_MAX_STEPS=${DEFAULT_MAX_STEPS}
    GOFR_AGENT_MAX_STEPS_HARD_CAP=${DEFAULT_MAX_STEPS_HARD_CAP}
    GOFR_AGENT_HUB_ENABLED=${DEFAULT_HUB_ENABLED}
    GOFR_AGENT_HUB_URL=$(build_hub_url "${DEFAULT_HUB_HOST}" "${PORT}")
    GOFR_AGENT_HUB_STORE_BACKEND=${DEFAULT_HUB_STORE_BACKEND}
  GOFR_AGENT_MCP_ALLOWED_HOSTS=${DEFAULT_ALLOWED_HOSTS}
  GOFR_AGENT_MCP_ALLOWED_ORIGINS=${DEFAULT_ALLOWED_ORIGINS}
  GOFR_AGENT_CORS_ORIGINS=${DEFAULT_ALLOWED_ORIGINS}

When --hub-store-backend external_cache is selected and explicit hub sizing env
vars are unset, this script applies a conservative real-server profile:
    GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES=${DEFAULT_EXTERNAL_CACHE_MEMORY_BUDGET_BYTES}
    GOFR_AGENT_HUB_CACHE_ACTIVE_SESSION_BUDGET=${DEFAULT_EXTERNAL_CACHE_ACTIVE_SESSION_BUDGET}
    GOFR_AGENT_HUB_MAX_RESULTS=${DEFAULT_EXTERNAL_CACHE_MAX_RESULTS}

Examples:
    docker compose -f docker/compose.dev.yml --profile runtime up -d --build
    docker compose -f docker/compose.dev.yml --profile workspace up -d --build
  $(basename "$0")
  $(basename "$0") --services-file ${DEFAULT_FIXTURE_MANIFEST}
    $(basename "$0") --services-file ${DEFAULT_COMPOSE_MANIFEST} --hub-url http://gofr-agent-manual:8090/mcp
    $(basename "$0") --hub-store-backend external_cache --hub-cache-url ${DEFAULT_HUB_CACHE_URL}
    $(basename "$0") --llm-model openai:deepseek/deepseek-v4-pro --timeout 600 --openrouter-api-key sk-or-...
    $(basename "$0") --llm-model test --no-services
    OPENROUTER_API_KEY=sk-or-... $(basename "$0") --model openai:deepseek/deepseek-v4-pro
EOF
}

NO_SERVICES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --host=*)
            HOST="${1#*=}"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --port=*)
            PORT="${1#*=}"
            shift
            ;;
        --model|--llm-model)
            MODEL="$2"
            shift 2
            ;;
        --model=*|--llm-model=*)
            MODEL="${1#*=}"
            shift
            ;;
        --openrouter-api-key|--api-key)
            OPENROUTER_API_KEY_VALUE="$2"
            shift 2
            ;;
        --openrouter-api-key=*|--api-key=*)
            OPENROUTER_API_KEY_VALUE="${1#*=}"
            shift
            ;;
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --log-level=*)
            LOG_LEVEL="${1#*=}"
            shift
            ;;
        --services-file)
            SERVICES_FILE="$2"
            shift 2
            ;;
        --services-file=*)
            SERVICES_FILE="${1#*=}"
            shift
            ;;
        --no-services)
            NO_SERVICES=1
            shift
            ;;
        --timeout|--agent-timeout-seconds)
            AGENT_TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --timeout=*|--agent-timeout-seconds=*)
            AGENT_TIMEOUT_SECONDS="${1#*=}"
            shift
            ;;
        --max-steps)
            MAX_STEPS="$2"
            shift 2
            ;;
        --max-steps=*)
            MAX_STEPS="${1#*=}"
            shift
            ;;
        --max-steps-hard-cap)
            MAX_STEPS_HARD_CAP="$2"
            shift 2
            ;;
        --max-steps-hard-cap=*)
            MAX_STEPS_HARD_CAP="${1#*=}"
            shift
            ;;
        --hub-enabled)
            HUB_ENABLED_RAW="true"
            shift
            ;;
        --hub-disabled|--no-hub)
            HUB_ENABLED_RAW="false"
            shift
            ;;
        --hub-url)
            HUB_URL="$2"
            shift 2
            ;;
        --hub-url=*)
            HUB_URL="${1#*=}"
            shift
            ;;
        --hub-host)
            HUB_HOST="$2"
            shift 2
            ;;
        --hub-host=*)
            HUB_HOST="${1#*=}"
            shift
            ;;
        --hub-port)
            HUB_PORT="$2"
            shift 2
            ;;
        --hub-port=*)
            HUB_PORT="${1#*=}"
            shift
            ;;
        --hub-store-backend)
            HUB_STORE_BACKEND="$2"
            shift 2
            ;;
        --hub-store-backend=*)
            HUB_STORE_BACKEND="${1#*=}"
            shift
            ;;
        --hub-cache-url)
            HUB_CACHE_URL="$2"
            shift 2
            ;;
        --hub-cache-url=*)
            HUB_CACHE_URL="${1#*=}"
            shift
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

if [[ ${NO_SERVICES} -eq 1 ]]; then
    SERVICES_FILE=""
elif [[ -z "${SERVICES_FILE}" ]]; then
    if [[ -f "${DEFAULT_FIXTURE_MANIFEST}" ]]; then
        SERVICES_FILE="${DEFAULT_FIXTURE_MANIFEST}"
    elif [[ -f "${DEFAULT_COMPOSE_MANIFEST}" ]]; then
        SERVICES_FILE="${DEFAULT_COMPOSE_MANIFEST}"
    elif [[ -f "${DEFAULT_LOCAL_MANIFEST}" ]]; then
        SERVICES_FILE="${DEFAULT_LOCAL_MANIFEST}"
    fi
fi

HUB_ENABLED="$(normalize_bool "${HUB_ENABLED_RAW}")"
if [[ -z "${HUB_PORT}" ]]; then
    HUB_PORT="${PORT}"
fi
if [[ "${HUB_ENABLED}" == "true" && -z "${HUB_URL}" ]]; then
    HUB_URL="$(build_hub_url "${HUB_HOST}" "${HUB_PORT}")"
fi
if [[ "${HUB_STORE_BACKEND}" == "external_cache" && -z "${HUB_CACHE_URL}" ]]; then
    HUB_CACHE_URL="${DEFAULT_HUB_CACHE_URL}"
fi

export GOFR_AGENT_AUTH_MODE="${GOFR_AGENT_AUTH_MODE:-dev}"
export GOFR_AGENT_LLM_MODEL="${MODEL}"
export GOFR_AGENT_AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS}"
export GOFR_AGENT_MAX_STEPS="${MAX_STEPS}"
export GOFR_AGENT_MAX_STEPS_HARD_CAP="${MAX_STEPS_HARD_CAP}"
export GOFR_AGENT_HUB_ENABLED="${HUB_ENABLED}"
export GOFR_AGENT_HUB_STORE_BACKEND="${HUB_STORE_BACKEND}"
if [[ "${HUB_STORE_BACKEND}" == "external_cache" ]]; then
    export GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES="${GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES:-${DEFAULT_EXTERNAL_CACHE_MEMORY_BUDGET_BYTES}}"
    export GOFR_AGENT_HUB_CACHE_ACTIVE_SESSION_BUDGET="${GOFR_AGENT_HUB_CACHE_ACTIVE_SESSION_BUDGET:-${DEFAULT_EXTERNAL_CACHE_ACTIVE_SESSION_BUDGET}}"
    export GOFR_AGENT_HUB_MAX_RESULTS="${GOFR_AGENT_HUB_MAX_RESULTS:-${DEFAULT_EXTERNAL_CACHE_MAX_RESULTS}}"
fi
if [[ -n "${HUB_URL}" ]]; then
    export GOFR_AGENT_HUB_URL="${HUB_URL}"
else
    unset GOFR_AGENT_HUB_URL
fi
if [[ -n "${HUB_CACHE_URL}" ]]; then
    export GOFR_AGENT_HUB_CACHE_URL="${HUB_CACHE_URL}"
else
    unset GOFR_AGENT_HUB_CACHE_URL
fi
export GOFR_AGENT_MCP_ALLOWED_HOSTS="${GOFR_AGENT_MCP_ALLOWED_HOSTS:-${DEFAULT_ALLOWED_HOSTS}}"
export GOFR_AGENT_MCP_ALLOWED_ORIGINS="${GOFR_AGENT_MCP_ALLOWED_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"
export GOFR_AGENT_CORS_ORIGINS="${GOFR_AGENT_CORS_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"

if [[ -n "${OPENROUTER_API_KEY_VALUE}" ]]; then
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY_VALUE}"
    export GOFR_AGENT_OPENROUTER_API_KEY="${OPENROUTER_API_KEY_VALUE}"
    export OPENAI_API_KEY="${OPENAI_API_KEY:-${OPENROUTER_API_KEY_VALUE}}"
    export OPENAI_BASE_URL="${OPENAI_BASE_URL:-${OPENROUTER_BASE_URL}}"
fi

if [[ "${MODEL}" != test* && -z "${OPENROUTER_API_KEY:-}" && -z "${GOFR_AGENT_OPENROUTER_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "Error: model '${MODEL}' requires an API key." >&2
    echo "Pass --openrouter-api-key/--api-key or set OPENROUTER_API_KEY." >&2
    echo "Use --llm-model test only when you intentionally want pydantic-ai test-model tool payloads." >&2
    exit 1
fi

if [[ -d "${COMMON_SRC}" ]]; then
    export PYTHONPATH="${PROJECT_ROOT}:${COMMON_SRC}:${PYTHONPATH:-}"
else
    export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
fi

COMMAND=(
    uv run python -m app.main_mcp
    --host "${HOST}"
    --port "${PORT}"
    --log-level "${LOG_LEVEL}"
    --llm-model "${MODEL}"
)

if [[ -n "${SERVICES_FILE}" ]]; then
    COMMAND+=(--services-file "${SERVICES_FILE}")
fi

echo "======================================================================="
echo "Starting real gofr-agent MCP server"
echo "======================================================================="
echo "Host:             ${HOST}"
echo "Port:             ${PORT}"
echo "Model:            ${MODEL}"
if [[ "${MODEL}" == test* ]]; then
    echo "Model warning:    pydantic-ai test model returns raw tool payload maps"
fi
echo "OpenRouter key:   $( [[ -n "${OPENROUTER_API_KEY:-}" ]] && echo configured || echo unset )"
echo "OpenAI base URL:  ${OPENAI_BASE_URL:-<default>}"
echo "Services file:    ${SERVICES_FILE:-<none>}"
echo "Auth mode:        ${GOFR_AGENT_AUTH_MODE}"
echo "Hub enabled:      ${HUB_ENABLED}"
echo "Hub host:         ${HUB_HOST}"
echo "Hub port:         ${HUB_PORT}"
echo "Hub URL:          ${HUB_URL:-<unset>}"
echo "Hub backend:      ${HUB_STORE_BACKEND}"
echo "Hub cache URL:    ${HUB_CACHE_URL:-<unset>}"
if [[ "${HUB_STORE_BACKEND}" == "external_cache" ]]; then
    echo "Hub cache budget: ${GOFR_AGENT_HUB_CACHE_MEMORY_BUDGET_BYTES}"
    echo "Hub sessions:     ${GOFR_AGENT_HUB_CACHE_ACTIVE_SESSION_BUDGET}"
    echo "Hub max results:  ${GOFR_AGENT_HUB_MAX_RESULTS}"
fi
echo "Agent timeout:    ${GOFR_AGENT_AGENT_TIMEOUT_SECONDS}"
echo "Max steps:        ${GOFR_AGENT_MAX_STEPS}"
echo "Max steps cap:    ${GOFR_AGENT_MAX_STEPS_HARD_CAP}"
echo "PYTHONPATH:       ${PYTHONPATH}"
echo "Allowed hosts:    ${GOFR_AGENT_MCP_ALLOWED_HOSTS}"
echo "Allowed origins:  ${GOFR_AGENT_MCP_ALLOWED_ORIGINS}"
echo "CORS origins:     ${GOFR_AGENT_CORS_ORIGINS}"
echo "======================================================================="

exec "${COMMAND[@]}"