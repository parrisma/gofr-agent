#!/bin/bash
# =============================================================================
# GOFR Tools Environment Dump Script
# =============================================================================
# Dumps the complete tools stack environment state including:
# - OpenWebUI and n8n service URLs
# - Container status
# - Volume information
# - Port configuration
# - Network connectivity
#
# Usage:
#   ./lib/gofr-common/scripts/dump_tools_environment.sh [OPTIONS]
#
# Options:
#   --help, -h           Show this help message
# =============================================================================

set -euo pipefail

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${COMMON_ROOT}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            cat << 'EOF'
GOFR Tools Environment Dump Script

Usage:
  ./lib/gofr-common/scripts/dump_tools_environment.sh [OPTIONS]

Options:
    --help, -h           Show this help message

Examples:
  # Dump tools environment
  ./lib/gofr-common/scripts/dump_tools_environment.sh
EOF
            exit 0
            ;;
        *)
            echo -e "${RED}ERROR:${NC} Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
    esac
done

# Load port configuration
GOFR_PORTS_ENV="${COMMON_ROOT}/config/gofr_ports.env"
if [[ -f "${GOFR_PORTS_ENV}" ]]; then
    set -a
    source "${GOFR_PORTS_ENV}"
    set +a
fi

# Set defaults
GOFR_OPENWEBUI_PORT=${GOFR_OPENWEBUI_PORT:-8083}
GOFR_N8N_PORT=${GOFR_N8N_PORT:-8084}

# Helper functions
section_header() {
    echo ""
    echo -e "${BOLD}$1${NC}"
    echo -e "${CYAN}    Source: $2${NC}"
    echo ""
}

show_value() {
    local label="$1"
    local value="$2"
    printf "  %-30s %s\n" "$label:" "$value"
}

check_container_running() {
    local container_name="$1"
    if docker ps --filter "name=${container_name}" --filter "status=running" -q | grep -q .; then
        echo "✓ Running"
    else
        echo "✗ Not Running"
    fi
}

get_container_status() {
    local container_name="$1"
    docker ps -a --filter "name=${container_name}" --format "{{.Status}}" 2>/dev/null || echo "Not Found"
}

# Main dump
echo ""
echo -e "${BOLD}=======================================================================${NC}"
echo -e "${BOLD}                    GOFR TOOLS ENVIRONMENT DUMP${NC}"
echo -e "${BOLD}=======================================================================${NC}"
echo ""
echo -e "  Timestamp:                     $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo -e "  Common Root:                   ${COMMON_ROOT}"
echo -e "  Project Root:                  ${PROJECT_ROOT}"
echo ""

# Service Ports & URLs
section_header "=== Service Ports & URLs ===" "lib/gofr-common/config/gofr_ports.env"

show_value "OpenWebUI Port" "${GOFR_OPENWEBUI_PORT}"
show_value "n8n Port" "${GOFR_N8N_PORT}"
show_value "" ""
show_value "OpenWebUI URL" "http://localhost:${GOFR_OPENWEBUI_PORT}"
show_value "n8n URL" "http://localhost:${GOFR_N8N_PORT}"

# Container Status
section_header "=== Container Status ===" "docker ps"

OPENWEBUI_STATUS=$(get_container_status "gofr-openwebui")
N8N_STATUS=$(get_container_status "gofr-n8n")

show_value "gofr-openwebui" "${OPENWEBUI_STATUS}"
show_value "gofr-n8n" "${N8N_STATUS}"

# Detailed container information
if docker ps -a --filter "name=gofr-openwebui\|gofr-n8n" -q | grep -q .; then
    echo ""
    echo -e "${CYAN}Detailed Container Info:${NC}"
    echo ""
    docker ps -a --filter "name=gofr-openwebui" --filter "name=gofr-n8n" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
fi

# Docker Images
section_header "=== Docker Images ===" "docker images"

if docker images --filter "reference=gofr-openwebui:prod" -q | grep -q .; then
    OPENWEBUI_IMAGE=$(docker images gofr-openwebui:prod --format "{{.Repository}}:{{.Tag}} ({{.Size}})")
    show_value "OpenWebUI Image" "${OPENWEBUI_IMAGE}"
else
    show_value "OpenWebUI Image" "Not Built"
fi

if docker images --filter "reference=gofr-n8n:prod" -q | grep -q .; then
    N8N_IMAGE=$(docker images gofr-n8n:prod --format "{{.Repository}}:{{.Tag}} ({{.Size}})")
    show_value "n8n Image" "${N8N_IMAGE}"
else
    show_value "n8n Image" "Not Built"
fi

# Docker Volumes
section_header "=== Docker Volumes ===" "docker volume ls"

echo -e "${CYAN}Tools Volumes:${NC}"
docker volume ls --filter "name=gofr-openwebui\|gofr-n8n" --format "table {{.Driver}}\t{{.Name}}" 2>/dev/null || echo "  No volumes found"

# Volume sizes if volumes exist
if docker volume ls --filter "name=gofr-openwebui-data" -q | grep -q .; then
    echo ""
    echo -e "${CYAN}Volume Sizes:${NC}"
    for vol in gofr-openwebui-data gofr-n8n-data gofr-n8n-logs; do
        if docker volume inspect "$vol" >/dev/null 2>&1; then
            VOL_PATH=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null)
            if [[ -n "$VOL_PATH" ]]; then
                VOL_SIZE=$(sudo du -sh "$VOL_PATH" 2>/dev/null | cut -f1 || echo "N/A")
                show_value "  $vol" "$VOL_SIZE"
            fi
        fi
    done
fi

