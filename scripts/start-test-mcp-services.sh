#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST_PATH="${PROJECT_ROOT}/tmp/fixture-services.yml"

usage() {
    cat <<EOF
Start the Docker Swarm MCP fixture services and write a manifest that the real
gofr-agent server can consume.

Usage:
  $(basename "$0") [--manifest-path PATH]

Options:
  --manifest-path PATH       Output manifest path (default: ${MANIFEST_PATH})
  -h, --help                 Show this help

This script does two things:
  1. Starts the fixture services via docker/fixtures-stack.sh start
  2. Writes a services manifest for the real server

After it completes, start the real server with:
  ${PROJECT_ROOT}/scripts/start-real-server.sh --services-file <manifest-path>
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest-path)
            MANIFEST_PATH="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

mkdir -p "$(dirname "${MANIFEST_PATH}")"

"${PROJECT_ROOT}/docker/fixtures-stack.sh" start

cat >"${MANIFEST_PATH}" <<'EOF'
services:
  - name: instruments
    url: http://gofr-agent-mcp-instruments:8500/mcp
    token: dev-admin-token
    description: Instrument reference data, spot prices, and OHLCV history
    hub_callback_token: dev-fixtures-hub-token

  - name: clients
    url: http://gofr-agent-mcp-clients:8501/mcp
    token: dev-admin-token
    description: Client master data, holdings, watchlists, and mandates

  - name: trades
    url: http://gofr-agent-mcp-trades:8502/mcp
    token: dev-admin-token
    description: Trade blotter retrieval, aggregation, and realised P&L

  - name: analytics
    url: http://gofr-agent-mcp-analytics:8503/mcp
    token: dev-admin-token
    description: Derived analytics for market data, positions, and executions
    hub_callback_token: dev-fixtures-hub-token
EOF

echo "======================================================================="
echo "Fixture MCP services are running"
echo "======================================================================="
echo "Manifest written to: ${MANIFEST_PATH}"
echo ""
echo "Start the real server with:"
echo "  ${PROJECT_ROOT}/scripts/start-real-server.sh --services-file ${MANIFEST_PATH}"