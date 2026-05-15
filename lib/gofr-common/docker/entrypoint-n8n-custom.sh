#!/bin/sh
set -eu

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log_info() { printf "[%s] [INFO] %s\n" "$(timestamp)" "$1"; }
log_warn() { printf "[%s] [WARN] %s\n" "$(timestamp)" "$1"; }
log_error() { printf "[%s] [ERROR] %s\n" "$(timestamp)" "$1" >&2; }

log_info "Initialising custom n8n nodes..."

# Ensure the nodes directory exists
mkdir -p /home/node/.n8n/nodes

# Copy the pre-installed nodes from the image to the volume
if [ -d "/opt/custom-nodes/node_modules/n8n-nodes-openrouter" ]; then
    log_info "Installing n8n-nodes-openrouter..."
    # Remove old version if exists
    rm -rf /home/node/.n8n/nodes/n8n-nodes-openrouter
    # Copy fresh from image
    cp -r /opt/custom-nodes/node_modules/n8n-nodes-openrouter /home/node/.n8n/nodes/
    
    # Verify installation
    if [ -f "/home/node/.n8n/nodes/n8n-nodes-openrouter/package.json" ]; then
        log_info "OpenRouter node installed successfully"
        ls -la /home/node/.n8n/nodes/n8n-nodes-openrouter/dist/ 2>/dev/null || log_warn "dist directory not found"
    else
        log_error "Installation verification failed"
    fi
else
    log_warn "n8n-nodes-openrouter not found in /opt/custom-nodes"
fi

log_info "Starting n8n..."

# Fix argument passing: if the command starts with 'n8n', strip it
# because /docker-entrypoint.sh prepends 'n8n' to arguments.
if [ "${1:-}" = "n8n" ]; then
    shift
fi

# Hand off to the original entrypoint
exec /docker-entrypoint.sh "$@"
