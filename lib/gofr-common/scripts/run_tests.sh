#!/bin/bash
# =============================================================================
# GOFR-Common Test Runner
# =============================================================================
# Standardized test runner script with consistent configuration across all
# GOFR projects. This script:
# - Sets up virtual environment
# - Configures PYTHONPATH for gofr-common discovery
# - Supports coverage reporting
# - Supports Docker execution
# - Optionally starts Vault in ephemeral test mode
# - Runs pytest with proper configuration
#
# Usage:
#   ./scripts/run_tests.sh                          # Run all tests
#   ./scripts/run_tests.sh tests/test_config.py    # Run specific test file
#   ./scripts/run_tests.sh -k "auth"               # Run tests matching keyword
#   ./scripts/run_tests.sh -v                      # Run with verbose output
#   ./scripts/run_tests.sh --coverage              # Run with coverage report
#   ./scripts/run_tests.sh --coverage-html         # Run with HTML coverage report
#   ./scripts/run_tests.sh --docker                # Run tests in Docker container
#   ./scripts/run_tests.sh --unit                  # Run unit tests only
#   ./scripts/run_tests.sh --vault                 # Start Vault for integration tests
#   ./scripts/run_tests.sh --cleanup-only          # Clean environment only
#
# REQUIREMENTS:
#   - Python virtual environment (.venv) or uv installed
#   - Docker running (for --docker or --vault options)
#   - gofr_ports.env must exist (for port configuration)
#   - For integration tests: Vault/Neo4j/ChromaDB running or use --vault flag
#
#   Unit tests (--unit) have no external dependencies.
#   Integration tests may require infrastructure or use ephemeral Vault (--vault).
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# =============================================================================
# CONFIGURATION
# =============================================================================

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Prefer uv for environment management when available
USE_UV=false
if command -v uv > /dev/null 2>&1; then
    USE_UV=true
fi

# Project-specific configuration
PROJECT_NAME="gofr-common"
ENV_PREFIX="GOFR_COMMON"
CONTAINER_NAME="gofr-common-dev"
TEST_DIR="tests"
COVERAGE_SOURCE="gofr_common"

# Activate virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ "$USE_UV" = true ]; then
    # Avoid VIRTUAL_ENV bleed from parent shells; uv will resolve the project env
    unset VIRTUAL_ENV
    echo "Using uv run for tooling (no manual venv activation)."
else
    if [ -f "${VENV_DIR}/bin/activate" ]; then
        source "${VENV_DIR}/bin/activate"
        echo "Activated venv: ${VENV_DIR}"
    else
        echo -e "${YELLOW}Warning: Virtual environment not found at ${VENV_DIR}${NC}"
        echo "Trying to use uv run instead..."
    fi
fi

# Set up PYTHONPATH for module discovery
export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"

# Test configuration
export GOFR_COMMON_ENV="TEST"
export GOFR_COMMON_JWT_SECRET="test-secret-key-for-secure-testing-do-not-use-in-production"
export GOFR_COMMON_LOG_LEVEL="DEBUG"

# Load port configuration from .env and apply test overrides
PORTS_CONFIG="${PROJECT_ROOT}/config/gofr_ports.env"
if [[ -f "${PORTS_CONFIG}" ]]; then
    set -a
    source "${PORTS_CONFIG}"
    set +a

    # Apply test offsets for services
    for svc in DOC PLOT NP DIG IQ; do
        for kind in MCP MCPO WEB; do
            base_var="GOFR_${svc}_${kind}_PORT"
            test_var="GOFR_${svc}_${kind}_PORT_TEST"
            test_val="${!test_var:-}"
            if [[ -n "${test_val}" ]]; then
                export "${base_var}=${test_val}"
            fi
        done
    done

    # Infrastructure test ports
    export GOFR_VAULT_PORT="${GOFR_VAULT_PORT_TEST:-${GOFR_VAULT_PORT}}"
    export GOFR_CHROMA_PORT="${GOFR_CHROMA_PORT_TEST:-${GOFR_CHROMA_PORT}}"
    export GOFR_NEO4J_HTTP_PORT="${GOFR_NEO4J_HTTP_PORT_TEST:-${GOFR_NEO4J_HTTP_PORT}}"
    export GOFR_NEO4J_BOLT_PORT="${GOFR_NEO4J_BOLT_PORT_TEST:-${GOFR_NEO4J_BOLT_PORT}}"
