#!/bin/bash
# Unified Vault lifecycle helper for the shared GOFR Vault
# Commands: start|stop|status|logs|init|unseal|env|jwt-secret|bootstrap|health

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/vault-compose.yml"
SECRETS_DIR="${PROJECT_ROOT}/secrets"
DATA_DIR="${PROJECT_ROOT}/data/vault"
CONTAINER_NAME="gofr-vault"

# Phase 1 hardening:
# - Never rely on gofr-secrets (runtime) volume as the long-term home for
#   bootstrap artifacts.
# - Prefer a dedicated bootstrap volume for root token/unseal key.
# - Keep legacy recovery from gofr-secrets for transition only.
BOOTSTRAP_VOLUME="gofr-vault-bootstrap"
LEGACY_RUNTIME_VOLUME="gofr-secrets"

# Auto-detect if running inside a container
if [ -f "/.dockerenv" ] || grep -qa "docker" /proc/1/cgroup 2>/dev/null; then
  VAULT_ADDR_DEFAULT="http://gofr-vault:8201"
else
  VAULT_ADDR_DEFAULT="http://localhost:8201"
fi

log() { echo "[vault-manage] $*"; }
err() { echo "[vault-manage][ERROR] $*" >&2; }

volume_read_file() {
  local volume="$1"
  local relpath="$2"

  if ! docker volume inspect "${volume}" >/dev/null 2>&1; then
    return 1
  fi

  docker run --rm -v "${volume}:/s:ro" alpine:3.19 sh -c "cat '/s/${relpath}'" 2>/dev/null
}

ensure_bootstrap_volume() {
  if ! docker volume inspect "${BOOTSTRAP_VOLUME}" >/dev/null 2>&1; then
    log "Creating bootstrap volume: ${BOOTSTRAP_VOLUME}"
    docker volume create "${BOOTSTRAP_VOLUME}" >/dev/null
  fi
}

sync_bootstrap_artifacts_to_volume() {
  # Best-effort: seed the bootstrap volume with Vault bootstrap artifacts.
  # Policy:
  # - Default: seed only if the volume is empty (prevents overwriting a valid
  #   bootstrap volume with a stale local cache).
  # - Forced: overwrite when explicitly requested (used during force rebuild or
  #   re-init scenarios).
  local force_seed="${1:-false}"
  if [ "${GOFR_FORCE_BOOTSTRAP_SEED:-}" = "1" ]; then
    force_seed=true
  fi

  if [ ! -f "${SECRETS_DIR}/vault_root_token" ] || [ ! -f "${SECRETS_DIR}/vault_unseal_key" ]; then
    return 0
  fi

  ensure_bootstrap_volume

  if [ "${force_seed}" != "true" ]; then
    local existing_token existing_unseal
    existing_token="$(volume_read_file "${BOOTSTRAP_VOLUME}" vault_root_token || true)"
    existing_unseal="$(volume_read_file "${BOOTSTRAP_VOLUME}" vault_unseal_key || true)"
    if [ -n "${existing_token}" ] && [ -n "${existing_unseal}" ]; then
      return 0
    fi
  fi

  local helper="gofr-vault-bootstrap-sync-$$"
  docker run -d --name "${helper}" -v "${BOOTSTRAP_VOLUME}:/dst" alpine:3.19 sleep 60 >/dev/null

  docker exec "${helper}" sh -c 'chmod 700 /dst || true' >/dev/null 2>&1 || true
  docker cp "${SECRETS_DIR}/vault_root_token" "${helper}:/dst/vault_root_token" >/dev/null 2>&1 || true
  docker cp "${SECRETS_DIR}/vault_unseal_key" "${helper}:/dst/vault_unseal_key" >/dev/null 2>&1 || true
  if [ -f "${SECRETS_DIR}/bootstrap_tokens.json" ]; then
    docker cp "${SECRETS_DIR}/bootstrap_tokens.json" "${helper}:/dst/bootstrap_tokens.json" >/dev/null 2>&1 || true
  fi

  docker exec "${helper}" sh -c 'chmod 600 /dst/vault_root_token /dst/vault_unseal_key 2>/dev/null || true' >/dev/null 2>&1 || true
  docker rm -f "${helper}" >/dev/null 2>&1 || true
}

