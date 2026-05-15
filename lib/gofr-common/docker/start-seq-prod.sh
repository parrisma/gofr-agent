#!/bin/bash
# =============================================================================
# GOFR SEQ Production Start Script (Persistent)
# =============================================================================
# Usage:
#   ./lib/gofr-common/docker/start-seq-prod.sh
#   ./lib/gofr-common/docker/start-seq-prod.sh --down
#
# Behavior:
# - Always builds image before start
# - Ensures gofr-net exists (creates only if missing)
# - Ensures gofr-seq-data volume exists (creates only if missing)
# - Loads SEQ admin password from Vault (creates it if missing)
# - Never recreates existing network/volume resources
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PORTS_FILE="${COMMON_ROOT}/config/gofr_ports.env"
COMPOSE_FILE="${SCRIPT_DIR}/seq-compose.prod.yml"
COMPOSE_PROJECT_NAME="gofr-seq-prod"
SECRETS_DIR="${COMMON_ROOT}/secrets"
VAULT_ROOT_TOKEN_FILE="${SECRETS_DIR}/vault_root_token"
VAULT_CONTAINER="gofr-vault"
SEQ_ADMIN_PASSWORD_PATH="secret/gofr/config/seq/admin-password"

DOWN_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --down)
      DOWN_ONLY=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--down]"
      echo ""
      echo "Options:"
      echo "  --down   Stop and remove SEQ prod container"
      echo ""
      echo "Password source (prod):"
      echo "  - Reads from Vault path: ${SEQ_ADMIN_PASSWORD_PATH}"
      echo "  - Creates password in Vault if missing"
      echo "  - Uses root token file: ${VAULT_ROOT_TOKEN_FILE}"
      echo "Optional env:"
      echo "  GOFR_SEQ_ADMIN_USERNAME (default: admin)"
      echo "  GOFR_SEQ_BIND_ADDR      (default: 127.0.0.1)"
      echo "  GOFR_SEQ_BASE_IMAGE     (default: datalust/seq:latest)"
      exit 0
      ;;
    *)
      log_err "Unknown option: $1"
      exit 1
      ;;
  esac
done

log_info "Checking Docker prerequisites..."
command -v docker >/dev/null 2>&1 || { log_err "docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { log_err "docker compose not available"; exit 1; }
log_ok "Docker + Compose available"

if [[ ! -f "$PORTS_FILE" ]]; then
  log_err "Missing ports file: $PORTS_FILE"
  exit 1
fi

set -a
source "$PORTS_FILE"
set +a

export GOFR_SEQ_INGEST_PORT="${GOFR_SEQ_INGEST_PORT:-5341}"
export GOFR_SEQ_UI_PORT="${GOFR_SEQ_UI_PORT:-5380}"
export GOFR_SEQ_BIND_ADDR="${GOFR_SEQ_BIND_ADDR:-127.0.0.1}"
export GOFR_VAULT_PORT="${GOFR_VAULT_PORT:-8201}"

vault_get_field() {
  local path="$1"
  local field="$2"
  local token="$3"
  docker exec \
    -e VAULT_ADDR="http://127.0.0.1:${GOFR_VAULT_PORT}" \
    -e VAULT_TOKEN="$token" \
    "$VAULT_CONTAINER" \
    vault kv get -field="$field" "$path" 2>/dev/null
}

vault_put_value() {
  local path="$1"
  local value="$2"
  local token="$3"
  docker exec \
    -e VAULT_ADDR="http://127.0.0.1:${GOFR_VAULT_PORT}" \
    -e VAULT_TOKEN="$token" \
    "$VAULT_CONTAINER" \
    vault kv put "$path" value="$value" >/dev/null
}

seq_compose() {
  docker compose --project-name "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cd "$SCRIPT_DIR"

if [[ "$DOWN_ONLY" == true ]]; then
  log_info "Stopping SEQ prod stack..."
  seq_compose down
  log_ok "SEQ prod stack stopped"
  exit 0
fi

if [[ ! -f "$VAULT_ROOT_TOKEN_FILE" ]]; then
  log_err "Vault root token not found: $VAULT_ROOT_TOKEN_FILE"
  log_err "Initialize/bootstrap Vault first (shared gofr-common Vault)."
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${VAULT_CONTAINER}$"; then
  log_err "Vault container '${VAULT_CONTAINER}' is not running"
  log_err "Start shared Vault first, then rerun this script."
  exit 1
fi

VAULT_TOKEN="$(cat "$VAULT_ROOT_TOKEN_FILE")"

log_info "Resolving SEQ admin password from Vault..."
if [[ -n "${GOFR_SEQ_ADMIN_PASSWORD:-}" ]]; then
  log_warn "GOFR_SEQ_ADMIN_PASSWORD is set in environment; writing it to Vault path ${SEQ_ADMIN_PASSWORD_PATH}"
  vault_put_value "$SEQ_ADMIN_PASSWORD_PATH" "$GOFR_SEQ_ADMIN_PASSWORD" "$VAULT_TOKEN"
  log_ok "SEQ admin password stored in Vault"
else
  EXISTING_SEQ_PASSWORD="$(vault_get_field "$SEQ_ADMIN_PASSWORD_PATH" value "$VAULT_TOKEN" || true)"
  if [[ -n "$EXISTING_SEQ_PASSWORD" ]]; then
    export GOFR_SEQ_ADMIN_PASSWORD="$EXISTING_SEQ_PASSWORD"
    log_ok "Loaded SEQ admin password from Vault"
  else
    GENERATED_SEQ_PASSWORD="$(openssl rand -hex 32)"
    vault_put_value "$SEQ_ADMIN_PASSWORD_PATH" "$GENERATED_SEQ_PASSWORD" "$VAULT_TOKEN"
    export GOFR_SEQ_ADMIN_PASSWORD="$GENERATED_SEQ_PASSWORD"
    log_ok "Created SEQ admin password in Vault at ${SEQ_ADMIN_PASSWORD_PATH}"
  fi
fi

log_info "Ensuring gofr-net network exists..."
if ! docker network inspect gofr-net >/dev/null 2>&1; then
  docker network create gofr-net >/dev/null
  log_ok "Created gofr-net"
else
  log_ok "gofr-net already exists"
fi

log_info "Ensuring gofr-seq-data volume exists..."
if ! docker volume inspect gofr-seq-data >/dev/null 2>&1; then
  docker volume create gofr-seq-data >/dev/null
  log_ok "Created gofr-seq-data"
else
  log_ok "gofr-seq-data already exists"
fi

# Reconcile legacy/stale container-name conflicts from older compose project names.
if docker inspect gofr-seq >/dev/null 2>&1; then
  EXISTING_PROJECT="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' gofr-seq 2>/dev/null || true)"
  if [[ "$EXISTING_PROJECT" != "$COMPOSE_PROJECT_NAME" ]]; then
    log_warn "Removing stale gofr-seq container from project '${EXISTING_PROJECT:-unknown}'"
    docker rm -f gofr-seq >/dev/null
    log_ok "Removed stale gofr-seq container"
  fi
fi

log_info "Building SEQ prod image..."
seq_compose build --pull
log_ok "SEQ prod image built"

log_info "Starting SEQ prod stack..."
seq_compose up -d

log_ok "SEQ prod is running"
echo ""
echo "SEQ ingestion: http://${GOFR_SEQ_BIND_ADDR}:${GOFR_SEQ_INGEST_PORT}"
echo "SEQ UI:        http://${GOFR_SEQ_BIND_ADDR}:${GOFR_SEQ_UI_PORT}"
