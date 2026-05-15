#!/bin/bash
# GOFR platform bootstrap helper
# Idempotent: checks state before acting and provides guided prompts.

# Hardening:
# - Use errtrace so ERR trap fires inside functions and subshells.
# - Restrictive umask so any created files (including logs) are not world-readable.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${COMMON_ROOT}/../.." && pwd)"

PROJECT_ROOT="${WORKSPACE_ROOT}"
if [[ ! -d "${WORKSPACE_ROOT}/lib/gofr-common" ]]; then
  PROJECT_ROOT="${COMMON_ROOT}"
fi

ASSUME_YES=false
TRACE=false
LOG_FILE=""
SCRIPT_START_TS=""
NO_LOG=false
STEP=0
FORCE_REBUILD=false

usage() {
  cat << 'EOF'
GOFR Platform Bootstrap (shared infrastructure)

Usage:
  ./lib/gofr-common/scripts/bootstrap_platform.sh [--yes] [--trace] [--log-file PATH] [--no-log] [--force-rebuild]

Options:
  --yes, -y    Run non-interactively and auto-accept prompts
  --trace      Enable bash xtrace for detailed logs
  --log-file   Write logs to a specific file path
  --no-log     Disable file logging (stdout/stderr only)
  --force-rebuild  Remove shared images/volumes before rebuild (DESTRUCTIVE)
  --help, -h   Show this help

This script will:
  - Build gofr-base image (if missing)
  - Build gofr-vault image (if missing)
  - Create shared Docker networks (gofr-net, gofr-test-net)
  - Create Vault volumes (gofr-vault-data/logs/file)
  - Start and bootstrap Vault (init, unseal, auth, JWT)
  - Seed secrets volumes (if project script exists)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true
      shift
      ;;
    --trace)
      TRACE=true
      shift
      ;;
    --log-file)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Missing value for --log-file" >&2
        usage
        exit 1
      fi
      LOG_FILE="$2"
      shift 2
      ;;
    --no-log)
      NO_LOG=true
      shift
      ;;
    --force-rebuild)
      FORCE_REBUILD=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
info() { echo "[$(timestamp)] [INFO] $*"; }
ok() { echo "[$(timestamp)] [OK]   $*"; }
warn() { echo "[$(timestamp)] [WARN] $*"; }
err() { echo "[$(timestamp)] [ERR]  $*" >&2; }

die() {
  err "$1"
  if [[ -n "${2:-}" ]]; then
    err "Fix: $2"
  fi
  exit 1
}

setup_logging() {
  SCRIPT_START_TS="$(date +%s)"
  if [[ "$NO_LOG" == "true" ]]; then
    LOG_FILE=""
    info "File logging disabled."
  else
    if [[ -z "$LOG_FILE" ]]; then
      LOG_FILE="${PROJECT_ROOT}/logs/bootstrap_platform_$(date +%Y%m%d_%H%M%S).log"
    fi

    local log_dir
    log_dir="$(dirname "$LOG_FILE")"
    if ! mkdir -p "$log_dir"; then
      warn "Failed to create log directory: $log_dir"
      warn "Logging will continue on stdout/stderr only."
      LOG_FILE=""
    else
      # Ensure log file exists with restrictive permissions before tee attaches.
      : > "$LOG_FILE" || true
      chmod 600 "$LOG_FILE" 2>/dev/null || true
      info "Note: bootstrap logs may include sensitive output depending on downstream scripts."
      exec > >(tee -a "$LOG_FILE") 2>&1
      info "Logging to ${LOG_FILE}"
    fi
  fi

  if [[ "$TRACE" == "true" ]]; then
    export PS4='+ [$(date +%H:%M:%S)] [TRACE] '
    set -x
    info "Trace enabled."
  fi
}

on_error() {
  local exit_code=$?
  local line_no=${BASH_LINENO[0]}
  local cmd=${BASH_COMMAND}
  err "Command failed (exit ${exit_code}) at line ${line_no}: ${cmd}"
  if [[ -n "$LOG_FILE" ]]; then
    err "Fix: review ${LOG_FILE} or re-run with --trace for more details."
  else
    err "Fix: re-run with --log-file PATH or --trace for more details."
  fi
  exit "$exit_code"
}

on_exit() {
  local exit_code=$?
  if [[ -n "$SCRIPT_START_TS" ]]; then
    local end_ts
    end_ts="$(date +%s)"
    local elapsed
    elapsed=$((end_ts - SCRIPT_START_TS))
    info "Total elapsed time: ${elapsed}s"
  fi
  exit "$exit_code"
}

