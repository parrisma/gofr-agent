#!/bin/bash
# =============================================================================
# GOFR Swarm Deployment Script
# =============================================================================
# Deploys the complete GOFR stack to Docker Swarm
#
# Usage:
#   ./deploy-swarm.sh              # Deploy with defaults
#   ./deploy-swarm.sh --build      # Build images first, then deploy
#   ./deploy-swarm.sh --secrets    # Create secrets first, then deploy
#   ./deploy-swarm.sh --full       # Build, create secrets, then deploy
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Fail-fast validation for required secrets (no placeholders allowed)
PLACEHOLDER_VALUES=("changeme" "change-this-encryption-key" "gofr-neo4j-password" "not-configured")
require_env() {
    local name="$1"
    local value="${!name:-}"

    if [ -z "$value" ]; then
        log_error "$name is required and must be provided via environment or Vault"
        exit 1
    fi

    for placeholder in "${PLACEHOLDER_VALUES[@]}"; do
        if [ "$value" = "$placeholder" ]; then
            log_error "$name uses placeholder value ($placeholder); provide a real secret."
            exit 1
        fi
    done
}

# Parse arguments
BUILD_IMAGES=false
CREATE_SECRETS=false

for arg in "$@"; do
    case $arg in
        --build)
            BUILD_IMAGES=true
            ;;
        --secrets)
            CREATE_SECRETS=true
            ;;
        --full)
            BUILD_IMAGES=true
            CREATE_SECRETS=true
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build     Build all Docker images before deploying"
            echo "  --secrets   Create Docker secrets before deploying"
            echo "  --full      Build images and create secrets before deploying"
            echo "  --help      Show this help message"
            exit 0
            ;;
    esac
done

# Check if Docker Swarm is initialized
log_info "Checking Docker Swarm status..."
if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
    log_warn "Docker Swarm is not initialized. Initializing..."
    docker swarm init
    log_success "Docker Swarm initialized"
fi

# Build images if requested
if [ "$BUILD_IMAGES" = true ]; then
    log_info "Building all GOFR images..."
    
    # Infrastructure
    log_info "Building infrastructure images..."
    cd "$SCRIPT_DIR/infra/neo4j" && ./build.sh
    cd "$SCRIPT_DIR/infra/chroma" && ./build.sh
    
    # GOFR services
    for project in plot doc dig iq np; do
        PROJECT_DIR="$DEVROOT/gofr-$project"
        if [ -f "$PROJECT_DIR/docker/build-prod.sh" ]; then
            log_info "Building gofr-$project..."
            cd "$PROJECT_DIR" && ./docker/build-prod.sh
        else
            log_warn "Build script not found for gofr-$project"
        fi
    done
    
    # Tools
    log_info "Building tool images..."
    cd "$SCRIPT_DIR" && ./build-n8n.sh
    cd "$SCRIPT_DIR" && ./build-openwebui.sh
    
    # Backup
    log_info "Building backup image..."
    cd "$DEVROOT/gofr-common"
    docker build -f docker/backup/Dockerfile -t gofr-backup:latest .
    
    log_success "All images built"
fi

# Create secrets if requested
if [ "$CREATE_SECRETS" = true ]; then
    log_info "Creating Docker secrets..."

    require_env JWT_SECRET
    require_env NEO4J_PASSWORD
    require_env N8N_ENCRYPTION_KEY

    # JWT Secret
    if ! docker secret inspect jwt_secret >/dev/null 2>&1; then
        echo "$JWT_SECRET" | docker secret create jwt_secret -
        log_success "Created jwt_secret"
    else
        log_info "jwt_secret already exists"
    fi
    
    # Neo4j Password
    if ! docker secret inspect neo4j_password >/dev/null 2>&1; then
        echo "$NEO4J_PASSWORD" | docker secret create neo4j_password -
        log_success "Created neo4j_password"
    else
        log_info "neo4j_password already exists"
    fi
    
    # N8N Encryption Key
    if ! docker secret inspect n8n_encryption_key >/dev/null 2>&1; then
        echo "$N8N_ENCRYPTION_KEY" | docker secret create n8n_encryption_key -
        log_success "Created n8n_encryption_key"
    else
        log_info "n8n_encryption_key already exists"
    fi
    
    # OpenAI API Key (optional)
    if ! docker secret inspect openai_api_key >/dev/null 2>&1; then
        if [ -n "$OPENAI_API_KEY" ]; then
            echo "$OPENAI_API_KEY" | docker secret create openai_api_key -
            log_success "Created openai_api_key"
        else
            log_info "Skipping openai_api_key (not provided)"
        fi
    else
        log_info "openai_api_key already exists"
    fi
    
    log_success "Secrets configured"
fi

# Deploy the stack
log_info "Deploying GOFR stack..."
cd "$SCRIPT_DIR"

# Export environment variables for compose (fail fast if missing)
require_env JWT_SECRET
require_env NEO4J_PASSWORD
require_env N8N_ENCRYPTION_KEY

export JWT_SECRET
export NEO4J_PASSWORD
export N8N_ENCRYPTION_KEY
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export BACKUP_SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"
export BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
export TZ="${TZ:-UTC}"

docker stack deploy -c gofr-swarm.yml gofr

log_success "GOFR stack deployed!"
echo ""
echo "================================================================"
echo "GOFR Stack Services"
echo "================================================================"
echo ""
echo "Infrastructure:"
echo "  Neo4j:     http://localhost:7474 (bolt://localhost:7687)"
echo "  ChromaDB:  http://localhost:8000"
echo ""
echo "GOFR Services:"
echo "  gofr-plot: MCP=8050, MCPO=8051, Web=8052"
echo "  gofr-doc:  MCP=8040, MCPO=8041, Web=8042"
echo "  gofr-dig:  MCP=8030, MCPO=8031, Web=8032"
echo "  gofr-iq:   MCP=8020, MCPO=8021, Web=8022"
echo "  gofr-np:   MCP=8060, MCPO=8061, Web=8062"
echo ""
echo "Tools:"
echo "  n8n:        http://localhost:5678"
echo "  Open WebUI: http://localhost:3000"
echo ""
echo "Commands:"
echo "  View services:  docker service ls"
echo "  View logs:      docker service logs gofr_<service>"
echo "  Scale service:  docker service scale gofr_<service>=N"
echo "  Remove stack:   docker stack rm gofr"
echo "================================================================"