vault_initialized_unsealed() {
  local status_json
  status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
  if [ -z "${status_json}" ]; then
    return 1
  fi

  local initialized sealed
  initialized=$(echo "${status_json}" | grep -o '"initialized": *[a-z]*' | sed 's/.*: *//')
  sealed=$(echo "${status_json}" | grep -o '"sealed": *[a-z]*' | sed 's/.*: *//')
  [ "${initialized}" = "true" ] && [ "${sealed}" = "false" ]
}

vault_is_initialized() {
  local status_json
  status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
  if [ -z "${status_json}" ]; then
    return 1
  fi
  local initialized
  initialized=$(echo "${status_json}" | grep -o '"initialized": *[a-z]*' | sed 's/.*: *//')
  [ "${initialized}" = "true" ]
}

vault_token_valid() {
  local token="$1"
  if [ -z "${token}" ]; then
    return 1
  fi
  docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${token}" \
    "${CONTAINER_NAME}" vault token lookup >/dev/null 2>&1
}

reconcile_local_bootstrap_artifacts() {
  # Self-heal:
  # - If Vault is already initialized+unsealed but local token/unseal key are
  #   missing, attempt to restore them from the bootstrap volume.
  # - If local root token exists but is invalid/revoked, attempt the same.
  # - Legacy: fall back to reading from gofr-secrets volume (transition only).

  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    return 0
  fi

  if ! vault_initialized_unsealed; then
    return 0
  fi

  ensure_dirs

  local need_recover=false
  if [ ! -f "${SECRETS_DIR}/vault_root_token" ] || [ ! -f "${SECRETS_DIR}/vault_unseal_key" ]; then
    need_recover=true
  elif ! vault_token_valid "$(cat "${SECRETS_DIR}/vault_root_token" 2>/dev/null || true)"; then
    need_recover=true
  fi

  if [ "${need_recover}" != "true" ]; then
    return 0
  fi

  log "Reconciling local Vault bootstrap artifacts (missing or invalid)..."

  local token=""
  token="$(volume_read_file "${BOOTSTRAP_VOLUME}" vault_root_token || true)"
  if [ -z "${token}" ]; then
    token="$(volume_read_file "${LEGACY_RUNTIME_VOLUME}" vault_root_token || true)"
  fi

  local unseal=""
  unseal="$(volume_read_file "${BOOTSTRAP_VOLUME}" vault_unseal_key || true)"
  if [ -z "${unseal}" ]; then
    unseal="$(volume_read_file "${LEGACY_RUNTIME_VOLUME}" vault_unseal_key || true)"
  fi

  if [ -n "${token}" ]; then
    echo -n "${token}" > "${SECRETS_DIR}/vault_root_token"
    chmod 600 "${SECRETS_DIR}/vault_root_token" 2>/dev/null || true
  fi
  if [ -n "${unseal}" ]; then
    echo -n "${unseal}" > "${SECRETS_DIR}/vault_unseal_key"
    chmod 600 "${SECRETS_DIR}/vault_unseal_key" 2>/dev/null || true
  fi

  if [ -f "${SECRETS_DIR}/vault_root_token" ] && vault_token_valid "$(cat "${SECRETS_DIR}/vault_root_token" 2>/dev/null || true)"; then
    log "✓ Local root token recovered and validated"
    sync_bootstrap_artifacts_to_volume || true
    return 0
  fi

  err "Vault is initialized+unsealed but a valid local root token could not be recovered."
  err "Fix: seed ${BOOTSTRAP_VOLUME} with vault_root_token/vault_unseal_key or re-run Vault bootstrap."
  return 1
}