else
    echo -e "${YELLOW}Warning: Port config not found at ${PORTS_CONFIG}${NC}"
fi

# Vault test configuration
VAULT_CONTAINER_NAME="gofr-vault-test"
VAULT_IMAGE="hashicorp/vault:1.15.4"
VAULT_INTERNAL_PORT=8200  # Vault dev-mode default
VAULT_TEST_PORT="${GOFR_VAULT_PORT_TEST:-8301}"
# Always use a dedicated test-only token to avoid leaking prod/dev tokens
VAULT_TEST_TOKEN="${GOFR_TEST_VAULT_DEV_TOKEN:-gofr-dev-root-token}"
TEST_NETWORK="${GOFR_TEST_NETWORK:-gofr-test-net}"
# Connect any running dev container so in-container pytest can reach test services
DEV_CONTAINER_NAMES=("gofr-common-dev" "gofr-dig-dev")

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

print_header() {
    echo -e "${GREEN}=== ${PROJECT_NAME} Test Runner ===${NC}"
    echo "Project root: ${PROJECT_ROOT}"
    echo "Environment: ${GOFR_COMMON_ENV}"
    echo "PYTHONPATH: ${PYTHONPATH}"
    echo ""
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    # Remove any test artifacts
    rm -rf "${PROJECT_ROOT}/.pytest_cache" 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/htmlcov" 2>/dev/null || true
    rm -f "${PROJECT_ROOT}/.coverage" 2>/dev/null || true
    echo -e "${GREEN}Cleanup complete${NC}"
}

