#!/bin/bash
# Description: Run the repository quality gate plus selected unit and integration test workflows.
# =============================================================================
# GOFR-Agent Test Runner
# =============================================================================
# Standardized test runner script for gofr-agent.
# Runs code quality gate first, then unit and integration tests.
#
# Usage:
#   ./scripts/run_tests.sh                          # Run all tests (quality gate → unit → integration)
#   ./scripts/run_tests.sh tests/unit/              # Run specific test directory
#   ./scripts/run_tests.sh -k "session"             # Run tests matching keyword
#   ./scripts/run_tests.sh -v                       # Run with verbose output
#   ./scripts/run_tests.sh --coverage               # Run with coverage report
#   ./scripts/run_tests.sh --coverage-html          # Run with HTML coverage report
#   ./scripts/run_tests.sh --docker                 # Run tests in Docker container
#   ./scripts/run_tests.sh --unit                   # Run unit tests only (no servers)
#   ./scripts/run_tests.sh --integration            # Run integration tests (with agent server)
#   ./scripts/run_tests.sh --quality                # Run code quality gate only
#   ./scripts/run_tests.sh --no-servers             # Run without starting gofr-agent server
#   ./scripts/run_tests.sh --stop                   # Stop servers only
#   ./scripts/run_tests.sh --cleanup-only           # Clean environment only
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project-specific configuration
PROJECT_NAME="gofr-agent"
ENV_PREFIX="GOFR_AGENT"
CONTAINER_NAME="gofr-agent-dev"
TEST_DIR="tests"
COVERAGE_SOURCE="app"
LOG_DIR="${PROJECT_ROOT}/logs"

# Activate virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
    echo "Activated venv: ${VENV_DIR}"
else
    echo -e "${YELLOW}Warning: Virtual environment not found at ${VENV_DIR}${NC}"
fi

# Set up PYTHONPATH for gofr-common discovery
if [ -d "${PROJECT_ROOT}/lib/gofr-common/src" ]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"
elif [ -d "${PROJECT_ROOT}/../gofr-common/src" ]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/../gofr-common/src:${PYTHONPATH:-}"
else
    export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
fi

# Test environment
export GOFR_AGENT_ENV="TEST"
export GOFR_AGENT_JWT_SECRET="${GOFR_AGENT_JWT_SECRET:-test-secret-key-for-secure-testing-do-not-use-in-production}"

# gofr-agent ports (prod + 100 for test)
export GOFR_AGENT_MCP_PORT="${GOFR_AGENT_MCP_PORT:-8190}"
export GOFR_AGENT_MCPO_PORT="${GOFR_AGENT_MCPO_PORT:-8191}"
export GOFR_AGENT_WEB_PORT="${GOFR_AGENT_WEB_PORT:-8192}"

# Disable LLM calls by default in tests; integration tests override this
export GOFR_AGENT_LLM_MODEL="${GOFR_AGENT_LLM_MODEL:-test:mock}"

# Ensure directories exist
mkdir -p "${LOG_DIR}"
mkdir -p "${PROJECT_ROOT}/data"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

print_header() {
    echo -e "${GREEN}=== ${PROJECT_NAME} Test Runner ===${NC}"
    echo "Project root: ${PROJECT_ROOT}"
    echo "PYTHONPATH:   ${PYTHONPATH}"
    echo "MCP Port:     ${GOFR_AGENT_MCP_PORT}"
    echo "LLM Model:    ${GOFR_AGENT_LLM_MODEL}"
    echo ""
}

port_in_use() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -i ":${port}" >/dev/null 2>&1
    elif command -v ss >/dev/null 2>&1; then
        ss -tuln | grep -q ":${port} "
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tuln | grep -q ":${port} "
    else
        timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/${port}" >/dev/null 2>&1
    fi
}

free_port() {
    local port=$1
    if ! port_in_use "$port"; then
        return 0
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti ":${port}" | xargs -r kill -9 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :${port}" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d'=' -f2 | xargs -r kill -9 2>/dev/null || true
    fi
    sleep 1
}