# Wait until Vault API is responsive and unsealed (or confirm sealed state).
# Returns 0 if unsealed, 1 if sealed, 2 if unreachable.
wait_vault_api_ready() {
  local max_attempts=${1:-15}
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))
    local status_json
    status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
    if [ -n "$status_json" ]; then
      local sealed
      sealed=$(echo "$status_json" | grep -o '"sealed": *[a-z]*' | sed 's/.*: *//')
      if [ "$sealed" = "false" ]; then
        return 0
      elif [ "$sealed" = "true" ]; then
        return 1
      fi
    fi
    sleep 2
  done
  return 2
}

# Check if Vault is sealed using JSON status (reliable, no text parsing races).
is_vault_sealed() {
  local status_json
  status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
  if [ -z "$status_json" ]; then
    return 0  # Can't reach = treat as sealed
  fi
  local sealed
  sealed=$(echo "$status_json" | grep -o '"sealed": *[a-z]*' | sed 's/.*: *//')
  [ "$sealed" = "true" ]
}

ensure_dirs() {
  mkdir -p "${SECRETS_DIR}" "${DATA_DIR}"
  chmod 700 "${SECRETS_DIR}" || true
}

ensure_volumes() {
  # Create Docker volumes if they don't exist
  for vol in gofr-vault-data gofr-vault-logs gofr-vault-file; do
    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
      log "Creating volume: $vol"
      docker volume create "$vol" >/dev/null
    fi
  done
}

ensure_network() {
  # Create gofr-net network if it doesn't exist
  if ! docker network inspect gofr-net >/dev/null 2>&1; then
    log "Creating network: gofr-net"
    docker network create gofr-net >/dev/null
  fi
}

health_check() {
  log "=== Vault Health Check ==="
  
  # Check container is running
  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    err "Container ${CONTAINER_NAME} is not running"
    return 1
  fi
  log "✓ Container is running"
  
  # Check vault is initialized
  local status_json
  status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
  if [ -z "$status_json" ]; then
    err "Cannot reach Vault API"
    return 1
  fi
  
  local initialized
  initialized=$(echo "$status_json" | grep -o '"initialized": *[a-z]*' | sed 's/.*: *//')
  if [ "$initialized" != "true" ]; then
    err "Vault is not initialized - run: $0 bootstrap"
    return 1
  fi
  log "✓ Vault is initialized"
  
  # Check vault is unsealed
  local sealed
  sealed=$(echo "$status_json" | grep -o '"sealed": *[a-z]*' | sed 's/.*: *//')
  if [ "$sealed" = "true" ]; then
    err "Vault is sealed - run: $0 unseal"
    return 1
  fi
  log "✓ Vault is unsealed"

  # Self-heal: recover missing/stale local bootstrap artifacts where possible.
  reconcile_local_bootstrap_artifacts || return 1
  
  # Check root token exists AND is valid before claiming success.
  if [ ! -f "${SECRETS_DIR}/vault_root_token" ]; then
    err "Root token not found at ${SECRETS_DIR}/vault_root_token"
    return 1
  fi

  local root_token
  root_token="$(cat "${SECRETS_DIR}/vault_root_token" 2>/dev/null || true)"
  if ! vault_token_valid "${root_token}"; then
    err "Root token present but invalid/revoked: ${SECRETS_DIR}/vault_root_token"
    err "Fix: seed ${BOOTSTRAP_VOLUME} with a valid token (vault_root_token/vault_unseal_key) or re-run Vault bootstrap."
    return 1
  fi
  log "✓ Root token valid"
  
  if [ ! -f "${SECRETS_DIR}/vault_unseal_key" ]; then
    err "Unseal key not found at ${SECRETS_DIR}/vault_unseal_key"
    return 1
  fi
  if [ ! -s "${SECRETS_DIR}/vault_unseal_key" ]; then
    err "Unseal key file is empty: ${SECRETS_DIR}/vault_unseal_key"
    return 1
  fi
  log "✓ Unseal key present"
  
  # Check KV secrets engine is enabled
  export VAULT_ADDR="${VAULT_ADDR_DEFAULT}"
  export VAULT_TOKEN=$(cat "${SECRETS_DIR}/vault_root_token")
  if ! docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN}" \
       "${CONTAINER_NAME}" vault secrets list 2>&1 | grep -q "^secret/"; then
    err "KV secrets engine not enabled at secret/"
    return 1
  fi
  log "✓ KV secrets engine enabled"
  
  # Check if auth is bootstrapped (check for a group)
  if ! docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN}" \
       "${CONTAINER_NAME}" vault kv list secret/gofr/auth/groups 2>/dev/null | grep -q .; then
    log "⚠ Auth not bootstrapped - run: $0 bootstrap"
    return 2  # Warning, not error
  fi
  log "✓ Auth is bootstrapped"

  # Best-effort: keep bootstrap volume synced on successful health.
  # This ensures other repos can recover missing local tokens without relying
  # on the runtime gofr-secrets volume.
  sync_bootstrap_artifacts_to_volume || true
  
  log "=== All Health Checks Passed ==="
  return 0
}

