#!/bin/bash
# Shared GOFR Server Restart Script
# Restarts all servers in correct order: MCP → MCPO → Web
#
# Supports two modes:
#   --prod  : Run servers as Docker containers (works from host)
#   --dev   : Run servers as local Python processes (requires devcontainer with uv)
#
# This script is called from project-specific wrappers that set environment variables.
#
# Required environment variables:
#   GOFR_PROJECT_NAME    - Project name for display (e.g., "gofr-np", "gofr-dig")
#   GOFR_PROJECT_ROOT    - Project root directory
#   GOFR_LOGS_DIR        - Log directory for output files
#   GOFR_DATA_DIR        - Data directory (for display)
#   GOFR_ENV             - Environment: PROD or TEST
#   GOFR_MCP_PORT        - MCP server port
#   GOFR_MCPO_PORT       - MCPO wrapper port
#   GOFR_WEB_PORT        - Web server port
#
# Optional environment variables:
#   GOFR_MCP_HOST        - MCP server bind host (default: 0.0.0.0)
#   GOFR_MCPO_HOST       - MCPO wrapper bind host (default: 0.0.0.0)
#   GOFR_WEB_HOST        - Web server bind host (default: 0.0.0.0)
#   GOFR_NETWORK         - Network name (for display)
#   GOFR_DOCKER_DIR      - Docker directory containing docker-compose.yml
#   GOFR_MCP_EXTRA_ARGS  - Extra args for MCP server
#   GOFR_MCPO_EXTRA_ARGS - Extra args for MCPO wrapper
#   GOFR_WEB_EXTRA_ARGS  - Extra args for Web server
#
# Usage from project wrapper:
#   export GOFR_PROJECT_NAME="gofr-np"
#   export GOFR_PROJECT_ROOT="/path/to/gofr-np"
#   # ... set other vars ...
#   source /path/to/gofr-common/scripts/restart_servers.sh "$@"

set -e

# Validate required environment variables
required_vars=(
    "GOFR_PROJECT_NAME"
    "GOFR_PROJECT_ROOT"
    "GOFR_LOGS_DIR"
    "GOFR_DATA_DIR"
    "GOFR_ENV"
    "GOFR_MCP_PORT"
    "GOFR_MCPO_PORT"
    "GOFR_WEB_PORT"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
done

# Default hosts
GOFR_MCP_HOST="${GOFR_MCP_HOST:-0.0.0.0}"
GOFR_MCPO_HOST="${GOFR_MCPO_HOST:-0.0.0.0}"
GOFR_WEB_HOST="${GOFR_WEB_HOST:-0.0.0.0}"
GOFR_DOCKER_DIR="${GOFR_DOCKER_DIR:-$GOFR_PROJECT_ROOT/docker}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse command line arguments
KILL_ALL=false
RUN_MODE=""  # "prod" or "dev"
while [[ $# -gt 0 ]]; do
    case $1 in
        --kill-all|--stop)
            KILL_ALL=true
            shift
            ;;
        --prod|--docker)
            RUN_MODE="prod"
            shift
            ;;
        --dev|--local)
            RUN_MODE="dev"
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "MODE OPTIONS (one required):"
            echo "    --prod, --docker    Run servers as Docker containers"
            echo "    --dev, --local      Run servers as local Python processes (needs uv)"
            echo ""
            echo "OTHER OPTIONS:"
            echo "    --kill-all, --stop  Stop all servers without restarting"
            echo "    --help              Show this help message"
            echo ""
            echo "REQUIREMENTS:"
            echo "  - Docker must be running (for --prod mode)"
            echo "  - uv must be installed (for --dev mode)"
            echo "  - Infrastructure must be running (Vault, Neo4j, ChromaDB)"
            echo "  - Secrets must be available (load via auth_env.sh for --dev)"
            echo ""
            echo "This is a shared script called by project-specific wrappers."
            echo "Use project wrapper instead: scripts/manage_servers.sh"
            echo "Environment variables should be set by the project wrapper script."
            exit 0
            ;;
        *)
            # Unknown options are ignored (may be handled by wrapper)
            shift
            ;;
    esac
done

