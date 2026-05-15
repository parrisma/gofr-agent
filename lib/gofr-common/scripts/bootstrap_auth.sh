#!/bin/bash
# =============================================================================
# GOFR Auth Bootstrap Wrapper Script
# =============================================================================
# Bootstrap authentication for GOFR projects by creating reserved groups
# (public, admin) and generating bootstrap tokens.
#
# This script:
# 1. Sources port configuration from gofr_ports.env
# 2. Sets up environment variables for the specified project
# 3. Calls bootstrap_auth.py to create groups and tokens
#
# Usage:
#   # Bootstrap with default prefix (GOFR) in production mode
#   ./bootstrap_auth.sh
#
#   # Bootstrap for production docker environment (explicit)
#   ./bootstrap_auth.sh --docker
#   ./bootstrap_auth.sh --prod
#
#   # Bootstrap for dev/test environment (uses gofr-vault-test)
#   ./bootstrap_auth.sh --dev
#   ./bootstrap_auth.sh --test
#
#   # Bootstrap for specific project
#   ./bootstrap_auth.sh --prefix GOFR --docker
#
#   # Bootstrap groups only (no tokens)
#   ./bootstrap_auth.sh --groups-only --docker
#
#   # Capture tokens to file
#   ./bootstrap_auth.sh --prefix GOFR --docker > tokens.env
#   source tokens.env
#
#   # Use with eval for current shell
#   eval "$(./bootstrap_auth.sh --prefix GOFR --docker)"
#
# REQUIREMENTS:
#   - Vault must be running and unsealed
#   - JWT secret must exist in Vault at secret/gofr/config/jwt-signing-secret
#   - GOFR_VAULT_TOKEN must be set (root or admin token)
#   - gofr_ports.env must exist (for port configuration)
#
#   For production setup, this is called automatically by scripts/start-prod.sh
#   For manual setup, use auth_env.sh to load required secrets first:
#     source lib/gofr-common/scripts/auth_env.sh --docker
#     ./bootstrap_auth.sh --docker
#
# Environment Variables (can be set before running):
#   GOFR_AUTH_PREFIX       Default prefix if --prefix not specified
#   GOFR_VAULT_URL         Vault server URL (overrides auto-detection)
#   GOFR_VAULT_TOKEN       Vault token (default: from gofr_ports.env)
#   GOFR_JWT_SECRET        Optional override (default: read from Vault)
#
# Environment Modes:
#   --docker|--prod        Production mode (default): gofr-vault:8301
#   --dev|--test           Dev/test mode: gofr-vault-test:8200
#
# =============================================================================

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOFR_COMMON_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${GOFR_COMMON_ROOT}/../.." && pwd)"

# Source port configuration if available
GOFR_PORTS_ENV="${GOFR_COMMON_ROOT}/config/gofr_ports.env"
if [[ -f "$GOFR_PORTS_ENV" ]]; then
    set -a
    source "$GOFR_PORTS_ENV"
    set +a
fi

# Parse command line for --prefix to set up project-specific defaults
PREFIX="GOFR"
ENV_MODE="prod"  # Default to production
EXTRA_ARGS=()
ADMIN_ROLE_NAME="gofr-admin-control"

while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            PREFIX="$2"
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        --prefix=*)
            PREFIX="${1#*=}"
            EXTRA_ARGS+=("$1")
            shift
            ;;
        --docker|--prod)
            ENV_MODE="prod"
            shift
            ;;
        --dev|--test)
            ENV_MODE="dev"
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Normalize prefix
PREFIX="${PREFIX^^}"  # uppercase
PREFIX="${PREFIX%%_}" # remove trailing underscore if present

# Build dynamic variable names
VAULT_URL_VAR="${PREFIX}_VAULT_URL"
VAULT_TOKEN_VAR="${PREFIX}_VAULT_TOKEN"
AUTH_BACKEND_VAR="${PREFIX}_AUTH_BACKEND"
VAULT_PATH_PREFIX_VAR="${PREFIX}_VAULT_PATH_PREFIX"
VAULT_MOUNT_POINT_VAR="${PREFIX}_VAULT_MOUNT_POINT"

# Set default environment variables based on prefix
# Use dynamic variable assignment with proper default handling

# Determine Vault hostname and port based on ENV_MODE
if [[ "${ENV_MODE}" == "prod" ]]; then
    VAULT_HOSTNAME="gofr-vault"
    VAULT_DEFAULT_PORT="${GOFR_VAULT_PORT:-8201}"
else
    VAULT_HOSTNAME="gofr-vault-test"
    VAULT_DEFAULT_PORT="${GOFR_VAULT_PORT_TEST:-8301}"
fi

# Vault URL - use gofr_ports.env port if available
DEFAULT_VAULT_URL="http://${VAULT_HOSTNAME}:${VAULT_DEFAULT_PORT}"
if [[ -z "${!VAULT_URL_VAR:-}" ]]; then
    export "${VAULT_URL_VAR}"="${DEFAULT_VAULT_URL}"