start() {
  ensure_dirs
  ensure_volumes
  ensure_network
  log "Starting Vault via compose..."
  docker compose -f "${COMPOSE_FILE}" up -d
  log "Waiting for health..."
  sleep 3
  docker compose -f "${COMPOSE_FILE}" ps

  # Smart start:
  # - Determine readiness based on Vault's own status (initialized/sealed)
  # - Only then consider whether local on-disk secrets are present
  #
  # In multi-repo setups, Vault can be initialized already while this repo's
  # ${SECRETS_DIR} is empty; in that case we should not claim Vault is
  # uninitialized.
  wait_vault_api_ready 10 || true

  local status_json
  status_json=$(docker exec "${CONTAINER_NAME}" vault status -format=json 2>/dev/null) || true
  if [ -z "${status_json}" ]; then
    log "⚠ Vault API not reachable yet; try again or check logs: $0 logs"
    return 0
  fi

  local initialized
  initialized=$(echo "$status_json" | grep -o '"initialized": *[a-z]*' | sed 's/.*: *//')
  if [ "$initialized" != "true" ]; then
    log "⚠ Vault needs initialization - run: $0 bootstrap"
    return 0
  fi

  if is_vault_sealed; then
    log "⚠ Vault is sealed - run: $0 unseal"
    return 0
  fi

  if [ ! -f "${SECRETS_DIR}/vault_root_token" ]; then
    log "⚠ Vault is initialized and unsealed, but local root token is missing at ${SECRETS_DIR}/vault_root_token"
    log "  If you use shared secrets volumes, seed them and/or copy tokens into ${SECRETS_DIR}."
    log "  Otherwise run: $0 bootstrap"
    return 0
  fi

  log "Vault is ready"
  # Run health check (best-effort)
  health_check || true
}

stop() {
  log "Stopping Vault..."
  docker compose -f "${COMPOSE_FILE}" down
}

status() {
  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    err "Container ${CONTAINER_NAME} not running"
    exit 1
  fi
  docker exec "${CONTAINER_NAME}" vault status
}

logs() {
  docker logs -f "${CONTAINER_NAME}"
}

init() {
  ensure_dirs

  if vault_is_initialized; then
    err "Vault is initialized; refusing re-init"
    err "Fix: if you intentionally wiped Vault data and want a fresh init, remove the Vault data volume(s) first, then re-run bootstrap."
    exit 1
  fi

  if [ -f "${SECRETS_DIR}/vault_root_token" ]; then
    log "⚠ Vault is uninitialized; ignoring stale local vault_root_token and overwriting local cache"
  fi

  log "Initializing Vault (1 key, 1 threshold)..."
  docker exec "${CONTAINER_NAME}" vault operator init -key-shares=1 -key-threshold=1 \
    | tee "${SECRETS_DIR}/vault_init_output"
  UNSEAL_KEY=$(grep 'Unseal Key 1:' "${SECRETS_DIR}/vault_init_output" | awk '{print $4}')
  ROOT_TOKEN=$(grep 'Initial Root Token:' "${SECRETS_DIR}/vault_init_output" | awk '{print $4}')
  echo -n "${UNSEAL_KEY}" > "${SECRETS_DIR}/vault_unseal_key"
  echo -n "${ROOT_TOKEN}" > "${SECRETS_DIR}/vault_root_token"
  chmod 600 "${SECRETS_DIR}/vault_unseal_key" "${SECRETS_DIR}/vault_root_token"
  log "Init complete; credentials saved in ${SECRETS_DIR}"
  
  # Unseal vault automatically
  log "Unsealing Vault..."
  docker exec "${CONTAINER_NAME}" vault operator unseal "${UNSEAL_KEY}" > /dev/null
  
  # Enable KV v2 secrets engine
  log "Enabling KV v2 secrets engine at secret/..."
  docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" vault secrets enable -path=secret kv-v2 || {
    log "KV secrets engine already enabled or error occurred"
  }
  
  # Enable AppRole auth method
  log "Enabling AppRole auth method..."
  docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" vault auth enable approle || {
    log "AppRole auth already enabled or error occurred"
  }

  # Seed bootstrap volume with fresh init artifacts (forced overwrite).
  sync_bootstrap_artifacts_to_volume true || true
}

