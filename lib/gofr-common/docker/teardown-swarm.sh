#!/bin/bash
# =============================================================================
# GOFR Swarm Teardown Script
# =============================================================================
# Removes the GOFR stack from Docker Swarm
#
# Usage:
#   ./teardown-swarm.sh              # Remove stack, keep volumes
#   ./teardown-swarm.sh --volumes    # Remove stack AND volumes (DESTRUCTIVE!)
#   ./teardown-swarm.sh --secrets    # Remove stack and secrets
#   ./teardown-swarm.sh --all        # Remove everything (DESTRUCTIVE!)
# =============================================================================

set -e

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

# Parse arguments
REMOVE_VOLUMES=false
REMOVE_SECRETS=false

for arg in "$@"; do
    case $arg in
        --volumes)
            REMOVE_VOLUMES=true
            ;;
        --secrets)
            REMOVE_SECRETS=true
            ;;
        --all)
            REMOVE_VOLUMES=true
            REMOVE_SECRETS=true
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --volumes   Also remove all Docker volumes (DESTRUCTIVE!)"
            echo "  --secrets   Also remove Docker secrets"
            echo "  --all       Remove stack, volumes, and secrets (DESTRUCTIVE!)"
            echo "  --help      Show this help message"
            exit 0
            ;;
    esac
done

# Confirmation for destructive operations
if [ "$REMOVE_VOLUMES" = true ]; then
    log_warn "WARNING: This will DELETE all GOFR data volumes!"
    log_warn "This action is IRREVERSIBLE!"
    echo ""
    read -p "Type 'DELETE' to confirm: " confirmation
    if [ "$confirmation" != "DELETE" ]; then
        log_error "Aborted."
        exit 1
    fi
fi

# Remove the stack
log_info "Removing GOFR stack..."
docker stack rm gofr 2>/dev/null || log_warn "Stack not found or already removed"

# Wait for services to be removed
log_info "Waiting for services to terminate..."
sleep 10

# Remove secrets if requested
if [ "$REMOVE_SECRETS" = true ]; then
    log_info "Removing Docker secrets..."
    for secret in jwt_secret neo4j_password n8n_encryption_key openai_api_key; do
        docker secret rm $secret 2>/dev/null || log_info "$secret not found"
    done
    log_success "Secrets removed"
fi

# Remove volumes if requested
if [ "$REMOVE_VOLUMES" = true ]; then
    log_info "Removing Docker volumes..."
    
    # Wait a bit more for containers to release volumes
    sleep 5
    
    VOLUMES=(
        "gofr_gofr-neo4j-data"
        "gofr_gofr-neo4j-logs"
        "gofr_gofr-chroma-data"
        "gofr_gofr-plot-data"
        "gofr_gofr-plot-logs"
        "gofr_gofr-doc-data"
        "gofr_gofr-doc-logs"
        "gofr_gofr-dig-data"
        "gofr_gofr-dig-logs"
        "gofr_gofr-iq-data"
        "gofr_gofr-iq-logs"
        "gofr_gofr-np-data"
        "gofr_gofr-np-logs"
        "gofr_gofr-n8n-data"
        "gofr_gofr-openwebui-data"
        "gofr_gofr-backups"
    )
    
    for vol in "${VOLUMES[@]}"; do
        docker volume rm "$vol" 2>/dev/null || log_info "Volume $vol not found"
    done
    
    log_success "Volumes removed"
fi

# Clean up networks
log_info "Cleaning up networks..."
docker network rm gofr_gofr-net 2>/dev/null || true
docker network rm gofr_gofr-internal 2>/dev/null || true

log_success "GOFR stack teardown complete"

if [ "$REMOVE_VOLUMES" = false ]; then
    echo ""
    log_info "Volumes were preserved. To remove them, run:"
    echo "  $0 --volumes"
fi
