#!/bin/bash
# =============================================================================
# GOFR Tools Production Start Script
# =============================================================================
# Single-command startup for OpenWebUI and n8n tools stack.
#
# Usage:
#   ./lib/gofr-common/docker/start-tools-prod.sh              # Normal start
#   ./lib/gofr-common/docker/start-tools-prod.sh --reset      # Reset volumes
#
# This script:
# 1. Sources port configuration
# 2. Generates encryption keys (if needed)
# 3. Loads secrets from Vault (if available)
# 4. Starts OpenWebUI and n8n services
# 5. Ensures gofr-net network exists
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$COMMON_ROOT/../.." && pwd)"
PORTS_FILE="${COMMON_ROOT}/config/gofr_ports.env"
SECRETS_DIR="${PROJECT_ROOT}/secrets"

# Parse arguments
RESET_ALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reset)
            RESET_ALL=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--reset]"
            echo ""
            echo "Options:"
            echo "  --reset          Wipe all volumes and start fresh"
            echo ""
            echo "REQUIREMENTS:"
            echo "  - Docker must be installed and running"
            echo "  - gofr_ports.env must exist (run scripts/generate_envs.sh first)"
            echo "  - Vault should be running for OpenRouter API key (optional)"
            echo ""
            echo "SERVICES:"
            echo "  - OpenWebUI: LLM Chat Interface (port ${GOFR_OPENWEBUI_PORT:-8083})"
            echo "  - n8n: Workflow Automation (port ${GOFR_N8N_PORT:-8084})"
            echo ""
            echo "POST-STARTUP:"
            echo "  - OpenWebUI: http://localhost:${GOFR_OPENWEBUI_PORT:-8083}"
            echo "  - n8n: http://localhost:${GOFR_N8N_PORT:-8084}"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo ""
echo "======================================================================="
echo "🚀 GOFR Tools Stack Startup (OpenWebUI + n8n)"
echo "======================================================================="

# Step 0: Reset if requested
if [ "$RESET_ALL" = true ]; then
    log_warn "RESET MODE: This will destroy all data!"
    read -p "Are you sure? Type 'yes' to continue: " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Aborted."
        exit 0
    fi
    
    log_info "Stopping gofr-tools containers..."
    cd "$SCRIPT_DIR"
    docker compose down 2>/dev/null || true
    
    log_info "Removing docker volumes..."
    docker volume rm gofr-openwebui-data gofr-n8n-data gofr-n8n-logs 2>/dev/null || true
    
    log_success "Reset complete - environment is clean"
fi

# Step 1: Source port configuration
log_info "Loading port configuration..."
if [ ! -f "$PORTS_FILE" ]; then
    log_error "Port config not found: $PORTS_FILE"
    log_info "Run: ./scripts/generate_envs.sh first"
    exit 1
fi
set -a
source "$PORTS_FILE"
set +a
log_success "Ports loaded"

# Step 2: Ensure gofr-net network exists
log_info "Ensuring gofr-net network exists..."
if ! docker network inspect gofr-net >/dev/null 2>&1; then
    log_info "Creating gofr-net network..."
    docker network create gofr-net
    log_success "Network created"
else
    log_success "Network already exists"
fi

# Step 3: Build custom images if they don't exist
log_info "Checking for custom images..."

if ! docker image inspect gofr-openwebui:prod >/dev/null 2>&1; then
    log_info "Building gofr-openwebui:prod image..."
    docker build -f "${COMMON_ROOT}/docker/Dockerfile.openwebui.prod" \
        -t gofr-openwebui:prod \
        "${COMMON_ROOT}/docker"
    log_success "OpenWebUI image built"
else
    log_info "OpenWebUI image already exists"
fi

if ! docker image inspect gofr-n8n:prod >/dev/null 2>&1; then
    log_info "Building gofr-n8n:prod image..."
    docker build -f "${COMMON_ROOT}/docker/Dockerfile.n8n.prod" \
        -t gofr-n8n:prod \
        "${COMMON_ROOT}/docker"
    log_success "n8n image built"
else
    log_info "n8n image already exists"
fi

# Step 4: Generate encryption keys if they don't exist
log_info "Checking encryption keys..."

