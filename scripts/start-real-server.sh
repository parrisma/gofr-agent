#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_FIXTURE_MANIFEST="${PROJECT_ROOT}/tmp/fixture-services.yml"
DEFAULT_LOCAL_MANIFEST="${PROJECT_ROOT}/services.yml"
COMMON_SRC="${PROJECT_ROOT}/lib/gofr-common/src"
OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"

HOST="${GOFR_AGENT_HOST:-0.0.0.0}"
PORT="${GOFR_AGENT_MCP_PORT:-8090}"
MODEL="${GOFR_AGENT_LLM_MODEL:-test}"
LOG_LEVEL="${GOFR_AGENT_LOG_LEVEL:-INFO}"
SERVICES_FILE="${GOFR_AGENT_SERVICES_FILE:-}"
OPENROUTER_API_KEY_VALUE="${OPENROUTER_API_KEY:-}"

DEFAULT_ALLOWED_HOSTS="gofr-agent-dev,gofr-agent-dev:8090,gofr-agent,gofr-agent:8090,127.0.0.1:*,localhost:*,[::1]:*"
DEFAULT_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://gofr-console-dev:3000"

usage() {
    cat <<EOF
Start the real gofr-agent MCP server for UI testing.

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --host HOST                Bind host (default: ${HOST})
  --port PORT                Bind port (default: ${PORT})
  --model MODEL              LLM model string (default: ${MODEL})
  --openrouter-api-key KEY   Export OpenRouter/OpenAI API env vars for this run
  --api-key KEY              Alias for --openrouter-api-key
  --log-level LEVEL          Server log level (default: ${LOG_LEVEL})
  --services-file PATH       Services manifest to load
  --no-services              Start without a services manifest
  -h, --help                 Show this help

Manifest selection order when --services-file is omitted:
  1. ${DEFAULT_FIXTURE_MANIFEST}
  2. ${DEFAULT_LOCAL_MANIFEST}
  3. no services file

Environment defaults applied when not already set:
  GOFR_AGENT_AUTH_MODE=dev
  GOFR_AGENT_MCP_ALLOWED_HOSTS=${DEFAULT_ALLOWED_HOSTS}
  GOFR_AGENT_MCP_ALLOWED_ORIGINS=${DEFAULT_ALLOWED_ORIGINS}
  GOFR_AGENT_CORS_ORIGINS=${DEFAULT_ALLOWED_ORIGINS}

Examples:
  $(basename "$0")
  $(basename "$0") --services-file ${DEFAULT_FIXTURE_MANIFEST}
    $(basename "$0") --model openai:deepseek/deepseek-v4-pro --openrouter-api-key sk-or-...
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
        --port)
            PORT="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --openrouter-api-key|--api-key)
            OPENROUTER_API_KEY_VALUE="$2"
            shift 2
            ;;
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --services-file)
            SERVICES_FILE="$2"
            shift 2
            ;;
        --no-services)
            NO_SERVICES=1
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
    elif [[ -f "${DEFAULT_LOCAL_MANIFEST}" ]]; then
        SERVICES_FILE="${DEFAULT_LOCAL_MANIFEST}"
    fi
fi

export GOFR_AGENT_AUTH_MODE="${GOFR_AGENT_AUTH_MODE:-dev}"
export GOFR_AGENT_MCP_ALLOWED_HOSTS="${GOFR_AGENT_MCP_ALLOWED_HOSTS:-${DEFAULT_ALLOWED_HOSTS}}"
export GOFR_AGENT_MCP_ALLOWED_ORIGINS="${GOFR_AGENT_MCP_ALLOWED_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"
export GOFR_AGENT_CORS_ORIGINS="${GOFR_AGENT_CORS_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS}}"

if [[ -n "${OPENROUTER_API_KEY_VALUE}" ]]; then
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY_VALUE}"
    export GOFR_AGENT_OPENROUTER_API_KEY="${OPENROUTER_API_KEY_VALUE}"
    export OPENAI_API_KEY="${OPENAI_API_KEY:-${OPENROUTER_API_KEY_VALUE}}"
    export OPENAI_BASE_URL="${OPENAI_BASE_URL:-${OPENROUTER_BASE_URL}}"
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
echo "OpenRouter key:   $( [[ -n "${OPENROUTER_API_KEY:-}" ]] && echo configured || echo unset )"
echo "OpenAI base URL:  ${OPENAI_BASE_URL:-<default>}"
echo "Services file:    ${SERVICES_FILE:-<none>}"
echo "Auth mode:        ${GOFR_AGENT_AUTH_MODE}"
echo "PYTHONPATH:       ${PYTHONPATH}"
echo "Allowed hosts:    ${GOFR_AGENT_MCP_ALLOWED_HOSTS}"
echo "Allowed origins:  ${GOFR_AGENT_MCP_ALLOWED_ORIGINS}"
echo "CORS origins:     ${GOFR_AGENT_CORS_ORIGINS}"
echo "======================================================================="

exec "${COMMAND[@]}"