# Network Configuration
section_header "=== Network Configuration ===" "docker network inspect gofr-net"

if docker network inspect gofr-net >/dev/null 2>&1; then
    show_value "Network Name" "gofr-net"
    show_value "Network Driver" "bridge"
    
    # Check if containers are connected
    OPENWEBUI_CONNECTED=$(docker network inspect gofr-net --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -o "gofr-openwebui" || echo "")
    N8N_CONNECTED=$(docker network inspect gofr-net --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -o "gofr-n8n" || echo "")
    
    if [[ -n "$OPENWEBUI_CONNECTED" ]]; then
        show_value "OpenWebUI Connected" "✓ Yes"
    else
        show_value "OpenWebUI Connected" "✗ No"
    fi
    
    if [[ -n "$N8N_CONNECTED" ]]; then
        show_value "n8n Connected" "✓ Yes"
    else
        show_value "n8n Connected" "✗ No"
    fi
else
    show_value "Network Status" "gofr-net not found"
fi

# Integration Points
section_header "=== Integration Points ===" "docker network inspect gofr-net"

show_value "MCPO Endpoint (OpenWebUI)" "http://gofr-mcpo:8081"
show_value "MCP Endpoint (n8n)" "http://gofr-iq-mcp:8080"
show_value "Web Endpoint (n8n)" "http://gofr-iq-web:8082"
show_value "Vault Endpoint" "http://gofr-vault:8201"

# Health Checks
section_header "=== Health Checks ===" "curl"

# Detect if we're in a container
if [ -f /.dockerenv ]; then
    OPENWEBUI_HOST="gofr-openwebui"
    OPENWEBUI_PORT="8080"
    N8N_HOST="gofr-n8n"
    N8N_PORT="5678"
else
    OPENWEBUI_HOST="localhost"
    OPENWEBUI_PORT="${GOFR_OPENWEBUI_PORT}"
    N8N_HOST="localhost"
    N8N_PORT="${GOFR_N8N_PORT}"
fi

if docker ps --filter "name=gofr-openwebui" --filter "status=running" -q | grep -q .; then
    OPENWEBUI_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://${OPENWEBUI_HOST}:${OPENWEBUI_PORT}/health" 2>/dev/null || echo "N/A")
    if [[ "$OPENWEBUI_HEALTH" == "200" ]]; then
        show_value "OpenWebUI Health" "✓ Healthy (HTTP 200)"
    else
        show_value "OpenWebUI Health" "✗ Unhealthy (HTTP ${OPENWEBUI_HEALTH})"
    fi
else
    show_value "OpenWebUI Health" "Container not running"
fi

if docker ps --filter "name=gofr-n8n" --filter "status=running" -q | grep -q .; then
    N8N_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://${N8N_HOST}:${N8N_PORT}/healthz" 2>/dev/null || echo "N/A")
    if [[ "$N8N_HEALTH" == "200" ]]; then
        show_value "n8n Health" "✓ Healthy (HTTP 200)"
    else
        show_value "n8n Health" "✗ Unhealthy (HTTP ${N8N_HEALTH})"
    fi
else
    show_value "n8n Health" "Container not running"
fi

# Configuration Files
section_header "=== Configuration Files ===" "stat (filesystem)"

show_config_file() {
    local label="$1"
    local path="$2"
    if [[ -f "$path" ]]; then
        local size=$(stat -c %s "$path" 2>/dev/null || stat -f %z "$path" 2>/dev/null || echo "0")
        local modified=$(stat -c %y "$path" 2>/dev/null | cut -d'.' -f1 || stat -f "%Sm" "$path" 2>/dev/null || echo "unknown")
        printf "  %-30s %s (%s bytes, modified: %s)\n" "$label:" "$path" "$size" "$modified"
    else
        printf "  %-30s %s (missing)\n" "$label:" "$path"
    fi
}

show_config_file "Ports Configuration" "${COMMON_ROOT}/config/gofr_ports.env"
show_config_file "Docker Compose" "${COMMON_ROOT}/docker/docker-compose-tools.yml"
show_config_file "Start Script" "${COMMON_ROOT}/docker/start-tools-prod.sh"
show_config_file "OpenWebUI Dockerfile" "${COMMON_ROOT}/docker/Dockerfile.openwebui.prod"
show_config_file "n8n Dockerfile" "${COMMON_ROOT}/docker/Dockerfile.n8n.prod"

# Summary
section_header "=== Summary ===" "health checks"

ALL_HEALTHY=true

# Check OpenWebUI
if [[ "$OPENWEBUI_STATUS" =~ "Up" ]] && [[ "$OPENWEBUI_STATUS" =~ "healthy" ]]; then
    echo -e "  ${GREEN}✓${NC} OpenWebUI is running and healthy"
else
    echo -e "  ${RED}✗${NC} OpenWebUI is not healthy"
    ALL_HEALTHY=false
fi

# Check n8n
if [[ "$N8N_STATUS" =~ "Up" ]] && [[ "$N8N_STATUS" =~ "healthy" ]]; then
    echo -e "  ${GREEN}✓${NC} n8n is running and healthy"
else
    echo -e "  ${RED}✗${NC} n8n is not healthy"
    ALL_HEALTHY=false
fi

echo ""
if [[ "$ALL_HEALTHY" == true ]]; then
    echo -e "${GREEN}✓ All tools services are healthy${NC}"
else
    echo -e "${YELLOW}⚠ Some tools services need attention${NC}"
fi

echo ""
echo -e "${BOLD}=======================================================================${NC}"
echo -e "Environment dump complete."
echo -e "${BOLD}=======================================================================${NC}"
echo ""
