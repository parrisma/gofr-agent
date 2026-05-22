#!/usr/bin/env python3
"""Interactive fixture chat launcher for manual gofr-agent testing.

Starts the Compose-managed fixture services, boots a local gofr-agent MCP
server configured against those services, then opens a small prompt loop that
calls the existing CLI with a shared session ID.
"""

from __future__ import annotations

# ruff: noqa: E402, I001
# The local gofr-common submodule path must be inserted before app imports,
# which intentionally splits the import block.

import argparse
import asyncio
import importlib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON_SRC = PROJECT_ROOT / "lib" / "gofr-common" / "src"
for import_path in (PROJECT_ROOT, COMMON_SRC):
    if import_path.is_dir() and str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import uvicorn
from gofr_common.web import AuthHeaderMiddleware
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.agent import GofrAgent
from app.auth._dev_auth_service import DevAuthService
from app.config import GofrAgentConfig
from app.mcp_server.mcp_server import create_mcp_server
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore
from app.transport_security import apply_transport_security
from tests.fixtures.mcp_services import analytics, instruments
from tests.fixtures.mcp_services._server import _UvicornThread, make_service_server

COMPOSE_FILE = PROJECT_ROOT / "docker" / "compose.dev.yml"
DEV_NETWORK = "gofr-dev-net"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
DEV_TOKEN = "dev-admin-token"
FIXTURE_HUB_TOKEN = "dev-fixtures-hub-token"
DEFAULT_SESSION = "fixture-chat"

SERVICE_PORTS = {
    "instruments": 8500,
    "clients": 8501,
    "trades": 8502,
    "analytics": 8503,
}

COMPOSE_HOSTS = {
    "instruments": "gofr-agent-mcp-instruments",
    "clients": "gofr-agent-mcp-clients",
    "trades": "gofr-agent-mcp-trades",
    "analytics": "gofr-agent-mcp-analytics",
}

COMPOSE_SERVICES = [
    "valkey",
    "mcp-instruments",
    "mcp-clients",
    "mcp-trades",
    "mcp-analytics",
]


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