start_vault_test_container() {
    echo -e "${BLUE}Starting Vault in ephemeral dev mode...${NC}"

    # Detect if script is running inside a container to choose the right Vault URL
    is_running_in_docker() {
        [ -f "/.dockerenv" ] && return 0
        grep -qa "docker\|containerd" /proc/1/cgroup 2>/dev/null && return 0
        return 1
    }

    # Ensure test network exists
    if ! docker network ls --format '{{.Name}}' | grep -q "^${TEST_NETWORK}$"; then
        echo "Creating test network: ${TEST_NETWORK}"
        docker network create "${TEST_NETWORK}"
    fi

    # Connect dev containers to test network if not already connected
    for dev_name in "${DEV_CONTAINER_NAMES[@]}"; do
        if docker ps --format '{{.Names}}' | grep -q "^${dev_name}$"; then
            if ! docker network inspect "${TEST_NETWORK}" --format '{{range .Containers}}{{.Name}} {{end}}' | grep -q "${dev_name}"; then
                echo "Connecting ${dev_name} to ${TEST_NETWORK}..."
                docker network connect "${TEST_NETWORK}" "${dev_name}" 2>/dev/null || true
            fi
        fi
    done

    # Pull Vault image if not present
    if ! docker images "${VAULT_IMAGE}" --format '{{.Repository}}' | grep -q "vault"; then
        echo -e "${YELLOW}Pulling Vault image: ${VAULT_IMAGE}${NC}"
        docker pull "${VAULT_IMAGE}"
    fi

    # Stop any existing test container
    if docker ps -aq -f name="^${VAULT_CONTAINER_NAME}$" | grep -q .; then
        echo "Removing existing Vault test container..."
        docker rm -f "${VAULT_CONTAINER_NAME}" 2>/dev/null || true
    fi

    # Start Vault in dev mode (no init/unseal needed, ephemeral in-memory storage)
    echo "Starting ${VAULT_CONTAINER_NAME} (dev mode, port ${VAULT_TEST_PORT}->${VAULT_INTERNAL_PORT})..."
    docker run -d \
        --name "${VAULT_CONTAINER_NAME}" \
        --hostname "${VAULT_CONTAINER_NAME}" \
        --network "${TEST_NETWORK}" \
        --cap-add IPC_LOCK \
        -p "${VAULT_TEST_PORT}:${VAULT_INTERNAL_PORT}" \
        -e "VAULT_DEV_ROOT_TOKEN_ID=${VAULT_TEST_TOKEN}" \
        -e "VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:${VAULT_INTERNAL_PORT}" \
        -e "VAULT_LOG_LEVEL=warn" \
        "${VAULT_IMAGE}" \
        server -dev > /dev/null

    # Wait for Vault to become healthy
    echo -n "Waiting for Vault to be ready"
    local retries=0
    local max_retries=30
    while [ $retries -lt $max_retries ]; do
        if docker exec -e VAULT_ADDR="http://127.0.0.1:${VAULT_INTERNAL_PORT}" \
            "${VAULT_CONTAINER_NAME}" vault status > /dev/null 2>&1; then
            echo " ready!"
            break
        fi
        echo -n "."
        sleep 1
        retries=$((retries + 1))
    done
    if [ $retries -eq $max_retries ]; then
        echo ""
        echo -e "${RED}Vault failed to start within ${max_retries}s${NC}"
        docker logs "${VAULT_CONTAINER_NAME}" 2>&1 | tail -20
        return 1
    fi

    # Enable KV secrets engine v2 at the expected path
    docker exec -e VAULT_ADDR="http://127.0.0.1:${VAULT_INTERNAL_PORT}" \
        -e VAULT_TOKEN="${VAULT_TEST_TOKEN}" \
        "${VAULT_CONTAINER_NAME}" \
        vault secrets enable -path=secret -version=2 kv 2>/dev/null || true

    # Set environment variables for tests
    if is_running_in_docker; then
        # Inside a container on the test network, talk to Vault by container name
        export GOFR_VAULT_URL="http://${VAULT_CONTAINER_NAME}:${VAULT_INTERNAL_PORT}"
    else
        # On the host, use the published test port
        export GOFR_VAULT_URL="http://localhost:${VAULT_TEST_PORT}"
    fi
    export GOFR_VAULT_TOKEN="${VAULT_TEST_TOKEN}"

    echo -e "${GREEN}Vault started successfully${NC}"
    echo "  Container: ${VAULT_CONTAINER_NAME}"
    echo "  Network:   ${TEST_NETWORK}"
    echo "  URL:       ${GOFR_VAULT_URL}"
    echo "  Token:     ${GOFR_VAULT_TOKEN}"
    echo ""
}

stop_vault_test_container() {
    echo -e "${YELLOW}Stopping Vault test container...${NC}"
    if docker ps -q -f name="^${VAULT_CONTAINER_NAME}$" | grep -q .; then
        docker stop ${VAULT_CONTAINER_NAME} 2>/dev/null || true
        docker rm ${VAULT_CONTAINER_NAME} 2>/dev/null || true
        echo -e "${GREEN}Vault container stopped${NC}"
    else
        echo "Vault container was not running"
    fi
    
    # Disconnect dev containers from test network (optional cleanup)
    for dev_name in "${DEV_CONTAINER_NAMES[@]}"; do
        if docker ps --format '{{.Names}}' | grep -q "^${dev_name}$"; then
            docker network disconnect "${TEST_NETWORK}" "${dev_name}" 2>/dev/null || true
        fi
    done
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

USE_DOCKER=false
COVERAGE=false
COVERAGE_HTML=false
RUN_UNIT=false
CLEANUP_ONLY=false
SKIP_LINT=false
USE_VAULT=true  # Default to starting Vault for integration tests
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
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
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        --skip-lint|--no-lint)
            SKIP_LINT=true
            shift
            ;;
        --vault)
            USE_VAULT=true
            shift
            ;;
        --no-vault)
            USE_VAULT=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PYTEST_ARGS...]"
            echo ""
            echo "Options:"
            echo "  --docker         Run tests inside Docker container"
            echo "  --coverage       Run with coverage report"
            echo "  --coverage-html  Run with HTML coverage report"
            echo "  --unit           Run unit tests only"
            echo "  --vault          Start Vault in ephemeral test mode (default)"
            echo "  --no-vault       Skip Vault startup (exclude integration tests)"
            echo "  --skip-lint      Skip code quality checks (ruff)"
            echo "  --cleanup-only   Clean environment and exit"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                              # Run all tests (incl. Vault integration)"
            echo "  $0 tests/test_config.py        # Run specific test file"
            echo "  $0 -k 'auth'                   # Run tests matching keyword"
            echo "  $0 -v                          # Run with verbose output"
            echo "  $0 --coverage                  # Run with coverage"
            echo "  $0 --docker                    # Run in Docker"
            echo "  $0 --no-vault                  # Skip Vault, run unit tests only"
            echo "  $0 --skip-lint                 # Skip linting, run tests only"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# =============================================================================
