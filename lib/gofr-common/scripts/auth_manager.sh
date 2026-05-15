#!/bin/bash
# =============================================================================
# Auth Manager Wrapper Script
# =============================================================================
# Wrapper for auth_manager.py that handles SSOT environment configuration.
#
# RECOMMENDED USAGE:
#   ./lib/gofr-common/scripts/auth_manager.sh groups list
#   ./lib/gofr-common/scripts/auth_manager.sh tokens list
#
# In a dev container, Docker hostnames are auto-detected; you typically do not
# need to pass --docker explicitly.
#
# SSOT PATTERN:
#   This script automatically sources:
#   1. lib/gofr-common/config/gofr_ports.env  (ports)
#   2. secrets/service_creds/gofr-admin-control.json (AppRole role_id/secret_id)
#
# It logs into Vault with the admin-control AppRole and exports:
#   GOFR_VAULT_URL, GOFR_VAULT_TOKEN, GOFR_AUTH_BACKEND
#
#   JWT signing secret is read from Vault at runtime by JwtSecretProvider
#   in auth_manager.py -- no env var needed.
#
# COMMANDS:
#   See: python lib/gofr-common/scripts/auth_manager.py --help
# =============================================================================

set -euo pipefail

# Default values (auto-detect dev container)
USE_DOCKER=false
if [[ -f "/.dockerenv" ]] || [[ -n "${DEVCONTAINER:-}" ]] || [[ -n "${REMOTE_CONTAINERS:-}" ]]; then
  USE_DOCKER=true
fi

# Parse wrapper flags (before passing to Python)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)
            USE_DOCKER=true
            shift
            ;;
        --help|-h)
            cat << 'EOF'
Auth Manager Wrapper - SSOT Environment Handler

USAGE:
  auth_manager.sh [--docker] <command> [args...]

OPTIONS:
  --docker          Use Docker hostnames (default: auto-detected in containers)
  --help, -h        Show this help

EXAMPLES:
  # List groups:
  ./lib/gofr-common/scripts/auth_manager.sh groups list

  # List tokens:
  ./lib/gofr-common/scripts/auth_manager.sh tokens list

  # Create admin token:
  ./lib/gofr-common/scripts/auth_manager.sh tokens create --groups admin --name dev-api

  # List tokens filtered by name pattern:
  ./lib/gofr-common/scripts/auth_manager.sh tokens list --name-pattern "prod-*"

  # Inspect token:
  ./lib/gofr-common/scripts/auth_manager.sh tokens inspect eyJhbGc...

  # Inspect by name:
  ./lib/gofr-common/scripts/auth_manager.sh tokens inspect --name dev-api

ENVIRONMENT:
  This wrapper is self-contained. It reads AppRole credentials from:
    - secrets/service_creds/gofr-admin-control.json
    - lib/gofr-common/secrets/service_creds/gofr-admin-control.json (fallback)

For full command reference, run:
  python lib/gofr-common/scripts/auth_manager.py --help
EOF
            exit 0
            ;;
        *)
            # First non-flag argument - pass everything to Python
            break
            ;;
    esac
done

# Find workspace root (where docker/ and lib/ exist)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_DIR="$(dirname "${SCRIPT_DIR}")"
WORKSPACE_ROOT="$(cd "${COMMON_DIR}/../.." && pwd)"

# Source SSOT files in correct order
PORTS_ENV="${COMMON_DIR}/config/gofr_ports.env"
SECRETS_DIR="${WORKSPACE_ROOT}/secrets"
FALLBACK_SECRETS_DIR="${WORKSPACE_ROOT}/lib/gofr-common/secrets"
ADMIN_ROLE_NAME="gofr-admin-control"

if [[ ! -f "${PORTS_ENV}" ]]; then
    echo "ERROR: Port config not found: ${PORTS_ENV}" >&2
  echo "Recovery: ensure gofr-common submodule is initialised and ports env exists." >&2
    exit 1
fi

# Source SSOT port config
set -a
source "${PORTS_ENV}"
set +a

# Configure Vault URL based on --docker flag
if [[ "${USE_DOCKER}" == true ]]; then
    export GOFR_VAULT_URL="http://gofr-vault:${GOFR_VAULT_PORT}"
else
    export GOFR_VAULT_URL="http://host.docker.internal:${GOFR_VAULT_PORT}"
fi

# Set backend (vault only)
export GOFR_AUTH_BACKEND="vault"

ADMIN_CREDS_FILE="${SECRETS_DIR}/service_creds/${ADMIN_ROLE_NAME}.json"
if [[ ! -f "${ADMIN_CREDS_FILE}" ]]; then
  ADMIN_CREDS_FILE="${FALLBACK_SECRETS_DIR}/service_creds/${ADMIN_ROLE_NAME}.json"