@dataclass
class LocalFixtureResources:
    service_urls: dict[str, str]
    service_threads: list[_UvicornThread]
    resetters: list[callable]

    def shutdown(self) -> None:
        for thread in self.service_threads:
            thread.shutdown()
            thread.join(timeout=5)
        for reset in self.resetters:
            reset()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start fixture MCP services and chat with gofr-agent from the CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        help=(
            "Model name. Use an OpenRouter model for live runs, `test` for the "
            "built-in pydantic-ai test model, or `fixture-descriptor-smoke` for "
            "a deterministic results-hub smoke test."
        ),
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
        choices=["auto", "compose", "localhost"],
        default="compose",
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
        "--agent-timeout-seconds",
        type=int,
        default=120,
        help="Wall-clock timeout for each agent run.",
    )
    parser.add_argument(
        "--hub-ttl-seconds",
        type=int,
        default=300,
        help="Lifetime for results-hub descriptors returned by fixture services.",
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


def fixture_services_are_running() -> bool:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "ps",
            "--services",
            "--status",
            "running",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return all(service in running for service in COMPOSE_SERVICES)


def connect_current_container_to_dev_net() -> None:
    current_container_id = socket.gethostname()
    docker_ps = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"id={current_container_id}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if not docker_ps.stdout.strip():
        return

    subprocess.run(
        ["docker", "network", "connect", DEV_NETWORK, current_container_id],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def start_fixture_stack(skip_build: bool, skip_stack: bool) -> bool:
    if skip_stack:
        return False

    already_running = fixture_services_are_running()
    if not skip_build:
        print("Building fixture service image...")
        run_command(["docker", "compose", "-f", str(COMPOSE_FILE), "build", *COMPOSE_SERVICES[1:]])

    print("Starting fixture service stack...")
    run_command(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", *COMPOSE_SERVICES])
    connect_current_container_to_dev_net()
    return not already_running


def stop_fixture_stack(started_by_script: bool, keep_stack: bool, skip_stack: bool) -> None:
    if skip_stack or keep_stack or not started_by_script:
        return
    print("Stopping fixture service stack...")
    run_command(["docker", "compose", "-f", str(COMPOSE_FILE), "stop", *COMPOSE_SERVICES])


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
    if mode == "compose":
        return COMPOSE_HOSTS
    if mode == "localhost":
        return {name: "127.0.0.1" for name in SERVICE_PORTS}

    if can_resolve(COMPOSE_HOSTS["instruments"]):
        return COMPOSE_HOSTS
    return {name: "127.0.0.1" for name in SERVICE_PORTS}


def service_urls_from_hosts(hosts: dict[str, str]) -> dict[str, str]:
    return {name: f"http://{hosts[name]}:{port}/mcp" for name, port in SERVICE_PORTS.items()}


def fixture_manifest(hosts: dict[str, str]) -> ServicesManifest:
    descriptions = {
        "instruments": "Instrument reference data, spot prices, and OHLCV history",
        "clients": "Client master data, holdings, watchlists, and mandates",
        "trades": "Trade blotter retrieval, aggregation, and realised P&L",
        "analytics": "Derived analytics for market data, positions, and executions",
    }
    hub_callback_tokens = {
        "instruments": FIXTURE_HUB_TOKEN,
        "analytics": FIXTURE_HUB_TOKEN,
    }
    return ServicesManifest(
        services=[
            ServiceConfig(
                name=name,
                url=f"http://{hosts[name]}:{port}/mcp",
                token=DEV_TOKEN,
                description=descriptions[name],
                hub_callback_token=hub_callback_tokens.get(name),
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


def _tool_payload(messages: list[ModelMessage], tool_name: str) -> dict[str, object] | None:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name != tool_name or part.outcome != "success":
                continue
            payload = GofrAgent._parse_tool_payload(part.model_response_str())
            if payload is not None:
                return payload
    return None


def _descriptor_smoke_model(
    messages: list[ModelMessage],
    _agent_info: AgentInfo,
) -> ModelResponse:
    instrument_payload = _tool_payload(messages, "instruments__get_ohlcv_history")
    simple_return_payload = _tool_payload(messages, "analytics__simple_return")
    volatility_payload = _tool_payload(messages, "analytics__historical_volatility")
    drawdown_payload = _tool_payload(messages, "analytics__max_drawdown")

    if instrument_payload is None:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "instruments__get_ohlcv_history",
                    {
                        "ticker": "AAPL",
                        "from_date": "2026-04-01",
                        "to_date": "2026-05-13",
                    },
                )
            ]
        )

    if simple_return_payload is None or volatility_payload is None or drawdown_payload is None:
        descriptor = json.loads(str(instrument_payload["content"]))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "analytics__simple_return",
                    {"ticker": "AAPL", "bars_ref": descriptor},
                ),
                ToolCallPart(
                    "analytics__historical_volatility",
                    {"ticker": "AAPL", "bars_ref": descriptor, "window": 30},
                ),
                ToolCallPart(
                    "analytics__max_drawdown",
                    {"ticker": "AAPL", "bars_ref": descriptor},
                ),
            ]
        )

    simple_return = json.loads(str(simple_return_payload["content"]))
    volatility = json.loads(str(volatility_payload["content"]))
    drawdown = json.loads(str(drawdown_payload["content"]))
    answer = {
        "ticker": simple_return["ticker"],
        "from_date": simple_return["from_date"],
        "to_date": simple_return["to_date"],
        "simple_return": simple_return["return_pct"],
        "annualised_vol": volatility["annualised_vol"],
        "max_drawdown_pct": drawdown["max_drawdown_pct"],
    }
    return ModelResponse(
        parts=[TextPart(json.dumps(answer, sort_keys=True, separators=(",", ":")))]
    )


