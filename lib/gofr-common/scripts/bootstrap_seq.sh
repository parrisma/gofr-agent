#!/usr/bin/env bash
# =============================================================================
# Bootstrap SEQ logging sink secrets into shared Vault
# =============================================================================
# Writes:
#   - secret/gofr/config/logging/seq-url     (field: value)
#   - secret/gofr/config/logging/seq-api-key (field: value)
#
# Input:
#   - Uses env vars if set, otherwise prompts.
#   - If prompted, exports env vars for remainder of script execution.
#
# Security:
#   - Never prints the API key value.
#   - Requires a Vault token (operator/root) to write secrets.
#
# Usage:
#   ./lib/gofr-common/scripts/bootstrap_seq.sh            # write if missing
#   ./lib/gofr-common/scripts/bootstrap_seq.sh --force     # overwrite existing
#
# Optional env vars:
#   GOFR_SEQ_URL | GOFR_DIG_SEQ_URL | SEQ_URL
#   GOFR_SEQ_API_KEY | GOFR_DIG_SEQ_API_KEY | SEQ_API_KEY
#   GOFR_SHARED_SECRETS_DIR (override where to find vault_root_token)
#   VAULT_TOKEN (if set, overrides vault_root_token file)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOFR_COMMON_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${GOFR_COMMON_ROOT}/../.." && pwd)"

# Source ports if available (for GOFR_VAULT_PORT)
PORTS_ENV="${GOFR_COMMON_ROOT}/config/gofr_ports.env"
if [[ -f "${PORTS_ENV}" ]]; then
  # shellcheck source=/dev/null
  source "${PORTS_ENV}"
fi

info() { echo "[INFO]  $*" >&2; }
ok() { echo "[OK]    $*" >&2; }
fail() { echo "[ERROR] $*" >&2; exit 1; }

resolve_secrets_dir() {
  local candidates=()

  if [[ -n "${GOFR_SHARED_SECRETS_DIR:-}" ]]; then
    candidates+=("${GOFR_SHARED_SECRETS_DIR}")
  fi

  candidates+=(
    "/run/gofr-secrets"
    "${WORKSPACE_ROOT}/secrets"
    "${GOFR_COMMON_ROOT}/secrets"
  )

  local dir
  for dir in "${candidates[@]}"; do
    if [[ -d "${dir}" ]]; then
      echo "${dir}"
      return 0
    fi
  done

  return 1
}

vault_local_addr() {
  local vault_port="${GOFR_VAULT_PORT:-8200}"
  echo "http://127.0.0.1:${vault_port}"
}

require_vault_token() {
  if [[ -n "${VAULT_TOKEN:-}" ]]; then
    return 0
  fi

  local secrets_dir
  if ! secrets_dir="$(resolve_secrets_dir)"; then
    fail "No secrets directory found. Mount gofr-secrets at /run/gofr-secrets or set GOFR_SHARED_SECRETS_DIR."
  fi

  local token_file="${secrets_dir}/vault_root_token"
  if [[ ! -f "${token_file}" ]]; then
    fail "vault_root_token not found at ${token_file}. Bootstrap Vault first (manage_vault.sh bootstrap)."
  fi

  VAULT_TOKEN="$(cat "${token_file}")"
  if [[ -z "${VAULT_TOKEN}" ]]; then
    fail "vault_root_token file is empty at ${token_file}"
  fi
  export VAULT_TOKEN
}

seq_default_url() {
  local host="${GOFR_SEQ_HOST:-gofr-seq}"
  local port="${GOFR_SEQ_INGEST_PORT:-5341}"
  echo "http://${host}:${port}"
}