# Require explicit mode selection
if [ -z "$RUN_MODE" ] && [ "$KILL_ALL" = false ]; then
    echo -e "${RED}ERROR: Must specify --prod or --dev mode${NC}"
    echo ""
    echo "Usage:"
    echo "  $0 --prod     # Run servers as Docker containers"
    echo "  $0 --dev      # Run servers as local Python (requires devcontainer)"
    echo "  $0 --stop     # Stop all servers"
    exit 1
fi

echo "======================================================================="
echo "$GOFR_PROJECT_NAME Server Restart Script"
echo "Environment: $GOFR_ENV"
echo "Mode: $([ "$RUN_MODE" = "prod" ] && echo "Docker containers" || echo "Local Python")"
echo "Data Root: $GOFR_DATA_DIR"
if [ -n "$GOFR_NETWORK" ]; then
    echo "Network: $GOFR_NETWORK"
fi
echo "======================================================================="

# Function to kill process and wait for it to die
kill_and_wait() {
    local pattern=$1
    local name=$2
    local pids=$(pgrep -f "$pattern" 2>/dev/null || echo "")
    
    if [ -z "$pids" ]; then
        echo "  - No $name running"
        return 0
    fi
    
    echo "  Killing $name (PIDs: $pids)..."
    pkill -9 -f "$pattern" 2>/dev/null || true
    
    # Wait for processes to die (max 10 seconds)
    for i in {1..20}; do
        if ! pgrep -f "$pattern" >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} $name stopped"
            return 0
        fi
        sleep 0.5
    done
    
    echo -e "  ${YELLOW}⚠${NC} Warning: $name may still be running"
    return 1
}

# Function to stop Docker containers
stop_docker_servers() {
    echo "  Stopping Docker containers..."
    cd "$GOFR_DOCKER_DIR"
    docker compose stop mcp mcpo web 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Docker containers stopped"
    cd "$GOFR_PROJECT_ROOT"
}

# Function to verify server is responding
verify_server() {
    local port=$1
    local name=$2
    local endpoint=$3
    local max_attempts=${4:-30}
    local attempt=0
    
    echo "  Waiting for $name to be ready..."
    while [ $attempt -lt $max_attempts ]; do
        # For MCP server, use proper headers for HTTP streamable transport
        if [[ "$name" == *"MCP"* && "$endpoint" == "/mcp"* ]]; then
            # MCP HTTP Streamable requires both Accept headers
            if curl -s -m 2 -H "Accept: application/json, text/event-stream" \
                   -H "Content-Type: application/json" \
                   -d '{"jsonrpc":"2.0","method":"ping","id":1}' \
                   "http://localhost:${port}${endpoint}" 2>&1 | grep -q "jsonrpc"; then
                echo -e "  ${GREEN}✓${NC} $name ready on port $port"
                return 0
            fi
        else
            if curl -s -m 2 "http://localhost:${port}${endpoint}" >/dev/null 2>&1; then
                echo -e "  ${GREEN}✓${NC} $name ready on port $port"
                return 0
            fi
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    
    echo -e "  ${RED}✗${NC} $name NOT responding after ${max_attempts}s"
    return 1
}

# Function to wait for Docker container to be healthy
wait_for_container() {
    local container=$1
    local name=$2
    local max_wait=${3:-60}
    local elapsed=0
    
    echo -ne "  Waiting for $name container..."
    while [ $elapsed -lt $max_wait ]; do
        local health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
        case "$health" in
            healthy)
                echo -e " ${GREEN}✓${NC}"
                return 0
                ;;
            unhealthy)
                echo -e " ${RED}✗ unhealthy${NC}"
                return 1
                ;;
            not_found)
                # Container may not have health check, check if running
                local state=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "not_found")
                if [ "$state" = "running" ]; then
                    echo -e " ${GREEN}✓${NC} (running)"
                    return 0
                fi
                ;;
        esac
        sleep 2
        elapsed=$((elapsed + 2))
        printf "."
    done
    echo -e " ${RED}✗ timeout${NC}"
    return 1
}

# Kill existing processes (for both modes, stop local processes)
echo ""
echo "Step 1: Stopping existing servers..."
echo "-----------------------------------------------------------------------"