async def _descriptor_smoke_stream(
    messages: list[ModelMessage],
    agent_info: AgentInfo,
):
    response = _descriptor_smoke_model(messages, agent_info)
    for index, part in enumerate(response.parts):
        if isinstance(part, ToolCallPart):
            yield {
                index: DeltaToolCall(
                    name=part.tool_name,
                    json_args=part.args_as_json_str(),
                    tool_call_id=part.tool_call_id,
                )
            }
            continue
        if isinstance(part, TextPart):
            yield part.content
            continue
        raise AssertionError(f"Unexpected response part: {type(part).__name__}")


def build_agent_model(model_name: str) -> object:
    if model_name == "test":
        return model_name
    if model_name == "fixture-descriptor-smoke":
        return FunctionModel(
            function=_descriptor_smoke_model,
            stream_function=_descriptor_smoke_stream,
            model_name="function:fixture-descriptor-smoke",
        )
    return openrouter_model(model_name)


def _local_address_for_remote(host: str, port: int) -> str | None:
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            return str(sock.getsockname()[0])
    except OSError:
        return None


def public_hub_host(bind_host: str, hosts: dict[str, str] | None = None) -> str:
    if bind_host in {"0.0.0.0", "::"}:
        if hosts is not None:
            for name, host in hosts.items():
                candidate = _local_address_for_remote(host, SERVICE_PORTS[name])
                if candidate is None:
                    continue
                try:
                    if not ip_address(candidate).is_loopback:
                        return candidate
                except ValueError:
                    return candidate
        return socket.gethostbyname(socket.gethostname())
    return bind_host


async def build_agent_app(
    args: argparse.Namespace,
    hosts: dict[str, str],
) -> tuple[object, ServiceRegistry]:
    hub_host = public_hub_host(args.host, hosts)
    config = GofrAgentConfig(
        host=args.host,
        mcp_port=args.port,
        llm_model=args.model,
        agent_timeout_seconds=args.agent_timeout_seconds,
        hub_enabled=True,
        hub_url=f"http://{hub_host}:{args.port}/mcp",
        hub_default_ttl_seconds=args.hub_ttl_seconds,
        hub_max_payload_bytes=65536,
        hub_max_results=32,
        mcp_allowed_hosts=agent_allowed_hosts(args.host, hub_host=hub_host),
    )
    registry = ServiceRegistry(config)
    await registry.load_manifest(fixture_manifest(hosts))

    auth_service = DevAuthService()
    agent = GofrAgent(
        config,
        registry,
        auth_service,
        model=build_agent_model(args.model),
    )
    agent.build()
    store = SessionStore(ttl_minutes=config.session_ttl_minutes)
    mcp = create_mcp_server(config, registry, agent, store, auth_service)
    apply_transport_security(mcp, config)
    return AuthHeaderMiddleware(mcp.streamable_http_app()), registry


def is_descriptor_smoke_model(model_name: str) -> bool:
    return model_name == "fixture-descriptor-smoke"