require_seq_inputs() {
  local resolved_url="${GOFR_SEQ_URL:-${GOFR_DIG_SEQ_URL:-${SEQ_URL:-}}}"
  local resolved_key="${GOFR_SEQ_API_KEY:-${GOFR_DIG_SEQ_API_KEY:-${SEQ_API_KEY:-}}}"

  if [[ -z "${resolved_url}" ]]; then
    local default_url
    default_url="$(seq_default_url)"
    if [[ -t 0 ]]; then
      local input_url=""
      read -r -p "Enter SEQ URL [${default_url}]: " input_url
      resolved_url="${input_url:-${default_url}}"
    else
      resolved_url="${default_url}"
      info "SEQ URL not provided; defaulting to ${default_url}"
    fi
  fi

  if [[ -z "${resolved_key}" ]]; then
    if [[ ! -t 0 ]]; then
      fail "SEQ API key is required. Set GOFR_SEQ_API_KEY (or GOFR_DIG_SEQ_API_KEY/SEQ_API_KEY) and re-run."
    fi
    read -r -s -p "Enter SEQ API key (from SEQ UI > Settings > API keys): " resolved_key
    echo "" >&2
  fi

  if [[ -z "${resolved_url}" ]]; then
    fail "SEQ URL is required"
  fi

  if [[ -z "${resolved_key}" ]]; then
    fail "SEQ API key is required"
  fi

  export GOFR_SEQ_URL="${resolved_url}"
  export GOFR_SEQ_API_KEY="${resolved_key}"
}

vault_kv_put() {
  local path="$1"
  local field="$2"
  local value="$3"

  if command -v vault >/dev/null 2>&1 && [[ -n "${VAULT_ADDR:-}" ]]; then
    VAULT_TOKEN="${VAULT_TOKEN}" vault kv put "${path}" "${field}=${value}" >/dev/null
    return 0
  fi

  local container="gofr-vault"
  if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    fail "Vault container '${container}' is not running. Start it: ./lib/gofr-common/scripts/manage_vault.sh start"
  fi

  docker exec \
    -e VAULT_ADDR="${VAULT_ADDR}" \
    -e VAULT_TOKEN="${VAULT_TOKEN}" \
    "${container}" vault kv put "${path}" "${field}=${value}" >/dev/null
}

# Read a single field from a Vault KV secret. Returns 0 and prints the value
# if the secret exists, returns 1 if missing/error.
vault_kv_get_field() {
  local path="$1"
  local field="$2"

  if command -v vault >/dev/null 2>&1 && [[ -n "${VAULT_ADDR:-}" ]]; then
    VAULT_TOKEN="${VAULT_TOKEN}" vault kv get -field="${field}" "${path}" 2>/dev/null
    return $?
  fi

  local container="gofr-vault"
  if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    return 1
  fi

  docker exec \
    -e VAULT_ADDR="${VAULT_ADDR}" \
    -e VAULT_TOKEN="${VAULT_TOKEN}" \
    "${container}" vault kv get -field="${field}" "${path}" 2>/dev/null
}

# Check whether both SEQ secrets already exist in Vault. Returns 0 if both
# are present (idempotent skip), 1 otherwise.
secrets_already_exist() {
  local url_val key_val
  url_val="$(vault_kv_get_field "secret/gofr/config/logging/seq-url" "value" 2>/dev/null)" || return 1
  key_val="$(vault_kv_get_field "secret/gofr/config/logging/seq-api-key" "value" 2>/dev/null)" || return 1

  if [[ -n "${url_val}" && -n "${key_val}" ]]; then
    return 0
  fi
  return 1
}

FORCE=false
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=true ;;
  esac
done

main() {
  info "Bootstrapping SEQ logging secrets into Vault"

  require_vault_token
  export VAULT_ADDR="${VAULT_ADDR:-$(vault_local_addr)}"

  # Idempotency: skip if secrets already exist (unless --force)
  if [[ "${FORCE}" != "true" ]] && secrets_already_exist; then
    ok "SEQ secrets already exist in Vault (use --force to overwrite)"
    return 0
  fi

  require_seq_inputs

  info "Writing seq-url to Vault (path=secret/gofr/config/logging/seq-url)"
  vault_kv_put "secret/gofr/config/logging/seq-url" "value" "${GOFR_SEQ_URL}" || fail "Failed to write seq-url to Vault"
  ok "seq-url written"

  info "Writing seq-api-key to Vault (path=secret/gofr/config/logging/seq-api-key)"
  vault_kv_put "secret/gofr/config/logging/seq-api-key" "value" "${GOFR_SEQ_API_KEY}" || fail "Failed to write seq-api-key to Vault"
  ok "seq-api-key written"

  ok "SEQ logging secrets bootstrapped"
  info "Next: restart services to pick up secrets (e.g. ./scripts/start-prod.sh --down && ./scripts/start-prod.sh)"
}

main
