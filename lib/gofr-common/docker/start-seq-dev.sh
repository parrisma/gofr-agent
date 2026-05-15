#!/bin/bash
# =============================================================================
# GOFR SEQ Development Start Script (Ephemeral)
# =============================================================================
# Usage:
#   ./lib/gofr-common/docker/start-seq-dev.sh           # Build + start
#   ./lib/gofr-common/docker/start-seq-dev.sh --down    # Stop/remove container
#
# Behavior:
# - Always builds image before start
# - Ensures gofr-net exists (creates only if missing)
# - Ephemeral runtime: no persistent volumes are used
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
COMPOSE_FILE="${SCRIPT_DIR}/seq-compose.dev.yml"

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
      echo "  --down   Stop and remove SEQ dev container"
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

# Use test/dev ports by default to avoid conflicts with production.
export GOFR_SEQ_INGEST_PORT="${GOFR_SEQ_INGEST_PORT_TEST:-5441}"
export GOFR_SEQ_UI_PORT="${GOFR_SEQ_UI_PORT_TEST:-5480}"

cd "$SCRIPT_DIR"

if [[ "$DOWN_ONLY" == true ]]; then
  log_info "Stopping SEQ dev stack..."
  docker compose -f "$COMPOSE_FILE" down
  log_ok "SEQ dev stack stopped"
  exit 0
fi

log_info "Ensuring gofr-net network exists..."
if ! docker network inspect gofr-net >/dev/null 2>&1; then
  docker network create gofr-net >/dev/null
  log_ok "Created gofr-net"
else
  log_ok "gofr-net already exists"
fi

log_info "Building SEQ dev image..."
docker compose -f "$COMPOSE_FILE" build --pull
log_ok "SEQ dev image built"

log_info "Starting SEQ dev stack (ephemeral)..."
docker compose -f "$COMPOSE_FILE" up -d

log_ok "SEQ dev is running"
echo ""
echo "SEQ ingestion: http://localhost:${GOFR_SEQ_INGEST_PORT}"
echo "SEQ UI:        http://localhost:${GOFR_SEQ_UI_PORT}"