TOOLS_ENV_FILE="${SECRETS_DIR}/tools-secrets.env"

# Try to load existing keys first
if [ -f "$TOOLS_ENV_FILE" ]; then
    log_info "Loading secrets from $TOOLS_ENV_FILE"
    set -a
    source "$TOOLS_ENV_FILE"
    set +a
fi

KEYS_UPDATED=false

# WebUI Secret Key
if [ -z "${WEBUI_SECRET_KEY:-}" ]; then
    log_info "Generating WebUI secret key..."
    export WEBUI_SECRET_KEY=$(openssl rand -hex 32)
    KEYS_UPDATED=true
    log_success "WebUI secret key generated"
else
    log_info "Using existing WebUI secret key"
fi

# n8n Encryption Key
if [ -z "${N8N_ENCRYPTION_KEY:-}" ]; then
    log_info "Generating n8n encryption key..."
    export N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)
    KEYS_UPDATED=true
    log_success "n8n encryption key generated"
else
    log_info "Using existing n8n encryption key"
fi

# Save keys if new ones were generated
if [ "$KEYS_UPDATED" = true ]; then
    log_info "Saving secrets to $TOOLS_ENV_FILE..."
    mkdir -p "$SECRETS_DIR"
    
    # Update or append keys
    # Note: This is a simple append/rewrite logic. For production key rotation, use Vault.
    cat > "$TOOLS_ENV_FILE" <<EOF
# GOFR Tools Stack Secrets
# Generated on $(date)
WEBUI_SECRET_KEY=$WEBUI_SECRET_KEY
N8N_ENCRYPTION_KEY=$N8N_ENCRYPTION_KEY
EOF
    chmod 600 "$TOOLS_ENV_FILE"
    log_success "Secrets saved"
fi

# Step 5: Try to load OpenRouter API key from Vault
log_info "Checking for OpenRouter API key..."
OPENROUTER_API_KEY=""

if [ -f "$SECRETS_DIR/vault_root_token" ] && docker ps --filter "name=gofr-vault" --filter "status=running" -q | grep -q .; then
    log_info "Vault is running, attempting to load OpenRouter API key..."
    VAULT_TOKEN=$(cat "$SECRETS_DIR/vault_root_token")
    VAULT_ADDR="http://localhost:${GOFR_VAULT_PORT:-8201}"
    
    OPENROUTER_API_KEY=$(docker exec -e VAULT_ADDR="${VAULT_ADDR}" -e VAULT_TOKEN="${VAULT_TOKEN}" \
        gofr-vault vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null || echo "")
    
    if [ -n "$OPENROUTER_API_KEY" ]; then
        export OPENROUTER_API_KEY
        log_success "OpenRouter API key loaded from Vault"
    else
        log_warn "OpenRouter API key not found in Vault (OpenWebUI will need manual configuration)"
    fi
else
    log_warn "Vault not running or not initialized (OpenWebUI will need manual configuration)"
fi

# Step 6: Start all services
log_info "Starting OpenWebUI and n8n services..."
cd "$SCRIPT_DIR"
docker compose -f docker-compose-tools.yml down 2>/dev/null || true
docker compose -f docker-compose-tools.yml up -d

echo ""
log_success "Waiting for services to become healthy..."
sleep 5

echo ""
echo "=== Container Status ==="
echo ""
docker ps --filter "name=gofr-openwebui\|gofr-n8n" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "======================================================================="
echo "✅ GOFR Tools Stack Ready"
echo "======================================================================="
echo ""
echo "Services:"
echo "  OpenWebUI:  http://localhost:${GOFR_OPENWEBUI_PORT:-8083}"
echo "  n8n:        http://localhost:${GOFR_N8N_PORT:-8084}"
echo ""
echo "Integration:"
echo "  - Both services are on the 'gofr-net' network"
echo "  - OpenWebUI can connect to MCPO at: http://gofr-mcpo:${GOFR_IQ_MCPO_PORT:-8081}"
echo "  - n8n can connect to gofr services via their container names"
echo ""
echo "Next Steps:"
echo "  1. Access OpenWebUI and complete initial setup"
echo "  2. Access n8n and complete initial setup"
echo "  3. Configure integrations as needed (manual)"
echo ""
echo "======================================================================="
