#!/usr/bin/env python3
"""Interactive fixture chat launcher for manual gofr-agent testing.

Starts the Docker Swarm fixture services, boots a local gofr-agent MCP server
configured against those services, then opens a small prompt loop that calls the
existing CLI with a shared session ID.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from gofr_common.web import AuthHeaderMiddleware
from mcp.server.transport_security import TransportSecuritySettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.agent import GofrAgent
from app.auth._dev_auth_service import DevAuthService
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_STACK = PROJECT_ROOT / "docker" / "fixtures-stack.sh"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
DEV_TOKEN = "dev-admin-token"
DEFAULT_SESSION = "fixture-chat"

SERVICE_PORTS = {
    "instruments": 8500,
    "clients": 8501,
    "trades": 8502,
    "analytics": 8503,
}

OVERLAY_HOSTS = {
    "instruments": "gofr-agent-mcp-instruments",
    "clients": "gofr-agent-mcp-clients",
    "trades": "gofr-agent-mcp-trades",
    "analytics": "gofr-agent-mcp-analytics",
}


class AgentServerThread(threading.Thread):
    """Run uvicorn in a daemon thread for the local gofr-agent MCP server."""

    def __init__(self, app: object, host: str, port: int, log_level: str) -> None:
        super().__init__(daemon=True)
        config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
        self.server = uvicorn.Server(config)
        self._ready = threading.Event()
        original_startup = self.server.startup

        async def _startup_and_signal(sockets: object = None) -> None:
            await original_startup(sockets=sockets)
            self._ready.set()

        self.server.startup = _startup_and_signal  # type: ignore[method-assign]

    def run(self) -> None:  # pragma: no cover - exercised by manual launcher
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.server.serve())

    def wait_ready(self, timeout_s: float = 30.0) -> None:
        if not self._ready.wait(timeout_s):
            raise TimeoutError("gofr-agent MCP server did not start in time")

    def shutdown(self) -> None:
        self.server.should_exit = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start fixture MCP services and chat with gofr-agent from the CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        help="OpenRouter model name.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for the local gofr-agent MCP server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Port for the local gofr-agent MCP server.",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="Session ID reused for every question.",
    )
    parser.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error", "critical"],
        help="uvicorn log level for the local agent server.",
    )
    parser.add_argument(
        "--network",
        choices=["auto", "overlay", "localhost"],
        default="overlay",
        help="How the agent reaches fixture services.",
    )
    parser.add_argument(
        "--once",
        help="Ask one question, print the answer, then shut down.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum downstream tool-call iterations per question.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Forward --verbose to app.cli.ask so tool arguments and summaries are shown.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Do not rebuild the fixture image before starting the stack.",
    )
    parser.add_argument(
        "--skip-stack",
        action="store_true",
        help="Do not start/stop the fixture stack; assume services are already running.",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Leave the fixture stack running when this script exits.",
    )
    return parser.parse_args(argv)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
    )


def stack_is_running() -> bool:
    result = subprocess.run(
        ["docker", "stack", "services", "gofr-agent-mcp-fixtures"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def start_fixture_stack(skip_build: bool, skip_stack: bool) -> bool:
    if skip_stack:
        return False

    already_running = stack_is_running()
    if not skip_build:
        print("Building fixture service image...")
        run_command([str(FIXTURE_STACK), "build"])

    print("Starting fixture service stack...")
    run_command([str(FIXTURE_STACK), "start"])
    return not already_running


def stop_fixture_stack(started_by_script: bool, keep_stack: bool, skip_stack: bool) -> None:
    if skip_stack or keep_stack or not started_by_script:
        return
    print("Stopping fixture service stack...")
    run_command([str(FIXTURE_STACK), "stop"])


def can_connect(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def can_resolve(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def wait_for_services(hosts: dict[str, str], timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    pending = set(SERVICE_PORTS)
    while pending and time.monotonic() < deadline:
        for name in list(pending):
            if can_connect(hosts[name], SERVICE_PORTS[name]):
                pending.remove(name)
        if pending:
            time.sleep(1)
    if pending:
        missing = ", ".join(sorted(pending))
        raise TimeoutError(f"Fixture service(s) not reachable: {missing}")


def choose_service_hosts(mode: str) -> dict[str, str]:
    if mode == "overlay":
        return OVERLAY_HOSTS
    if mode == "localhost":
        return {name: "127.0.0.1" for name in SERVICE_PORTS}

    if can_resolve(OVERLAY_HOSTS["instruments"]):
        return OVERLAY_HOSTS
    return {name: "127.0.0.1" for name in SERVICE_PORTS}


def fixture_manifest(hosts: dict[str, str]) -> ServicesManifest:
    descriptions = {
        "instruments": "Instrument reference data, spot prices, and OHLCV history",
        "clients": "Client master data, holdings, watchlists, and mandates",
        "trades": "Trade blotter retrieval, aggregation, and realised P&L",
        "analytics": "Derived analytics for market data, positions, and executions",
    }
    return ServicesManifest(
        services=[
            ServiceConfig(
                name=name,
                url=f"http://{hosts[name]}:{port}/mcp",
                description=descriptions[name],
            )
            for name, port in SERVICE_PORTS.items()
        ]
    )


def openrouter_model(model_name: str) -> OpenAIChatModel:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY must be set before running fixture chat")
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key),
    )


async def build_agent_app(
    args: argparse.Namespace,
    hosts: dict[str, str],
) -> tuple[object, ServiceRegistry]:
    config = GofrAgentConfig(llm_model=args.model)
    registry = ServiceRegistry(config)
    await registry.load_manifest(fixture_manifest(hosts))

    auth_service = DevAuthService()
    agent = GofrAgent(
        config,
        registry,
        auth_service,
        model=openrouter_model(args.model),
    )
    agent.build()
    store = SessionStore(ttl_minutes=config.session_ttl_minutes)
    mcp = create_mcp_server(config, registry, agent, store, auth_service)
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=agent_allowed_hosts(args.host),
        allowed_origins=[],
    )
    return AuthHeaderMiddleware(mcp.streamable_http_app()), registry


def ask_cli(
    server_url: str,
    session: str,
    question: str,
    max_steps: int,
    *,
    verbose: bool = False,
) -> int:
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "app.cli.ask",
        "--url",
        server_url,
        "--token",
        DEV_TOKEN,
        "--session",
        session,
        "--max-steps",
        str(max_steps),
    ]
    if verbose:
        command.append("--verbose")
    command.append(question)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def print_intro(server_url: str, session: str, hosts: dict[str, str], model: str) -> None:
    print("", flush=True)
    print("Fixture chat is ready.", flush=True)
    print(f"Agent MCP URL: {server_url}", flush=True)
    print(f"Session: {session}", flush=True)
    print(f"Model: {model}", flush=True)
    print("Services:", flush=True)
    for name, port in SERVICE_PORTS.items():
        print(f"  - {name}: http://{hosts[name]}:{port}/mcp", flush=True)
    print("", flush=True)
    print("Type a question and press Enter. Commands: :quit, :exit, :reset", flush=True)
    print("", flush=True)


def connect_host(bind_host: str) -> str:
    if bind_host in {"0.0.0.0", "::"}:
        return socket.gethostname()
    return bind_host


def agent_server_url(bind_host: str, port: int) -> str:
    return f"http://{connect_host(bind_host)}:{port}/mcp"


def agent_allowed_hosts(bind_host: str) -> list[str]:
    hosts = {connect_host(bind_host), socket.gethostname(), "127.0.0.1", "localhost"}
    return [f"{host}:*" for host in sorted(hosts) if host]


def configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper())
    logging.basicConfig(level=level)
    for logger_name in ("httpx", "mcp", "app", "asyncio"):
        logging.getLogger(logger_name).setLevel(level)
    logging.getLogger("asyncio").disabled = True


def repl(server_url: str, session: str, max_steps: int, *, verbose: bool) -> int:
    while True:
        try:
            question = input("gofr> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0

        if not question:
            continue
        if question in {":quit", ":exit"}:
            return 0
        if question == ":reset":
            reset = [
                "uv",
                "run",
                "python",
                "-m",
                "app.cli.ask",
                "--url",
                server_url,
                "--token",
                DEV_TOKEN,
                "--reset",
                session,
            ]
            subprocess.run(reset, cwd=PROJECT_ROOT, check=False)
            continue
        ask_cli(server_url, session, question, max_steps, verbose=verbose)


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)
    started_stack = False
    registry: ServiceRegistry | None = None
    thread: AgentServerThread | None = None
    loop = asyncio.new_event_loop()

    try:
        started_stack = start_fixture_stack(args.skip_build, args.skip_stack)
        hosts = choose_service_hosts(args.network)
        wait_for_services(hosts)

        app, registry = loop.run_until_complete(build_agent_app(args, hosts))
        thread = AgentServerThread(app, args.host, args.port, args.log_level)
        thread.start()
        thread.wait_ready()

        server_url = agent_server_url(args.host, args.port)
        print_intro(server_url, args.session, hosts, args.model)

        if args.once:
            return ask_cli(
                server_url,
                args.session,
                args.once,
                args.max_steps,
                verbose=args.verbose,
            )
        return repl(server_url, args.session, args.max_steps, verbose=args.verbose)
    finally:
        if thread is not None:
            thread.shutdown()
            thread.join(timeout=10)
        if registry is not None:
            loop.run_until_complete(registry.shutdown())
        loop.close()
        stop_fixture_stack(started_stack, args.keep_stack, args.skip_stack)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001 - top-level CLI error reporting
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
