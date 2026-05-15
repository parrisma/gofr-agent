#!/usr/bin/env python3
"""
Ping any GOFR MCP service via the Streamable HTTP transport.

How it works:
    1. Opens a Streamable HTTP connection to the MCP endpoint.
    2. Performs the MCP initialize handshake (protocol version, capabilities).
    3. Calls the `ping` tool (every GOFR MCP service exposes one).
    4. Prints the result and exits 0 on success, 1 on failure.

    The MCP Streamable HTTP transport is NOT plain REST — it uses a
    persistent HTTP connection with Server-Sent Events (SSE) for responses.
    A simple `curl -X POST` will hang because it doesn't speak the SSE
    protocol. This script uses the official `mcp` Python SDK which handles
    the full handshake automatically.

Hostname rules — FROM vs TO:
    The URL you pass depends on WHERE this script runs and WHERE the
    MCP service runs.

    From a dev container (on gofr-net) → use Docker service/container names:
        http://gofr-dig-mcp:8070/mcp      (gofr-dig MCP)
        http://gofr-doc-mcp:8060/mcp      (gofr-doc MCP)

    From the Docker host itself → use localhost + the published host port:
        http://localhost:8070/mcp          (gofr-dig MCP)
        http://localhost:8060/mcp          (gofr-doc MCP)

    The key difference: dev containers share the `gofr-net` Docker network
    with the prod/test containers, so they can reach each other by container
    name. The Docker host is outside that network and can only reach
    containers through published ports on localhost.

    "host.docker.internal" does NOT work from inside a dev container on
    Linux — it resolves to the host's Docker bridge IP, but published ports
    are bound to the host's loopback (127.0.0.1), which is unreachable from
    the bridge. Use the Docker container name instead.

Usage:
    # From a dev container — use Docker container names
    uv run lib/gofr-common/scripts/mcp_ping.py http://gofr-dig-mcp:8070/mcp
    uv run lib/gofr-common/scripts/mcp_ping.py http://gofr-doc-mcp:8060/mcp

    # From the Docker host — use localhost
    uv run lib/gofr-common/scripts/mcp_ping.py http://localhost:8070/mcp

    # With explicit timeout (seconds)
    uv run lib/gofr-common/scripts/mcp_ping.py http://gofr-dig-mcp:8070/mcp --timeout 10

    # Quiet mode — exit code only (0 = ok, 1 = fail)
    uv run lib/gofr-common/scripts/mcp_ping.py http://gofr-dig-mcp:8070/mcp -q

Requires: mcp (pip/uv package)

Every GOFR MCP service exposes a `ping` tool that returns:
    {"status": "ok", "service": "<name>", "build": "<build>", "timestamp": "..."}
"""

import argparse
import asyncio
import json
import socket
import sys
import time
from urllib.parse import urlparse


async def ping(url: str, timeout: float) -> dict:
    """Connect to an MCP endpoint, call the ping tool, return the result dict."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with asyncio.timeout(timeout):
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("ping", {})
                if result.content and len(result.content) > 0:
                    return json.loads(result.content[0].text)
                return {"status": "error", "error": "empty response"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ping a GOFR MCP service via Streamable HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
hostname rules:
  from dev container (gofr-net)  → use Docker container names
    http://gofr-dig-mcp:8070/mcp
    http://gofr-doc-mcp:8060/mcp
  from Docker host               → use localhost + published port
    http://localhost:8070/mcp

  host.docker.internal does NOT work from Linux dev containers.
  It resolves to the host's Docker bridge IP (e.g. 192.168.65.254),
  but published ports are bound to 127.0.0.1 on the host, which is
  unreachable from the bridge network. Use container names instead.""",
    )
    parser.add_argument(
        "url",
        help="MCP endpoint URL, e.g. http://localhost:8070/mcp",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Connection + call timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode — no output, exit code only (0=ok, 1=fail)",
    )
    args = parser.parse_args()

    # Resolve and display the target hostname's IP
    parsed = urlparse(args.url)
    hostname = parsed.hostname or ""
    if not args.quiet:
        try:
            ip = socket.gethostbyname(hostname)
            print(f"      {hostname} → {ip}", file=sys.stderr)
        except socket.gaierror:
            print(f"      {hostname} → <unresolvable>", file=sys.stderr)

    t0 = time.monotonic()
    try:
        result = asyncio.run(ping(args.url, args.timeout))
    except TimeoutError:
        if not args.quiet:
            print(f"FAIL  {args.url}  timeout after {args.timeout:.0f}s", file=sys.stderr)
            if "host.docker.internal" in args.url:
                print(
                    "HINT  host.docker.internal doesn't work from Linux dev containers.\n"
                    "      Use the Docker container name instead, e.g.:\n"
                    "        http://gofr-dig-mcp:8070/mcp",
                    file=sys.stderr,
                )
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if not args.quiet:
            print(f"FAIL  {args.url}  {type(exc).__name__}: {exc}", file=sys.stderr)
            if "host.docker.internal" in args.url:
                print(
                    "HINT  host.docker.internal doesn't work from Linux dev containers.\n"
                    "      Use the Docker container name instead, e.g.:\n"
                    "        http://gofr-dig-mcp:8070/mcp",
                    file=sys.stderr,
                )
        return 1

    elapsed_ms = (time.monotonic() - t0) * 1000
    status = result.get("status", "unknown")

    if status != "ok":
        if not args.quiet:
            print(f"FAIL  {args.url}  status={status}  {json.dumps(result)}", file=sys.stderr)
        return 1

    if not args.quiet:
        service = result.get("service", "?")
        build = result.get("build", "?")
        ts = result.get("timestamp", "")
        print(f"OK    {service}  build={build}  {elapsed_ms:.0f}ms  {ts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