fi

# Auth backend - default to vault
if [[ -z "${!AUTH_BACKEND_VAR:-}" ]]; then
    export "${AUTH_BACKEND_VAR}"="vault"
fi

# Vault path prefix (e.g., gofr-iq/auth for GOFR)
if [[ -z "${!VAULT_PATH_PREFIX_VAR:-}" ]]; then
    PATH_PREFIX=$(echo "${PREFIX}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
    export "${VAULT_PATH_PREFIX_VAR}"="${PATH_PREFIX}/auth"
fi

# Vault mount point - default to secret
if [[ -z "${!VAULT_MOUNT_POINT_VAR:-}" ]]; then
    export "${VAULT_MOUNT_POINT_VAR}"="secret"
fi

# Hard-cutover admin role is scoped for auth-management only.
# Disable optional policy/JWT write steps to avoid expected permission warning noise.
BOOTSTRAP_INSTALL_POLICIES_VAR="${PREFIX}_BOOTSTRAP_INSTALL_POLICIES"
BOOTSTRAP_STORE_JWT_VAR="${PREFIX}_BOOTSTRAP_STORE_JWT_SECRET"
export "${BOOTSTRAP_INSTALL_POLICIES_VAR}"="false"
export "${BOOTSTRAP_STORE_JWT_VAR}"="false"

ADMIN_CREDS_FILE="${WORKSPACE_ROOT}/secrets/service_creds/${ADMIN_ROLE_NAME}.json"
if [[ ! -f "${ADMIN_CREDS_FILE}" ]]; then
    ADMIN_CREDS_FILE="${GOFR_COMMON_ROOT}/secrets/service_creds/${ADMIN_ROLE_NAME}.json"
fi

if [[ ! -f "${ADMIN_CREDS_FILE}" ]]; then
    echo "" >&2
    echo "ERROR: Admin AppRole credentials file is missing." >&2
    echo "" >&2
    echo "Cause: hard cutover requires ${ADMIN_ROLE_NAME} credentials for auth bootstrap operations." >&2
    echo "Context: expected ${WORKSPACE_ROOT}/secrets/service_creds/${ADMIN_ROLE_NAME}.json or ${GOFR_COMMON_ROOT}/secrets/service_creds/${ADMIN_ROLE_NAME}.json" >&2
    echo "Recovery options:" >&2
    echo "  1. Provision roles/creds: uv run scripts/setup_approle.py" >&2
    echo "  2. Verify file permissions and mount at secrets/service_creds" >&2
    echo "" >&2
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
    echo "" >&2
    echo "ERROR: Admin AppRole credentials are invalid." >&2
    echo "" >&2
    echo "Cause: role_id and/or secret_id are missing in credentials file." >&2
    echo "Context: file=${ADMIN_CREDS_FILE}" >&2
    echo "Recovery options:" >&2
    echo "  1. Reprovision credentials: uv run scripts/setup_approle.py" >&2
    echo "  2. Confirm JSON keys role_id and secret_id exist" >&2
    echo "" >&2
    exit 1
fi

ROLE_ID_VALUE="${ADMIN_CREDS[0]}"
SECRET_ID_VALUE="${ADMIN_CREDS[1]}"

approle_login_json() {
    local vault_url="$1"
    local role_id="$2"
    local secret_id="$3"

    if command -v vault >/dev/null 2>&1; then
        VAULT_ADDR="${vault_url}" vault write -format=json auth/approle/login role_id="${role_id}" secret_id="${secret_id}"
        return $?
    fi

    local container_name="${VAULT_HOSTNAME}"
    if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        return 1
    fi

    docker exec -e VAULT_ADDR="http://127.0.0.1:${VAULT_DEFAULT_PORT}" "${container_name}" vault write -format=json auth/approle/login role_id="${role_id}" secret_id="${secret_id}"
}

APPROLE_LOGIN_JSON="$(approle_login_json "${!VAULT_URL_VAR}" "${ROLE_ID_VALUE}" "${SECRET_ID_VALUE}" 2>/dev/null || true)"
if [[ -z "${APPROLE_LOGIN_JSON}" ]]; then
    echo "" >&2
    echo "ERROR: Failed to authenticate admin AppRole with Vault." >&2
    echo "" >&2
    echo "Cause: Vault AppRole login returned no response." >&2
    echo "Context: role=${ADMIN_ROLE_NAME}, vault_url=${!VAULT_URL_VAR}" >&2
    echo "Recovery options:" >&2
    echo "  1. Ensure Vault is running and reachable" >&2
    echo "  2. Reprovision credentials: uv run scripts/setup_approle.py" >&2
    echo "" >&2
    exit 1
fi

VAULT_CLIENT_TOKEN="$(uv run python -c '
import json
import sys
payload = json.loads(sys.stdin.read())
print(payload.get("auth", {}).get("client_token", ""))
' <<<"${APPROLE_LOGIN_JSON}")"

if [[ -z "${VAULT_CLIENT_TOKEN}" ]]; then
    echo "" >&2
    echo "ERROR: Failed to extract Vault client token from AppRole login response." >&2
    echo "" >&2
    echo "Cause: auth.client_token missing in Vault response." >&2
    echo "Context: role=${ADMIN_ROLE_NAME}, creds_file=${ADMIN_CREDS_FILE}" >&2
    echo "Recovery options:" >&2
    echo "  1. Reprovision credentials: uv run scripts/setup_approle.py" >&2
    echo "  2. Verify policy/role bindings for ${ADMIN_ROLE_NAME}" >&2
    echo "" >&2
    exit 1
fi

export "${VAULT_TOKEN_VAR}"
printf -v "${VAULT_TOKEN_VAR}" '%s' "${VAULT_CLIENT_TOKEN}"

# JWT secret - source of truth is Vault
JWT_SECRET_VAR="${PREFIX}_JWT_SECRET"
if [[ -z "${!JWT_SECRET_VAR:-}" ]]; then
    vault_kv_get() {
        local path="$1"
        local field="$2"
        local vault_url="${!VAULT_URL_VAR:-${DEFAULT_VAULT_URL}}"
        local vault_token="${!VAULT_TOKEN_VAR:-}"

        if [[ -z "${vault_token}" ]]; then
            return 1
        fi

        if command -v vault >/dev/null 2>&1; then
            VAULT_ADDR="${vault_url}" VAULT_TOKEN="${vault_token}" vault kv get -field="${field}" "${path}"
            return $?
        fi

        local container_name="${VAULT_HOSTNAME}"
        if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
            return 1
        fi

        docker exec -e VAULT_ADDR="http://127.0.0.1:${VAULT_DEFAULT_PORT}" -e VAULT_TOKEN="${vault_token}" "${container_name}" vault kv get -field="${field}" "${path}"
    }

    JWT_FROM_VAULT="$(vault_kv_get "secret/gofr/config/jwt-signing-secret" "value" 2>/dev/null || true)"
    if [[ -n "${JWT_FROM_VAULT}" ]]; then
        export "${JWT_SECRET_VAR}"="${JWT_FROM_VAULT}"
    fi
fi

if [[ -z "${!JWT_SECRET_VAR:-}" ]]; then
    echo "" >&2
    echo "ERROR: Failed to resolve ${JWT_SECRET_VAR}." >&2
    echo "" >&2
    echo "Cause: JWT secret must be sourced from Vault and was not readable." >&2
    echo "Context: Vault URL=${!VAULT_URL_VAR:-not-set}, Path=secret/gofr/config/jwt-signing-secret" >&2
    echo "Recovery options:" >&2
    echo "  1. Ensure Vault is running and reachable" >&2
    echo "  2. Ensure ${VAULT_TOKEN_VAR} is valid and has read access" >&2
    echo "  3. Bootstrap JWT secret: ./lib/gofr-common/scripts/manage_vault.sh bootstrap" >&2
    echo "" >&2
    exit 1
fi

# Log configuration (to stderr)
echo "=== GOFR Auth Bootstrap ===" >&2
echo "Environment:  ${ENV_MODE}" >&2
echo "Prefix:       ${PREFIX}" >&2
echo "Backend:      ${!AUTH_BACKEND_VAR:-vault}" >&2
echo "Vault URL:    ${!VAULT_URL_VAR:-not set}" >&2
echo "Vault Token:  ${!VAULT_TOKEN_VAR:0:16}..." >&2
echo "Vault Role:   ${ADMIN_ROLE_NAME}" >&2
echo "" >&2

# Run the Python bootstrap script
# Tokens go to stdout, logs go to stderr
cd "${GOFR_COMMON_ROOT}"

# Use uv run if available, otherwise try python3 directly
if command -v uv &> /dev/null; then
    uv run --active python3 "${SCRIPT_DIR}/bootstrap_auth.py" --prefix "${PREFIX}" "${EXTRA_ARGS[@]}"
elif [[ -f "${GOFR_COMMON_ROOT}/.venv/bin/python" ]]; then
    "${GOFR_COMMON_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/bootstrap_auth.py" --prefix "${PREFIX}" "${EXTRA_ARGS[@]}"
else
    python3 "${SCRIPT_DIR}/bootstrap_auth.py" --prefix "${PREFIX}" "${EXTRA_ARGS[@]}"
fi

exit_code=$?

if [[ $exit_code -eq 0 ]]; then
    echo "" >&2
    echo "✓ Bootstrap complete" >&2
else
    echo "" >&2
    echo "✗ Bootstrap failed (exit code: ${exit_code})" >&2
fi

exit $exit_code
