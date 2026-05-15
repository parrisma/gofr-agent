"""gofr-agent MCP server entry point.

Usage::

    uv run python app/main_mcp.py [OPTIONS]
    uv run python -m app.main_mcp [OPTIONS]

Options are also loaded from environment variables prefixed ``GOFR_AGENT_``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

import uvicorn
from gofr_common.web import AuthHeaderMiddleware

from app.agent.agent import GofrAgent
from app.auth import get_auth_service
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="gofr-agent — reasoning agent MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("GOFR_AGENT_HOST", "0.0.0.0"),  # noqa: S104
        help="Bind host.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GOFR_AGENT_MCP_PORT", "8090")),
        help="Bind port.",
    )
    parser.add_argument(
        "--services-file",
        default=os.environ.get("GOFR_AGENT_SERVICES_FILE", "services.yml"),
        help="Path to the services YAML manifest.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("GOFR_AGENT_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level.",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=int(os.environ.get("GOFR_AGENT_POOL_SIZE", "3")),
        help="Number of concurrent connections per service.",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("GOFR_AGENT_LLM_MODEL", "openai:gpt-4o-mini"),
        help="pydantic-ai model string.",
    )
    return parser.parse_args(argv)


async def _run_server(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = GofrAgentConfig(
        session_pool_size=args.pool_size,
        llm_model=args.llm_model,
    )

    # Load services manifest
    services_path = Path(args.services_file)
    if services_path.exists():
        manifest = ServicesManifest.from_yaml(services_path)
        logger.info("Loaded %d service(s) from '%s'.", len(manifest.services), services_path)
    else:
        manifest = ServicesManifest(services=[])
        logger.warning(
            "Services file '%s' not found — starting with no downstream services.",
            services_path,
        )

    # Bootstrap
    registry = ServiceRegistry(config)
    await registry.load_manifest(manifest)

    auth_service = get_auth_service()

    agent = GofrAgent(config, registry)
    agent.build()

    session_store = SessionStore(ttl_minutes=config.session_ttl_minutes)
    await session_store.start_ttl_sweep()

    mcp = create_mcp_server(config, registry, agent, session_store, auth_service)

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        logger.info("Signal %d received — shutting down.", sig)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    logger.info("Starting gofr-agent MCP server on %s:%d", args.host, args.port)

    server_config = uvicorn.Config(
        AuthHeaderMiddleware(mcp.streamable_http_app()),
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
    )
    server = uvicorn.Server(server_config)

    serve_task = asyncio.create_task(server.serve())
    await shutdown_event.wait()

    logger.info("Stopping registry…")
    await registry.shutdown()
    server.should_exit = True
    await serve_task


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    args = _parse_args(argv)
    asyncio.run(_run_server(args))


if __name__ == "__main__":  # pragma: no cover
    main()