unseal() {
  if [ ! -f "${SECRETS_DIR}/vault_unseal_key" ]; then
    err "vault_unseal_key missing; run init first"
    exit 1
  fi
  KEY=$(cat "${SECRETS_DIR}/vault_unseal_key")
  log "Unsealing Vault..."
  docker exec "${CONTAINER_NAME}" vault operator unseal "${KEY}"
}

env_cmd() {
  VAULT_TOKEN_FILE="${SECRETS_DIR}/vault_root_token"
  if [ -f "${VAULT_TOKEN_FILE}" ]; then
    export VAULT_TOKEN=$(cat "${VAULT_TOKEN_FILE}")
  fi
  export VAULT_ADDR="${VAULT_ADDR_DEFAULT}"
  echo "export VAULT_ADDR=${VAULT_ADDR}"
  [ -n "${VAULT_TOKEN:-}" ] && echo "export VAULT_TOKEN=${VAULT_TOKEN}"
}

ensure_jwt_secret() {
  # Idempotent: create JWT signing secret in Vault if it doesn't exist
  log "Ensuring JWT signing secret exists..."
  
  if [ ! -f "${SECRETS_DIR}/vault_root_token" ]; then
    err "vault_root_token not found - run init first"
    return 1
  fi
  
  local VAULT_TOKEN=$(cat "${SECRETS_DIR}/vault_root_token")
  local JWT_PATH="secret/gofr/config/jwt-signing-secret"
  
  # Check if secret already exists
  if docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN}" \
       "${CONTAINER_NAME}" vault kv get -field=value "${JWT_PATH}" >/dev/null 2>&1; then
    log "✓ JWT signing secret already exists"
    return 0
  fi
  
  # Generate and store new secret
  log "Creating JWT signing secret..."
  local JWT_SECRET=$(openssl rand -hex 32)
  if ! docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN}" \
       "${CONTAINER_NAME}" vault kv put "${JWT_PATH}" value="${JWT_SECRET}" >/dev/null 2>&1; then
    err "Failed to write JWT signing secret to Vault"
    return 1
  fi
  log "✓ JWT signing secret created at ${JWT_PATH}"
}