stop_servers() {
    echo "Stopping gofr-agent server processes..."
    pkill -9 -f "python.*app/main_mcp" 2>/dev/null || true
    pkill -9 -f "python.*app.main_mcp" 2>/dev/null || true
    pkill -9 -f "gofr-agent.*mcp" 2>/dev/null || true
    sleep 2

    if ps aux | grep -E "python.*(app/main_mcp|app\.main_mcp)" | grep -v grep >/dev/null 2>&1; then
        echo -e "${RED}WARNING: Some server processes still running${NC}"
        return 1
    fi
    echo "All server processes stopped"
    return 0
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    stop_servers || true
    rm -f "${LOG_DIR}/${PROJECT_NAME}_mcp_test.log" 2>/dev/null || true
    echo -e "${GREEN}Cleanup complete${NC}"
}

start_mcp_server() {
    local log_file="${LOG_DIR}/${PROJECT_NAME}_mcp_test.log"
    echo -e "${YELLOW}Starting gofr-agent MCP server on port ${GOFR_AGENT_MCP_PORT}...${NC}"

    free_port "${GOFR_AGENT_MCP_PORT}"
    rm -f "${log_file}"

    nohup uv run python app/main_mcp.py \
        --port "${GOFR_AGENT_MCP_PORT}" \
        --jwt-secret "${GOFR_AGENT_JWT_SECRET}" \
        --no-auth \
        --log-level DEBUG \
        > "${log_file}" 2>&1 &
    MCP_PID=$!
    echo "MCP PID: ${MCP_PID}"

    echo -n "Waiting for MCP server"
    for _ in {1..40}; do
        if ! kill -0 ${MCP_PID} 2>/dev/null; then
            echo -e " ${RED}✗${NC}"
            echo "--- Server log ---"
            tail -30 "${log_file}"
            return 1
        fi
        if port_in_use "${GOFR_AGENT_MCP_PORT}"; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 0.5
    done
    echo -e " ${RED}✗${NC}"
    echo "--- Server log ---"
    tail -30 "${log_file}"
    return 1
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

USE_DOCKER=false
START_SERVERS=false        # Integration tests manage their own in-process server by default
COVERAGE=false
COVERAGE_HTML=false
RUN_UNIT=false
RUN_INTEGRATION=false
RUN_QUALITY=false
RUN_ALL=false
STOP_ONLY=false
CLEANUP_ONLY=false
PYTEST_ARGS=()
PYTEST_HAS_TARGET=false

pytest_target_path() {
    local arg="$1"
    local path_part=""

    if [[ "$arg" == -* ]]; then
        return 1
    fi

    path_part="${arg%%::*}"
    if [[ -e "$path_part" ]]; then
        printf '%s\n' "$path_part"
        return 0
    fi
    return 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)
            USE_DOCKER=true
            shift
            ;;
        --coverage|--cov)
            COVERAGE=true
            shift
            ;;
        --coverage-html)
            COVERAGE=true
            COVERAGE_HTML=true
            shift
            ;;
        --unit)
            RUN_UNIT=true
            START_SERVERS=false
            shift
            ;;
        --integration)
            RUN_INTEGRATION=true
            START_SERVERS=true
            shift
            ;;
        --quality)
            RUN_QUALITY=true
            START_SERVERS=false
            shift
            ;;
        --all)
            RUN_ALL=true
            START_SERVERS=true
            shift
            ;;
        --no-servers|--without-servers)
            START_SERVERS=false
            shift
            ;;
        --with-servers|--start-servers)
            START_SERVERS=true
            shift
            ;;
        --stop|--stop-servers)
            STOP_ONLY=true
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PYTEST_ARGS...]"
            echo ""
            echo "Options:"
            echo "  --docker           Run tests inside Docker container"
            echo "  --coverage         Run with coverage report"
            echo "  --coverage-html    Run with HTML coverage report"
            echo "  --unit             Run unit tests only (no servers)"
            echo "  --integration      Run integration tests (starts MCP server)"
            echo "  --quality          Run code quality gate only"
            echo "  --all              Run quality gate + unit + integration tests"
            echo "  --no-servers       Don't start gofr-agent server"
            echo "  --with-servers     Start gofr-agent server before tests"
            echo "  --stop             Stop servers and exit"
            echo "  --cleanup-only     Clean environment and exit"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                           # quality gate → unit → integration"
            echo "  $0 --unit                    # unit tests only"
            echo "  $0 --quality                 # ruff + pyright + bandit only"
            echo "  $0 --coverage                # full suite with coverage"
            echo "  $0 tests/unit/test_pool.py   # single test file"
            echo "  $0 -k session                # tests matching 'session'"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