# Stop Docker containers if they exist
if command -v docker &> /dev/null; then
    stop_docker_servers
fi

# Kill local processes in reverse order (Web, MCPO, MCP)
kill_and_wait "app.main_web" "Web server"
kill_and_wait "mcpo --port\|mcpo" "MCPO wrapper"
kill_and_wait "app.main_mcpo" "MCPO wrapper process"
kill_and_wait "app.main_mcp" "MCP server"

# Wait for ports to be released
echo ""
echo "Waiting for ports to be released..."
sleep 2

# Check if --kill-all flag is set
if [ "$KILL_ALL" = true ]; then
    echo ""
    echo "Kill-all mode: Exiting without restart"
    echo "======================================================================="
    exit 0
fi

# =============================================================================
# PROD MODE: Start servers as Docker containers
# =============================================================================
if [ "$RUN_MODE" = "prod" ]; then
    
    # Verify docker-compose.yml exists
    if [ ! -f "$GOFR_DOCKER_DIR/docker-compose.yml" ]; then
        echo -e "${RED}ERROR: docker-compose.yml not found at $GOFR_DOCKER_DIR${NC}"
        exit 1
    fi
    
    echo ""
    echo "Step 2: Starting servers as Docker containers..."
    echo "-----------------------------------------------------------------------"
    
    cd "$GOFR_DOCKER_DIR"
    
    # Start the server containers (infra should already be running)
    docker compose up -d mcp mcpo web
    
    echo ""
    echo "Step 3: Waiting for containers to be ready..."
    echo "-----------------------------------------------------------------------"
    
    # Wait for containers to be healthy/running
    wait_for_container "${GOFR_PROJECT_NAME}-mcp" "MCP Server" 60
    wait_for_container "${GOFR_PROJECT_NAME}-mcpo" "MCPO Wrapper" 30
    wait_for_container "${GOFR_PROJECT_NAME}-web" "Web Server" 30
    
    # Verify servers are responding
    echo ""
    echo "Step 4: Verifying servers are responding..."
    echo "-----------------------------------------------------------------------"
    
    verify_server $GOFR_MCP_PORT "MCP Server" "/mcp" 30 || {
        echo -e "${RED}ERROR: MCP server not responding${NC}"
        docker compose logs mcp | tail -20
        exit 1
    }
    
    verify_server $GOFR_MCPO_PORT "MCPO Wrapper" "/openapi.json" 15 || {
        echo -e "${RED}ERROR: MCPO wrapper not responding${NC}"
        docker compose logs mcpo | tail -20
        exit 1
    }
    
    verify_server $GOFR_WEB_PORT "Web Server" "/ping" 15 || {
        echo -e "${RED}ERROR: Web server not responding${NC}"
        docker compose logs web | tail -20
        exit 1
    }
    
    cd "$GOFR_PROJECT_ROOT"
    
    # Summary
    echo ""
    echo "======================================================================="
    echo -e "${GREEN}All servers started successfully (Docker containers)!${NC}"
    echo "======================================================================="
    echo ""
    echo "Server URLs:"
    echo "  MCP:  http://localhost:$GOFR_MCP_PORT/mcp/"
    echo "  MCPO: http://localhost:$GOFR_MCPO_PORT/openapi.json"
    echo "  Web:  http://localhost:$GOFR_WEB_PORT/"
    echo ""
    echo "View logs:"
    echo "  docker compose -f $GOFR_DOCKER_DIR/docker-compose.yml logs -f mcp mcpo web"
    echo ""
    exit 0
fi

# =============================================================================
# DEV MODE: Start servers as local Python processes
# =============================================================================

# Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}ERROR: 'uv' not found. Dev mode requires running inside the devcontainer.${NC}"
    echo "Either:"
    echo "  1. Run from VS Code terminal (inside devcontainer)"
    echo "  2. Use --prod mode to run Docker containers instead"
    exit 1
fi

# Create logs directory if it doesn't exist
mkdir -p "$GOFR_LOGS_DIR"

# Start MCP server
echo ""
echo "Step 2: Starting MCP server ($GOFR_MCP_HOST:$GOFR_MCP_PORT)..."
echo "-----------------------------------------------------------------------"