# MAIN EXECUTION
# =============================================================================

print_header

# Handle cleanup-only mode
if [ "$CLEANUP_ONLY" = true ]; then
    cleanup_environment
    exit 0
fi

# =============================================================================
# VAULT SETUP (if requested)
# =============================================================================

if [ "$USE_VAULT" = true ]; then
    start_vault_test_container
    
    # Set up trap to stop Vault on exit (success or failure)
    trap 'stop_vault_test_container' EXIT
fi

# =============================================================================
# CODE QUALITY CHECKS (RUFF)
# =============================================================================

if [ "$SKIP_LINT" = false ]; then
    echo -e "${BLUE}Running code quality checks (ruff)...${NC}"
    
    RUFF_CMD="ruff check src/ tests/"
    
    if [ "$USE_DOCKER" = true ]; then
        if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
            echo -e "${RED}Container ${CONTAINER_NAME} is not running for lint check.${NC}"
            exit 1
        fi
        docker exec "${CONTAINER_NAME}" bash -c "cd /home/${PROJECT_NAME} && source .venv/bin/activate && ${RUFF_CMD}"
        LINT_EXIT_CODE=$?
    else
        if [ "$USE_UV" = true ]; then
            uv run --group dev ${RUFF_CMD}
            LINT_EXIT_CODE=$?
        elif command -v ruff &> /dev/null; then
            ${RUFF_CMD}
            LINT_EXIT_CODE=$?
        else
            echo -e "${YELLOW}Warning: ruff not found, skipping lint checks${NC}"
            LINT_EXIT_CODE=0
        fi
    fi
    
    if [ $LINT_EXIT_CODE -ne 0 ]; then
        echo ""
        echo -e "${RED}=== Ruff checks failed! ===${NC}"
        echo -e "${YELLOW}Fix issues with: ruff check src/ tests/ --fix${NC}"
        echo -e "${YELLOW}Or skip lint with: $0 --skip-lint${NC}"
        exit $LINT_EXIT_CODE
    fi
    
    echo -e "${GREEN}Ruff checks passed!${NC}"
    echo ""
    
    # -------------------------------------------------------------------------
    # PYRIGHT TYPE CHECKING
    # -------------------------------------------------------------------------
    # Check if pyright is available (installed with: uv add "pyright[nodejs]")
    PYRIGHT_AVAILABLE=false
    if [ "$USE_UV" = true ]; then
        PYRIGHT_AVAILABLE=true
    elif command -v pyright &> /dev/null; then
        PYRIGHT_AVAILABLE=true
    elif [ -f "${VENV_DIR}/bin/pyright" ]; then
        PYRIGHT_AVAILABLE=true
    fi
    
    if [ "$PYRIGHT_AVAILABLE" = true ]; then
        echo -e "${BLUE}Running type checks (pyright)...${NC}"
        
        # Use python -m for reliability (venv/uv shebang wrappers can go stale)
        PYRIGHT_CMD="python -m pyright src/"
        
        if [ "$USE_DOCKER" = true ]; then
            docker exec "${CONTAINER_NAME}" bash -c "cd /home/${PROJECT_NAME} && source .venv/bin/activate && ${PYRIGHT_CMD}"
            TYPE_EXIT_CODE=$?
        else
            if [ "$USE_UV" = true ]; then
                uv run --group dev ${PYRIGHT_CMD}
                TYPE_EXIT_CODE=$?
            elif command -v pyright &> /dev/null; then
                ${PYRIGHT_CMD}
                TYPE_EXIT_CODE=$?
            else
                echo -e "${YELLOW}Warning: Cannot run pyright (uv not available)${NC}"
                TYPE_EXIT_CODE=0
            fi
        fi
        
        if [ $TYPE_EXIT_CODE -ne 0 ]; then
            echo ""
            echo -e "${RED}=== Type checks failed! ===${NC}"
            echo -e "${YELLOW}Or skip lint with: $0 --skip-lint${NC}"
            exit $TYPE_EXIT_CODE
        fi
        
        echo -e "${GREEN}Type checks passed!${NC}"
        echo ""
    else
        echo -e "${YELLOW}Skipping pyright type checks (pyright not installed)${NC}"
        echo -e "${YELLOW}Install with: uv add \"pyright[nodejs]\"${NC}"
        echo ""
    fi
