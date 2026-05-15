#!/bin/sh
# Vault Entrypoint for GOFR shared infrastructure
# Starts Vault in production mode with file storage

set -eu

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log_info() { printf "%s[VAULT]%s [%s] %s\n" "${BLUE}" "${NC}" "$(timestamp)" "$1"; }
log_success() { printf "%s[VAULT]%s [%s] %s\n" "${GREEN}" "${NC}" "$(timestamp)" "$1"; }
log_warn() { printf "%s[VAULT]%s [%s] %s\n" "${YELLOW}" "${NC}" "$(timestamp)" "$1"; }
log_error() { printf "%s[VAULT]%s [%s] %s\n" "${RED}" "${NC}" "$(timestamp)" "$1" >&2; }

main() {
    log_info "======================================================================="
    log_info "GOFR Shared Vault - Production Mode"
    log_info "======================================================================="
    log_info "Storage:    File-based (/vault/data)"
    log_info "Listen:     ${VAULT_ADDR:-http://0.0.0.0:8201}"
    log_info "Config:     /vault/config/vault.hcl"
    log_info "======================================================================="
    
    if [ ! -f "/vault/data/vault.db" ]; then
        log_warn "Fresh install detected - Vault needs initialization"
        log_warn "After startup, run: docker exec gofr-vault vault operator init"
        log_warn "Save the unseal keys and root token securely!"
    else
        log_info "Existing Vault data found"
        log_warn "Vault will need unsealing after startup"
        log_warn "Run: docker exec gofr-vault vault operator unseal"
    fi
    
    log_info "Starting Vault server in production mode..."
    
    # Execute vault server with config file
    exec vault "$@"
}

main "$@"
