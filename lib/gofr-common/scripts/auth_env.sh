#!/bin/bash
# =============================================================================
# Auth Env Helper (Vault)
# =============================================================================
# Mint a short-lived operator token (least privilege via policy) and emit
# environment variables in .env format for easy sourcing:
#   source <(./auth_env.sh)
#
# Options:
#   --docker              Use Docker hostnames (gofr-vault) instead of localhost
#   --vault-addr URL      Vault address (default: http://localhost:8201, or http://gofr-vault:8201 with --docker)
#   --root-token-file F   Root token file (default: ../../secrets/vault_root_token)
#   --policy NAME         Policy for minted token (default: gofr-mcp-policy)
#   --ttl DURATION        Token TTL (default: 1h)
#
# Output (stdout):
#   VAULT_ADDR=...
#   VAULT_TOKEN=...      # short-lived token (not root)
#   GOFR_JWT_SECRET=...
#
# Note: requires jq plus either vault CLI on host or docker access to gofr-vault.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ -> gofr-common/ -> lib/ -> repo root
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

USE_DOCKER=false
VAULT_ADDR="http://localhost:8201"
ROOT_TOKEN_FILE="${WORKSPACE_ROOT}/secrets/vault_root_token"
POLICY="gofr-mcp-policy"
TTL="1h"

vault_cmd() {
  if command -v vault >/dev/null 2>&1; then
    VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$ROOT_TOKEN" vault "$@"
  else
    # Fallback: run inside vault container
    if ! docker ps --format '{{.Names}}' | grep -q '^gofr-vault$'; then
        echo "Vault CLI not found and gofr-vault container not running" >&2
        return 1
    fi
    # Inside container Vault listens on 8201
    docker exec -e VAULT_ADDR="http://127.0.0.1:8201" -e VAULT_TOKEN="$ROOT_TOKEN" gofr-vault vault "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker)
      USE_DOCKER=true; shift ;;
    --vault-addr)
      VAULT_ADDR="$2"; shift 2 ;;
    --root-token-file)
      ROOT_TOKEN_FILE="$2"; shift 2 ;;
    --policy)
      POLICY="$2"; shift 2 ;;
    --ttl)
      TTL="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,80p' "$0"; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Apply docker hostname if requested and not explicitly overridden
if [[ "$USE_DOCKER" == true && "$VAULT_ADDR" == "http://localhost:8201" ]]; then
  # Load ports from gofr_ports.env
  PORTS_FILE="${WORKSPACE_ROOT}/lib/gofr-common/config/gofr_ports.env"
  if [[ -f "$PORTS_FILE" ]]; then
    source "$PORTS_FILE"
    VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
  else
    VAULT_ADDR="http://gofr-vault:8201"
  fi
fi

if [[ ! -f "$ROOT_TOKEN_FILE" ]]; then
  echo "Root token file not found: $ROOT_TOKEN_FILE" >&2
  exit 1
fi

ROOT_TOKEN=$(<"$ROOT_TOKEN_FILE")

NEW_TOKEN=$(vault_cmd token create -policy="$POLICY" -ttl="$TTL" -format=json \
  | jq -r '.auth.client_token')

if [[ -z "$NEW_TOKEN" || "$NEW_TOKEN" == "null" ]]; then
  echo "Failed to mint operator token" >&2
  exit 1
fi

JWT_SECRET=$(vault_cmd kv get -field=value secret/gofr/config/jwt-signing-secret)

if [[ -z "$JWT_SECRET" ]]; then
  echo "Failed to read JWT secret from Vault" >&2
  exit 1
fi

cat <<EOF
export VAULT_ADDR=$VAULT_ADDR
export VAULT_TOKEN=$NEW_TOKEN
export GOFR_JWT_SECRET=$JWT_SECRET
EOF