run_step() {
  local label="$1"
  shift
  STEP=$((STEP + 1))
  info "Step ${STEP}: ${label}"
  local step_start
  step_start="$(date +%s)"
  "$@"
  local status=$?
  local step_end
  step_end="$(date +%s)"
  info "Step ${STEP} completed in $((step_end - step_start))s (status ${status})"
  return "$status"
}

confirm() {
  local prompt="$1"
  if [[ "$ASSUME_YES" == "true" ]]; then
    info "Auto-accept: ${prompt}"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    warn "No interactive input available. Skipping: ${prompt}"
    return 1
  fi
  read -r -p "${prompt} [y/N]: " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    die "Docker is not installed or not on PATH." \
      "Install Docker Engine and ensure the 'docker' command is available."
  fi
  if ! docker info >/dev/null 2>&1; then
    die "Docker is not running or not reachable." \
      "Start Docker, ensure your user can access /var/run/docker.sock, and retry."
  fi
  if ! docker compose version >/dev/null 2>&1; then
    die "Docker Compose plugin not available." \
      "Install the Compose plugin (docker compose) and retry."
  fi
}

ensure_submodule() {
  if [[ -d "${PROJECT_ROOT}/lib/gofr-common" ]]; then
    ok "gofr-common submodule present."
    return 0
  fi

  if ! command -v git >/dev/null 2>&1; then
    die "git is not installed or not on PATH." \
      "Install Git and ensure it is available in your PATH."
  fi

  if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
    die "This does not look like a git clone (missing .git)." \
      "Clone the project repo first, then rerun this script."
  fi

  info "gofr-common submodule not found."
  info "This script assumes a fresh git clone and will initialize submodules."
  if ! confirm "Run 'git submodule update --init --recursive' now?"; then
    warn "Skipping submodule init. The bootstrap cannot continue without gofr-common."
    exit 1
  fi

  (cd "${PROJECT_ROOT}" && git submodule update --init --recursive)

  if [[ ! -d "${PROJECT_ROOT}/lib/gofr-common" ]]; then
    die "Submodule init completed but lib/gofr-common is still missing." \
      "Run 'git submodule update --init --recursive' manually and retry."
  fi

  ok "Submodules initialized."
}

build_base_image() {
  if docker image inspect gofr-base:latest >/dev/null 2>&1; then
    ok "Base image exists: gofr-base:latest"
    return 0
  fi

  info "Base image gofr-base:latest is missing."
  info "This image is shared by all GOFR projects."
  if ! confirm "Build gofr-base:latest now?"; then
    warn "Skipping base image build. Dependent builds may fail."
    return 1
  fi

  if [[ -f "${COMMON_ROOT}/docker/build-base.sh" ]]; then
    (cd "${COMMON_ROOT}/docker" && bash build-base.sh)
  else
    (cd "${COMMON_ROOT}" && docker build -f docker/Dockerfile.base -t gofr-base:latest .)
  fi

  ok "Base image built: gofr-base:latest"
}

build_vault_image() {
  if docker image inspect gofr-vault:latest >/dev/null 2>&1; then
    ok "Vault image exists: gofr-vault:latest"
    return 0
  fi

  info "Vault image gofr-vault:latest is missing."
  info "This image is shared by all GOFR projects."
  if ! confirm "Build gofr-vault:latest now?"; then
    warn "Skipping Vault image build. Vault bootstrap may fail."
    return 1
  fi

  local project_build="${PROJECT_ROOT}/docker/build-vault.sh"
  if [[ -f "$project_build" ]]; then
    (cd "${PROJECT_ROOT}" && bash "$project_build")
    ok "Vault image built via project script."
    return 0
  fi

  warn "Project build-vault.sh not found. Using common Dockerfile.vault instead."
  warn "If this fails due to BuildKit requirements, use your project script instead."
  (cd "${COMMON_ROOT}" && docker build -f docker/Dockerfile.vault -t gofr-vault:latest .)
  ok "Vault image built via common Dockerfile."
}

ensure_networks() {
  local networks=("gofr-net" "gofr-test-net")
  local missing=()

  for net in "${networks[@]}"; do
    if ! docker network inspect "$net" >/dev/null 2>&1; then
      missing+=("$net")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Docker networks exist: gofr-net, gofr-test-net"
    return 0
  fi

  info "Missing Docker networks: ${missing[*]}"
  info "These networks are shared across all GOFR projects."
  if ! confirm "Create missing networks now?"; then
    warn "Skipping network creation. Containers may not connect properly."
    return 1
  fi

  for net in "${missing[@]}"; do
    docker network create "$net" >/dev/null
    ok "Created network: $net"
  done
}

