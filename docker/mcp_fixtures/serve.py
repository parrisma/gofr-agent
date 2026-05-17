"""Standalone entry-point for test MCP fixture services.

Usage:
    python docker/mcp_fixtures/serve.py --service instruments --port 8500
    python docker/mcp_fixtures/serve.py --service clients    --port 8501
    python docker/mcp_fixtures/serve.py --service trades     --port 8502
    python docker/mcp_fixtures/serve.py --service analytics  --port 8503
"""

from __future__ import annotations

import argparse
import importlib

import uvicorn
from gofr_common.web import AuthHeaderMiddleware

from app.config import GofrAgentConfig
from app.transport_security import apply_transport_security

SERVICES: dict[str, str] = {
    "instruments": "tests.fixtures.mcp_services.instruments",
    "clients": "tests.fixtures.mcp_services.clients",
    "trades": "tests.fixtures.mcp_services.trades",
    "analytics": "tests.fixtures.mcp_services.analytics",
}

DOCKER_ALLOWED_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "gofr-agent-mcp-instruments:*",
    "gofr-agent-mcp-clients:*",
    "gofr-agent-mcp-trades:*",
    "gofr-agent-mcp-analytics:*",
    "mcp-instruments:*",
    "mcp-clients:*",
    "mcp-trades:*",
    "mcp-analytics:*",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a test MCP fixture service")
    parser.add_argument(
        "--service",
        required=True,
        choices=list(SERVICES),
        help="Which fixture service to start",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, required=True, help="TCP port to listen on")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
    )
    args = parser.parse_args()

    mod = importlib.import_module(SERVICES[args.service])
    apply_transport_security(mod.mcp, GofrAgentConfig(mcp_allowed_hosts=DOCKER_ALLOWED_HOSTS))
    app = AuthHeaderMiddleware(mod.mcp.streamable_http_app())

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