# Conditional authentication: check for JWT credentials
MCP_AUTH_ARGS=""
if [ -n "$GOFR_JWT_SECRET" ] && [ -n "$GOFR_TOKEN_STORE" ]; then
    MCP_AUTH_ARGS="--jwt-secret $GOFR_JWT_SECRET --token-store $GOFR_TOKEN_STORE"
    echo "  Authentication: ENABLED (JWT)"
else
    MCP_AUTH_ARGS="--no-auth"
    echo "  Authentication: DISABLED (--no-auth)"
fi

cd "$GOFR_PROJECT_ROOT"
nohup uv run python -m app.main_mcp \
    $MCP_AUTH_ARGS \
    --host $GOFR_MCP_HOST \
    --port $GOFR_MCP_PORT \
    $GOFR_MCP_EXTRA_ARGS \
    > "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcp.log" 2>&1 &

MCP_PID=$!
echo "  MCP server starting (PID: $MCP_PID)"
echo "  Log: $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcp.log"

# Verify MCP is operational (HTTP Streamable transport)
if ! verify_server $GOFR_MCP_PORT "MCP Server" "/mcp"; then
    echo -e "${RED}ERROR: MCP server failed to start${NC}"
    tail -20 "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcp.log"
    exit 1
fi

# Start MCPO wrapper
echo ""
echo "Step 3: Starting MCPO wrapper ($GOFR_MCPO_HOST:$GOFR_MCPO_PORT)..."
echo "-----------------------------------------------------------------------"

nohup uv run python -m app.main_mcpo \
    --mcp-host $GOFR_MCP_HOST --mcp-port $GOFR_MCP_PORT \
    --mcpo-host $GOFR_MCPO_HOST --mcpo-port $GOFR_MCPO_PORT \
    $GOFR_MCPO_EXTRA_ARGS \
    > "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcpo.log" 2>&1 &

MCPO_PID=$!
echo "  MCPO wrapper starting (PID: $MCPO_PID)"
echo "  Log: $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcpo.log"

# Verify MCPO is operational
if ! verify_server $GOFR_MCPO_PORT "MCPO Wrapper" "/openapi.json" 15; then
    echo -e "${RED}ERROR: MCPO wrapper failed to start${NC}"
    tail -20 "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcpo.log"
    exit 1
fi

# Start Web server
echo ""
echo "Step 4: Starting Web server ($GOFR_WEB_HOST:$GOFR_WEB_PORT)..."
echo "-----------------------------------------------------------------------"

# Add --no-auth for TEST environment
WEB_AUTH_FLAG=""
if [ "$GOFR_ENV" = "TEST" ]; then
    WEB_AUTH_FLAG="--no-auth"
fi

nohup uv run python -m app.main_web \
    $WEB_AUTH_FLAG \
    --host $GOFR_WEB_HOST \
    --port $GOFR_WEB_PORT \
    $GOFR_WEB_EXTRA_ARGS \
    > "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_web.log" 2>&1 &

WEB_PID=$!
echo "  Web server starting (PID: $WEB_PID)"
echo "  Log: $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_web.log"

# Verify Web server is operational
if ! verify_server $GOFR_WEB_PORT "Web Server" "/ping" 15; then
    echo -e "${RED}ERROR: Web server failed to start${NC}"
    tail -20 "$GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_web.log"
    exit 1
fi

# Summary
echo ""
echo "======================================================================="
echo -e "${GREEN}All servers started successfully (local Python)!${NC}"
echo "======================================================================="
echo ""
echo "Server URLs:"
echo "  MCP:  http://localhost:$GOFR_MCP_PORT/mcp/"
echo "  MCPO: http://localhost:$GOFR_MCPO_PORT/openapi.json"
echo "  Web:  http://localhost:$GOFR_WEB_PORT/"
echo ""
echo "Logs:"
echo "  MCP:  $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcp.log"
echo "  MCPO: $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_mcpo.log"
echo "  Web:  $GOFR_LOGS_DIR/${GOFR_PROJECT_NAME}_web.log"
echo ""