fi

if [[ ! -f "${ADMIN_CREDS_FILE}" ]]; then
  echo "ERROR: Admin AppRole credentials file is missing" >&2
  echo "   Cause: hard cutover requires admin-control role credentials" >&2
  echo "   Context: expected ${SECRETS_DIR}/service_creds/${ADMIN_ROLE_NAME}.json or ${FALLBACK_SECRETS_DIR}/service_creds/${ADMIN_ROLE_NAME}.json" >&2
  echo "   Recovery: run uv run scripts/setup_approle.py to provision ${ADMIN_ROLE_NAME}" >&2
  exit 1
fi

readarray -t ADMIN_CREDS < <(uv run python -c '
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
print(payload.get("role_id", ""))
print(payload.get("secret_id", ""))
' "${ADMIN_CREDS_FILE}")

if [[ "${#ADMIN_CREDS[@]}" -lt 2 ]] || [[ -z "${ADMIN_CREDS[0]}" ]] || [[ -z "${ADMIN_CREDS[1]}" ]]; then
  echo "ERROR: Admin AppRole credentials are invalid" >&2
  echo "   Cause: missing role_id and/or secret_id" >&2
  echo "   Context: file=${ADMIN_CREDS_FILE}" >&2
  echo "   Recovery: re-run uv run scripts/setup_approle.py to refresh ${ADMIN_ROLE_NAME} credentials" >&2
  exit 1
fi

export GOFR_VAULT_ROLE_ID="${ADMIN_CREDS[0]}"
export GOFR_VAULT_SECRET_ID="${ADMIN_CREDS[1]}"

vault_approle_login() {
  local vault_url="$1"
  local role_id="$2"
  local secret_id="$3"

  if command -v vault >/dev/null 2>&1; then
    VAULT_ADDR="${vault_url}" vault write -format=json auth/approle/login role_id="${role_id}" secret_id="${secret_id}"
    return $?
  fi

  local vault_container="gofr-vault"
  if ! docker ps --format '{{.Names}}' | grep -q "^${vault_container}$"; then
    echo "ERROR: Cannot authenticate admin AppRole to Vault" >&2
    echo "   Cause: vault CLI not installed and ${vault_container} container not running" >&2
    echo "   Context: GOFR_VAULT_URL=${vault_url}, role=${ADMIN_ROLE_NAME}" >&2
    echo "   Recovery: install vault CLI or start Vault: ./lib/gofr-common/scripts/manage_vault.sh start" >&2
    return 1
  fi

  docker exec -e VAULT_ADDR="http://127.0.0.1:${GOFR_VAULT_PORT}" "${vault_container}" vault write -format=json auth/approle/login role_id="${role_id}" secret_id="${secret_id}"
}

APPROLE_LOGIN_JSON="$(vault_approle_login "${GOFR_VAULT_URL}" "${GOFR_VAULT_ROLE_ID}" "${GOFR_VAULT_SECRET_ID}" 2>/dev/null || true)"
if [[ -z "${APPROLE_LOGIN_JSON}" ]]; then
  echo "ERROR: Failed to authenticate with admin AppRole" >&2
  echo "   Cause: Vault login returned no response" >&2
  echo "   Context: GOFR_VAULT_URL=${GOFR_VAULT_URL}, role=${ADMIN_ROLE_NAME}" >&2
  echo "   Recovery: reprovision credentials with uv run scripts/setup_approle.py" >&2
  exit 1
fi

GOFR_VAULT_TOKEN="$(uv run python -c '
import json
import sys
payload = json.loads(sys.stdin.read())
print(payload.get("auth", {}).get("client_token", ""))
' <<<"${APPROLE_LOGIN_JSON}")"

if [[ -z "${GOFR_VAULT_TOKEN}" ]]; then
  echo "ERROR: Failed to extract Vault client token from AppRole login" >&2
  echo "   Cause: Vault response missing auth.client_token" >&2
  echo "   Context: role=${ADMIN_ROLE_NAME}, creds_file=${ADMIN_CREDS_FILE}" >&2
  echo "   Recovery: regenerate credentials via uv run scripts/setup_approle.py" >&2
  exit 1
fi
export GOFR_VAULT_TOKEN

# Display configuration
echo "=== Auth Manager Configuration ===" >&2
echo "Environment: prod" >&2
echo "Backend: vault" >&2
echo "Vault URL: ${GOFR_VAULT_URL}" >&2
echo "Vault Token: ${GOFR_VAULT_TOKEN:0:8}..." >&2
echo "Vault Role: ${ADMIN_ROLE_NAME}" >&2
echo "=====================================" >&2
echo "" >&2

# Run auth_manager.py with remaining arguments
cd "${SCRIPT_DIR}"
exec uv run python auth_manager.py --backend "vault" "$@"