for arg in "${PYTEST_ARGS[@]}"; do
    if pytest_target_path "$arg" >/dev/null; then
        PYTEST_HAS_TARGET=true
        break
    fi
done

# =============================================================================
# MAIN EXECUTION
# =============================================================================

print_header

if [ "$STOP_ONLY" = true ]; then
    echo -e "${YELLOW}Stopping servers and exiting...${NC}"
    stop_servers
    exit 0
fi

if [ "$CLEANUP_ONLY" = true ]; then
    cleanup_environment
    exit 0
fi

cleanup_environment

# Optionally start the MCP server for subprocess-based integration tests
MCP_PID=""
if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    echo -e "${GREEN}=== Starting gofr-agent MCP Server ===${NC}"
    start_mcp_server || { stop_servers; exit 1; }
    echo ""
fi

# Build coverage arguments
COVERAGE_ARGS=""
if [ "$COVERAGE" = true ]; then
    COVERAGE_ARGS="--cov=${COVERAGE_SOURCE} --cov-report=term-missing"
    if [ "$COVERAGE_HTML" = true ]; then
        COVERAGE_ARGS="${COVERAGE_ARGS} --cov-report=html:htmlcov"
    fi
    echo -e "${BLUE}Coverage reporting enabled${NC}"
fi

# =============================================================================
# RUN TESTS
# =============================================================================

echo -e "${GREEN}=== Running Tests ===${NC}"
set +e
TEST_EXIT_CODE=0
PYTEST_IMPORT_MODE=(--import-mode=importlib)

pytest_args_have_target() {
    for arg in "$@"; do
        if pytest_target_path "$arg" >/dev/null; then
            return 0
        fi
    done
    return 1
}

run_quality_gate() {
    echo -e "${BLUE}--- Code Quality Gate (ruff + pyright + bandit) ---${NC}"
    uv run python -m pytest "${TEST_DIR}/code_quality/" -v
}