fi

# =============================================================================
# PYTEST EXECUTION
# =============================================================================

# Build pytest command (use python -m pytest for reliable invocation
# even when venv shebangs point to stale paths)
PYTEST_CMD="python -m pytest"

# Add coverage if requested
COVERAGE_ARGS=""
if [ "$COVERAGE" = true ]; then
    COVERAGE_ARGS="--cov=${COVERAGE_SOURCE} --cov-report=term-missing"
    if [ "$COVERAGE_HTML" = true ]; then
        COVERAGE_ARGS="${COVERAGE_ARGS} --cov-report=html:htmlcov"
    fi
    echo -e "${BLUE}Coverage reporting enabled${NC}"
fi

# Add default test directory if no args provided
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=("${TEST_DIR}/")
fi

# Add verbose by default if not specified
if [[ ! " ${PYTEST_ARGS[*]} " =~ " -v " ]] && [[ ! " ${PYTEST_ARGS[*]} " =~ " -q " ]]; then
    PYTEST_CMD="${PYTEST_CMD} -v"
fi

# Construct full command
FULL_CMD="${PYTEST_CMD} ${PYTEST_ARGS[*]} ${COVERAGE_ARGS}"

# =============================================================================
# EXECUTION
# =============================================================================

if [ "$USE_DOCKER" = true ]; then
    # Run in Docker container
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${YELLOW}Container ${CONTAINER_NAME} is not running.${NC}"
        echo -e "${YELLOW}Starting container...${NC}"
        
        if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
            docker start "${CONTAINER_NAME}"
            sleep 2
        else
            echo -e "${RED}Container ${CONTAINER_NAME} does not exist.${NC}"
            echo "Run: ./scripts/run-dev.sh to create it"
            exit 1
        fi
    fi
    
    echo -e "${BLUE}Running tests in Docker container: ${CONTAINER_NAME}${NC}"
    echo "Command: ${FULL_CMD}"
    echo ""
    
    docker exec "${CONTAINER_NAME}" bash -c "cd /home/${PROJECT_NAME} && source .venv/bin/activate && ${FULL_CMD}"
    EXIT_CODE=$?
else
    # Run locally
    echo -e "${BLUE}Running tests locally${NC}"
    echo "Command: ${FULL_CMD}"
    echo ""
    
    if [ "$USE_UV" = true ]; then
        uv run ${FULL_CMD}
    else
        eval "${FULL_CMD}"
    fi
    EXIT_CODE=$?
fi

# =============================================================================
# RESULTS
# =============================================================================

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=== All tests passed! ===${NC}"
    if [ "$COVERAGE" = true ] && [ "$COVERAGE_HTML" = true ]; then
        echo -e "${BLUE}HTML coverage report: ${PROJECT_ROOT}/htmlcov/index.html${NC}"
    fi
else
    echo -e "${RED}=== Some tests failed (exit code: ${EXIT_CODE}) ===${NC}"
fi

exit $EXIT_CODE