ensure_volumes() {
  local volumes=("gofr-vault-data" "gofr-vault-logs" "gofr-vault-file" "gofr-vault-bootstrap")
  local missing=()

  for vol in "${volumes[@]}"; do
    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
      missing+=("$vol")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Vault volumes exist: ${volumes[*]}"
    return 0
  fi

  info "Missing Vault volumes: ${missing[*]}"
  info "These volumes store Vault data and logs across restarts."
  if ! confirm "Create missing Vault volumes now?"; then
    warn "Skipping volume creation. Vault will not persist data."
    return 1
  fi

  for vol in "${missing[@]}"; do
    docker volume create "$vol" >/dev/null
    ok "Created volume: $vol"
  done
}

force_rebuild_cleanup() {
  if [[ "${FORCE_REBUILD}" != "true" ]]; then
    return 0
  fi

  warn "--force-rebuild selected: this will DELETE shared images and volumes."
  warn "This may affect other GOFR projects on the same Docker host."
  if ! confirm "Proceed with force rebuild cleanup?"; then
    die "Refusing to run with --force-rebuild without confirmation." "Re-run without --force-rebuild or pass --yes to auto-accept."
  fi

  local manage_script="${COMMON_ROOT}/scripts/manage_vault.sh"
  if [[ -f "${manage_script}" ]]; then
    info "Stopping Vault (best-effort) before removing volumes..."
    bash "${manage_script}" stop >/dev/null 2>&1 || true
  fi

  info "Removing images (best-effort): gofr-base:latest, gofr-vault:latest"
  docker rmi -f gofr-base:latest >/dev/null 2>&1 || true
  docker rmi -f gofr-vault:latest >/dev/null 2>&1 || true

  info "Removing Vault volumes (best-effort): gofr-vault-data, gofr-vault-logs, gofr-vault-file, gofr-vault-bootstrap"
  for vol in gofr-vault-data gofr-vault-logs gofr-vault-file gofr-vault-bootstrap; do
    docker volume rm -f "${vol}" >/dev/null 2>&1 || true
  done

  ok "Force rebuild cleanup complete."
}

start_and_bootstrap_vault() {
  local manage_script="${COMMON_ROOT}/scripts/manage_vault.sh"
  if [[ ! -f "$manage_script" ]]; then
    die "manage_vault.sh not found at ${manage_script}" \
      "Re-run submodule init or verify gofr-common scripts directory."
  fi

  info "Starting Vault (if not running)..."
  bash "$manage_script" start

  info "Checking Vault health..."
  if bash "$manage_script" health >/dev/null 2>&1; then
    ok "Vault is healthy and bootstrapped."
    return 0
  fi

  local health_status=$?
  if [[ $health_status -eq 2 ]]; then
    warn "Vault is running but auth is not bootstrapped."
  else
    warn "Vault is not healthy or not initialized."
  fi

  info "Bootstrap performs init, unseal, KV setup, AppRole auth, JWT secret, and groups/tokens."
  if ! confirm "Run Vault bootstrap now?"; then
    warn "Skipping Vault bootstrap. Platform setup is incomplete."
    return 1
  fi

  bash "$manage_script" bootstrap
  ok "Vault bootstrap completed."
}

seed_secrets_volume() {
  local seed_script="${PROJECT_ROOT}/scripts/migrate_secrets_to_volume.sh"
  if [[ ! -f "$seed_script" ]]; then
    warn "Project secrets seeding script not found at ${seed_script}."
    warn "Fix: run it manually if your project provides one to seed gofr-secrets volumes."
    return 1
  fi

  info "Seeding secrets into Docker volumes (gofr-secrets, gofr-secrets-test)."
  info "This should copy ONLY runtime credentials (service_creds/*.json) into shared volumes."
  info "Hardening: do NOT copy Vault bootstrap artifacts (root token/unseal key) into runtime volumes."
  if ! confirm "Run secrets seeding now?"; then
    warn "Skipping secrets seeding. Containers may not authenticate."
    return 1
  fi

  (cd "${PROJECT_ROOT}" && bash "$seed_script")
  ok "Secrets volumes seeded."
}

main() {
  trap on_error ERR
  trap on_exit EXIT
  setup_logging

  info "GOFR platform bootstrap (shared infrastructure)"
  info "Common root: ${COMMON_ROOT}"
  info "Project root: ${PROJECT_ROOT}"
  echo ""

  run_step "Validate Docker availability" require_docker
  run_step "Ensure submodule" ensure_submodule

  run_step "Force rebuild cleanup" force_rebuild_cleanup || true

  run_step "Build base image" build_base_image || true
  run_step "Build vault image" build_vault_image || true
  run_step "Ensure networks" ensure_networks || true
  run_step "Ensure volumes" ensure_volumes || true
  run_step "Start and bootstrap Vault" start_and_bootstrap_vault
  run_step "Seed secrets volume" seed_secrets_volume || true

  echo ""
  ok "Platform bootstrap complete."
  info "Next: follow your project-specific Getting Started guide."
}

main