run_unit_tests() {
    # Optional args: specific test file(s) to run; defaults to the full unit/ directory.
    if [ $# -gt 0 ]; then
        echo -e "${BLUE}--- Unit Tests: $* ---${NC}"
        if pytest_args_have_target "$@"; then
            uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "$@" -v ${COVERAGE_ARGS}
        else
            uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "${TEST_DIR}/unit/" "$@" -v ${COVERAGE_ARGS}
        fi
    else
        echo -e "${BLUE}--- Unit Tests ---${NC}"
        uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "${TEST_DIR}/unit/" -v ${COVERAGE_ARGS}
    fi
}

run_integration_tests() {
    # Optional args: specific test file(s) to run; defaults to the full integration/ directory.
    if [ $# -gt 0 ]; then
        echo -e "${BLUE}--- Integration Tests: $* ---${NC}"
        if pytest_args_have_target "$@"; then
            uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "$@" -v ${COVERAGE_ARGS}
        else
            uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "${TEST_DIR}/integration/" "$@" -v ${COVERAGE_ARGS}
        fi
    else
        echo -e "${BLUE}--- Integration Tests ---${NC}"
        uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "${TEST_DIR}/integration/" -v ${COVERAGE_ARGS}
    fi
}

if [ "$USE_DOCKER" = true ]; then
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${RED}Container ${CONTAINER_NAME} is not running.${NC}"
        echo "Run: ./docker/run-dev.sh"
        exit 1
    fi
    INNER_ARGS=""
    if [ "$COVERAGE" = true ]; then INNER_ARGS="$INNER_ARGS --coverage"; fi
    if [ "$COVERAGE_HTML" = true ]; then INNER_ARGS="$INNER_ARGS --coverage-html"; fi
    if [ "$RUN_UNIT" = true ]; then INNER_ARGS="$INNER_ARGS --unit"; fi
    if [ "$RUN_INTEGRATION" = true ]; then INNER_ARGS="$INNER_ARGS --integration"; fi
    if [ "$RUN_QUALITY" = true ]; then INNER_ARGS="$INNER_ARGS --quality"; fi
    echo -e "${BLUE}Running tests inside container ${CONTAINER_NAME}...${NC}"
    docker exec "${CONTAINER_NAME}" bash -c \
        "cd /home/gofr/devroot/${PROJECT_NAME} && ./scripts/run_tests.sh ${INNER_ARGS}"
    TEST_EXIT_CODE=$?

elif [ "$RUN_QUALITY" = true ]; then
    run_quality_gate
    TEST_EXIT_CODE=$?

elif [ "$RUN_UNIT" = true ]; then
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed — skipping unit tests${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        if [ ${#PYTEST_ARGS[@]} -gt 0 ]; then
            run_unit_tests "${PYTEST_ARGS[@]}"
        else
            run_unit_tests
        fi
        TEST_EXIT_CODE=$?
    fi

elif [ "$RUN_INTEGRATION" = true ]; then
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed — skipping integration tests${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        if [ ${#PYTEST_ARGS[@]} -gt 0 ]; then
            run_integration_tests "${PYTEST_ARGS[@]}"
        else
            run_integration_tests
        fi
        TEST_EXIT_CODE=$?
    fi

elif [ "$RUN_ALL" = true ]; then
    echo -e "${BLUE}Step 1/3: Code quality gate...${NC}"
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        echo -e "${BLUE}Step 2/3: Unit tests...${NC}"
        run_unit_tests
        UNIT_EXIT=$?
        if [ $UNIT_EXIT -ne 0 ]; then
            echo -e "${RED}Unit tests failed${NC}"
            TEST_EXIT_CODE=$UNIT_EXIT
        else
            echo ""
            echo -e "${BLUE}Step 3/3: Integration tests...${NC}"
            run_integration_tests
            TEST_EXIT_CODE=$?
        fi
    fi

elif [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    # Default: quality gate → unit → integration
    echo -e "${BLUE}Step 1/3: Code quality gate...${NC}"
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed — fix issues before running further tests${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        echo -e "${BLUE}Step 2/3: Unit tests...${NC}"
        run_unit_tests
        UNIT_EXIT=$?
        if [ $UNIT_EXIT -ne 0 ]; then
            echo -e "${RED}Unit tests failed${NC}"
            TEST_EXIT_CODE=$UNIT_EXIT
        else
            echo ""
            echo -e "${BLUE}Step 3/3: Integration tests...${NC}"
            run_integration_tests
            TEST_EXIT_CODE=$?
        fi
    fi

elif [ "$PYTEST_HAS_TARGET" = false ]; then
    # Option-only pytest arguments should still run the normal stepwise suite.
    echo -e "${BLUE}Step 1/3: Code quality gate...${NC}"
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed — fix issues before running further tests${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        echo -e "${BLUE}Step 2/3: Unit tests...${NC}"
        run_unit_tests "${PYTEST_ARGS[@]}"
        UNIT_EXIT=$?
        if [ $UNIT_EXIT -ne 0 ]; then
            echo -e "${RED}Unit tests failed${NC}"
            TEST_EXIT_CODE=$UNIT_EXIT
        else
            echo ""
            echo -e "${BLUE}Step 3/3: Integration tests...${NC}"
            run_integration_tests "${PYTEST_ARGS[@]}"
            TEST_EXIT_CODE=$?
        fi
    fi

else
    # Custom pytest arguments: quality gate first, then targeted run.
    run_quality_gate
    QUALITY_EXIT=$?
    if [ $QUALITY_EXIT -ne 0 ]; then
        echo -e "${RED}Code quality gate failed — skipping tests${NC}"
        TEST_EXIT_CODE=$QUALITY_EXIT
    else
        echo ""
        uv run python -m pytest "${PYTEST_IMPORT_MODE[@]}" "${PYTEST_ARGS[@]}" ${COVERAGE_ARGS}
        TEST_EXIT_CODE=$?
    fi
fi

set -e

# =============================================================================
# CLEANUP
# =============================================================================

if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    echo ""
    echo -e "${YELLOW}Stopping test servers...${NC}"
    stop_servers || true
fi

# =============================================================================
# RESULTS
# =============================================================================

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=== All Tests Passed ===${NC}"
else
    echo -e "${RED}=== Tests Failed (exit code: ${TEST_EXIT_CODE}) ===${NC}"
fi

exit $TEST_EXIT_CODE