bootstrap() {
  log "=== Full Vault Bootstrap ==="
  
  # Build image if needed
  if ! docker images | grep -q "gofr-vault.*latest"; then
    log "Building Vault image..."
    cd "${PROJECT_ROOT}"
    docker build -f docker/Dockerfile.vault -t gofr-vault:latest .
  else
    log "Vault image exists"
  fi
  
  # Ensure Vault is running and decide init based on live Vault state (not local token file presence).
  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    start
  fi

  log "Waiting for Vault API to become reachable..."
  if ! wait_vault_api_ready 20; then
    err "Vault API did not become reachable after start"
    return 1
  fi

  if ! vault_is_initialized; then
    log "Vault is uninitialized; running init..."
    init
  else
    log "Vault is already initialized"

    # Always check if sealed and unseal if needed (using reliable JSON check)
    log "Waiting for Vault API to stabilize..."
    wait_vault_api_ready 15 || true
    if is_vault_sealed; then
      log "Vault is sealed — unsealing..."
      unseal
      sleep 2
      if is_vault_sealed; then
        err "Vault is still sealed after unseal attempt"
        return 1
      fi
    else
      log "Vault is already unsealed"
    fi
  fi

  # Reconcile missing/stale local token for the "already initialized" case.
  reconcile_local_bootstrap_artifacts || return 1

  # Validate root token is usable before configuring anything.
  if ! vault_token_valid "$(cat "${SECRETS_DIR}/vault_root_token" 2>/dev/null || true)"; then
    err "Local vault_root_token is present but invalid/revoked: ${SECRETS_DIR}/vault_root_token"
    err "Fix: seed ${BOOTSTRAP_VOLUME} with a valid token or re-run Vault init/bootstrap."
    return 1
  fi

  # Verify Vault API is truly ready before configuring
  log "Confirming Vault API is ready..."
  if ! wait_vault_api_ready 10; then
    err "Vault API not ready — cannot continue with bootstrap"
    return 1
  fi
  log "✓ Vault API is responsive and unsealed"

  # Ensure KV v2 secrets engine is enabled
  local VAULT_TOKEN_VAL
  VAULT_TOKEN_VAL=$(cat "${SECRETS_DIR}/vault_root_token")
  if ! docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN_VAL}" \
       "${CONTAINER_NAME}" vault secrets list 2>/dev/null | grep -q "^secret/"; then
    log "Enabling KV v2 secrets engine at secret/..."
    docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN_VAL}" \
      "${CONTAINER_NAME}" vault secrets enable -path=secret kv-v2 || {
      err "Failed to enable KV secrets engine"
      return 1
    }
  fi
  log "✓ KV v2 secrets engine enabled"

  # Ensure AppRole auth method is enabled
  if ! docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN_VAL}" \
       "${CONTAINER_NAME}" vault auth list 2>/dev/null | grep -q "approle/"; then
    log "Enabling AppRole auth method..."
    docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="${VAULT_TOKEN_VAL}" \
      "${CONTAINER_NAME}" vault auth enable approle || {
      err "Failed to enable AppRole auth"
      return 1
    }
  fi
  log "✓ AppRole auth method enabled"

  # Ensure JWT signing secret exists (idempotent)
  ensure_jwt_secret || {
    err "Failed to ensure JWT signing secret — is Vault unsealed?"
    return 1
  }
  
  # Run auth bootstrap
  log "Bootstrapping authentication (JWT, groups, tokens)..."
  export VAULT_ADDR="${VAULT_ADDR_DEFAULT}"
  export VAULT_TOKEN=$(cat "${SECRETS_DIR}/vault_root_token")
  cd "${PROJECT_ROOT}"
  
  # Check if Python script exists
  if [ -f "${PROJECT_ROOT}/scripts/bootstrap_vault.py" ]; then
    # Try uv first, fallback to python3
    if command -v uv >/dev/null 2>&1; then
      uv run scripts/bootstrap_vault.py
    else
      python3 scripts/bootstrap_vault.py
    fi
  else
    err "bootstrap_vault.py not found at ${PROJECT_ROOT}/scripts/bootstrap_vault.py"
    exit 1
  fi
  
  log "=== Bootstrap Complete ==="
  log "Secrets saved to: ${SECRETS_DIR}"
  log "  - vault_root_token"
  log "  - vault_unseal_key"
  log "  - bootstrap_tokens.json"
  log ""
  log "To use Vault, run:"
  log "  source <(${SCRIPT_DIR}/manage_vault.sh env)"
  log ""
  
  # Run final health check
  health_check

  # Keep bootstrap volume synced (best-effort)
  sync_bootstrap_artifacts_to_volume || true
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  logs) logs ;;
  init) start; init ;;
  unseal) unseal ;;
  env) env_cmd ;;
  jwt-secret) ensure_jwt_secret ;;
  bootstrap) bootstrap ;;
  health) health_check ;;
  *)
    echo "Usage: $0 {start|stop|status|logs|init|unseal|env|jwt-secret|bootstrap|health}"
    exit 1
    ;;
esac
