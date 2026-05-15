"""Typer CLI for querying the gofr-agent MCP server.

Usage::

    uv run python -m app.cli.ask "What is the capital of France?"
    uv run python -m app.cli.ask --session abc123 "Follow-up question"
    uv run python -m app.cli.ask --reset abc123
"""

from __future__ import annotations

import asyncio
import json
import os

import typer
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

app = typer.Typer(help="Query the gofr-agent reasoning agent.")


@app.command()
def ask(
    question: str | None = typer.Argument(None, help="Question to ask the agent."),
    session: str | None = typer.Option(
        None, "--session", "-s", help="Session ID to continue a conversation."
    ),
    reset: str | None = typer.Option(
        None, "--reset", help="Clear session history and exit."
    ),
    url: str = typer.Option(
        os.environ.get("GOFR_AGENT_URL", "http://localhost:8090/mcp"),
        "--url",
        help="gofr-agent MCP server URL.",
    ),
    token: str = typer.Option(
        os.environ.get("GOFR_AGENT_TOKEN", ""),
        "--token",
        help="Bearer token for authentication (or set GOFR_AGENT_TOKEN env var).",
    ),
    max_steps: int = typer.Option(
        10,
        "--max-steps",
        help="Maximum downstream tool-call iterations for this question.",
    ),
) -> None:
    """Ask the gofr-agent a question."""
    if not token:
        typer.echo(
            "Error: Authentication token required. "
            "Pass --token or set GOFR_AGENT_TOKEN.",
            err=True,
        )
        raise typer.Exit(code=1)
    asyncio.run(
        _run(
            question=question,
            session_id=session,
            reset=reset,
            url=url,
            token=token,
            max_steps=max_steps,
        )
    )


async def _run(
    question: str | None,
    session_id: str | None,
    reset: str | None,
    url: str,
    token: str,
    max_steps: int,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        streamablehttp_client(url, headers=headers) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()

        if reset is not None:
            result = await client.call_tool("reset_session", {"session_id": reset})
            typer.echo(f"Session '{reset}' reset.")
            _print_result(result)
            return

        if question is None:
            typer.echo("Error: Provide a question or use --reset.", err=True)
            raise typer.Exit(code=1)

        params: dict[str, object] = {"question": question, "max_steps": max_steps}
        if session_id is not None:
            params["session_id"] = session_id

        result = await client.call_tool("ask", params)
        _print_result(result)


def _print_result(result: object) -> None:
    for content in result.content:  # type: ignore[union-attr]
        if hasattr(content, "text"):
            try:
                data = json.loads(content.text)
                if "answer" in data:
                    typer.echo(f"\nAnswer: {data['answer']}")
                    if data.get("session_id"):
                        typer.echo(f"Session: {data['session_id']}")
                    if data.get("tokens_used"):
                        typer.echo(f"Tokens: {data['tokens_used']}")
                else:
                    typer.echo(content.text)
            except (json.JSONDecodeError, TypeError):
                typer.echo(content.text)


if __name__ == "__main__":
    app()