async def build_descriptor_smoke_app(
    args: argparse.Namespace,
) -> tuple[object, ServiceRegistry, LocalFixtureResources]:
    instruments_module = importlib.reload(instruments)
    analytics_module = importlib.reload(analytics)
    instruments_module.reset_results_hub_state()
    analytics_module.reset_results_hub_state()
    instruments_module.configure_results_hub_auth(FIXTURE_HUB_TOKEN)
    analytics_module.configure_results_hub_auth(FIXTURE_HUB_TOKEN)

    instruments_host, instruments_port, instruments_thread = make_service_server(
        instruments_module.mcp
    )
    analytics_host, analytics_port, analytics_thread = make_service_server(analytics_module.mcp)

    hub_host = public_hub_host(args.host)
    config = GofrAgentConfig(
        host=args.host,
        mcp_port=args.port,
        llm_model="test",
        agent_timeout_seconds=args.agent_timeout_seconds,
        session_pool_size=4,
        hub_enabled=True,
        hub_url=f"http://{hub_host}:{args.port}/mcp",
        hub_default_ttl_seconds=args.hub_ttl_seconds,
        hub_max_payload_bytes=65536,
        hub_max_results=32,
        mcp_allowed_hosts=agent_allowed_hosts(args.host, hub_host=hub_host),
    )
    registry = ServiceRegistry(config)
    await registry.load_manifest(
        ServicesManifest(
            services=[
                ServiceConfig(
                    name="instruments",
                    url=f"http://{instruments_host}:{instruments_port}/mcp",
                    token=DEV_TOKEN,
                    hub_callback_token=FIXTURE_HUB_TOKEN,
                ),
                ServiceConfig(
                    name="analytics",
                    url=f"http://{analytics_host}:{analytics_port}/mcp",
                    token=DEV_TOKEN,
                    hub_callback_token=FIXTURE_HUB_TOKEN,
                ),
            ]
        )
    )

    auth_service = DevAuthService()
    agent = GofrAgent(
        config,
        registry,
        auth_service,
        model=build_agent_model(args.model),
    )
    agent.build()
    store = SessionStore(ttl_minutes=config.session_ttl_minutes)
    mcp = create_mcp_server(config, registry, agent, store, auth_service)
    apply_transport_security(mcp, config)
    resources = LocalFixtureResources(
        service_urls={
            "instruments": f"http://{instruments_host}:{instruments_port}/mcp",
            "analytics": f"http://{analytics_host}:{analytics_port}/mcp",
        },
        service_threads=[instruments_thread, analytics_thread],
        resetters=[
            instruments_module.reset_results_hub_state,
            analytics_module.reset_results_hub_state,
        ],
    )
    return AuthHeaderMiddleware(mcp.streamable_http_app()), registry, resources


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


def print_intro(
    server_url: str,
    session: str,
    service_urls: dict[str, str],
    model: str,
) -> None:
    print("", flush=True)
    print("Fixture chat is ready.", flush=True)
    print(f"Agent MCP URL: {server_url}", flush=True)
    print(f"Session: {session}", flush=True)
    print(f"Model: {model}", flush=True)
    print("Services:", flush=True)
    for name, url in service_urls.items():
        print(f"  - {name}: {url}", flush=True)
    print("", flush=True)
    print("Type a question and press Enter. Commands: :quit, :exit, :reset", flush=True)
    print("", flush=True)


def connect_host(bind_host: str) -> str:
    if bind_host in {"0.0.0.0", "::"}:
        return socket.gethostname()
    return bind_host


def agent_server_url(bind_host: str, port: int) -> str:
    return f"http://{connect_host(bind_host)}:{port}/mcp"


def agent_allowed_hosts(bind_host: str, *, hub_host: str | None = None) -> list[str]:
    dev_container_host = os.environ.get("GOFR_DEV_CONTAINER", "gofr-agent-dev").strip()
    hosts = {
        connect_host(bind_host),
        public_hub_host(bind_host),
        socket.gethostname(),
        "127.0.0.1",
        "localhost",
    }
    if dev_container_host:
        hosts.add(dev_container_host)
    if hub_host:
        hosts.add(hub_host)
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
    local_resources: LocalFixtureResources | None = None
    loop = asyncio.new_event_loop()

    try:
        if is_descriptor_smoke_model(args.model):
            app, registry, local_resources = loop.run_until_complete(
                build_descriptor_smoke_app(args)
            )
            service_urls = local_resources.service_urls
        else:
            started_stack = start_fixture_stack(args.skip_build, args.skip_stack)
            hosts = choose_service_hosts(args.network)
            wait_for_services(hosts)
            app, registry = loop.run_until_complete(build_agent_app(args, hosts))
            service_urls = service_urls_from_hosts(hosts)

        thread = AgentServerThread(app, args.host, args.port, args.log_level)
        thread.start()
        thread.wait_ready()

        server_url = agent_server_url(args.host, args.port)
        print_intro(server_url, args.session, service_urls, args.model)

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
        if local_resources is not None:
            local_resources.shutdown()
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
