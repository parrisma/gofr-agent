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
import sys
from typing import Any

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
        os.environ.get("GOFR_AGENT_URL", "http://gofr-agent:8090/mcp"),
        "--url",
        help="gofr-agent MCP server URL.",
    ),
    token: str = typer.Option(
        os.environ.get("GOFR_AGENT_TOKEN", ""),
        "--token",
        help="Bearer token for authentication (or set GOFR_AGENT_TOKEN env var).",
    ),
    max_steps: int | None = typer.Option(
        None,
        "--max-steps",
        help=(
            "Maximum downstream tool-call iterations for this question. "
            "When omitted, the server default is used."
        ),
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Legacy context to treat as pasted data.",
    ),
    instructions: str | None = typer.Option(
        None,
        "--instructions",
        help="Authenticated requester instructions for this run.",
    ),
    asserted_fact: list[str] | None = typer.Option(
        None,
        "--asserted-fact",
        help="Caller-asserted fact to provide as non-authoritative input.",
    ),
    pasted_content: list[str] | None = typer.Option(
        None,
        "--pasted-content",
        help="Third-party content to treat as data only.",
    ),
    forbidden_service: list[str] | None = typer.Option(
        None,
        "--forbidden-service",
        help="Service the agent must not call.",
    ),
    forbidden_tool: list[str] | None = typer.Option(
        None,
        "--forbidden-tool",
        help="Tool the agent must not call.",
    ),
    allowed_service: list[str] | None = typer.Option(
        None,
        "--allowed-service",
        help="Restrict tool calls to this service. Repeat for multiple services.",
    ),
    tools_only: bool = typer.Option(
        False,
        "--tools-only",
        help="Require factual answers to come from tools.",
    ),
    no_commentary: bool = typer.Option(
        False,
        "--no-commentary",
        help="Ask for no extra commentary in the final answer.",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Pause and resume deterministic clarification prompts when supported.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Print only the final answer.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Print reasoning details including tool arguments and result summaries.",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text or json.",
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
    if output_format not in {"text", "json"}:
        typer.echo("Error: --format must be 'text' or 'json'.", err=True)
        raise typer.Exit(code=1)
    asyncio.run(
        _run(
            question=question,
            session_id=session,
            reset=reset,
            url=url,
            token=token,
            max_steps=max_steps,
            context=context,
            instructions=instructions,
            asserted_facts=asserted_fact,
            pasted_content=pasted_content,
            forbidden_services=forbidden_service,
            forbidden_tools=forbidden_tool,
            allowed_services=allowed_service,
            tools_only=tools_only,
            no_commentary=no_commentary,
            interactive=interactive,
            quiet=quiet,
            verbose=verbose,
            output_format=output_format,
        )
    )


async def _run(
    question: str | None,
    session_id: str | None,
    reset: str | None,
    url: str,
    token: str,
    max_steps: int | None,
    context: str | None,
    instructions: str | None,
    asserted_facts: list[str] | None,
    pasted_content: list[str] | None,
    forbidden_services: list[str] | None,
    forbidden_tools: list[str] | None,
    allowed_services: list[str] | None,
    tools_only: bool,
    no_commentary: bool,
    interactive: bool,
    quiet: bool,
    verbose: bool,
    output_format: str,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    events: list[dict[str, Any]] = []
    renderer = EventRenderer(verbose=verbose)

    async def _capture_log(params: Any) -> None:
        data = getattr(params, "data", None)
        if not isinstance(data, dict) or "kind" not in data:
            return
        events.append(data)
        if output_format == "text" and not quiet:
            renderer.render(data)

    async with (
        streamablehttp_client(url, headers=headers) as (read, write, _),
        ClientSession(read, write, logging_callback=_capture_log) as client,
    ):
        await client.initialize()

        if reset is not None:
            result = await client.call_tool("reset_session", {"session_id": reset})
            typer.echo(f"Session '{reset}' reset.")
            payload = _extract_result_payload(result)
            _print_payload(payload, quiet=False)
            return

        if question is None:
            typer.echo("Error: Provide a question or use --reset.", err=True)
            raise typer.Exit(code=1)

        params: dict[str, object] = {
            "question": question,
            "output_format": output_format,
        }
        if max_steps is not None:
            params["max_steps"] = max_steps
        if session_id is not None:
            params["session_id"] = session_id
        if context is not None:
            params["context"] = context
        if instructions is not None:
            params["instructions"] = instructions
        if asserted_facts:
            params["asserted_facts"] = asserted_facts
        if pasted_content:
            params["pasted_content"] = pasted_content
        if forbidden_services:
            params["forbidden_services"] = forbidden_services
        if forbidden_tools:
            params["forbidden_tools"] = forbidden_tools
        if allowed_services:
            params["allowed_services"] = allowed_services
        if tools_only:
            params["tools_only"] = True
        if no_commentary:
            params["no_commentary"] = True
        if interactive:
            params["interactive"] = True

        result = await client.call_tool("ask", params)
        payload = _extract_result_payload(result)
        if output_format == "text" and payload.get("status") == "waiting_for_user":
            payload = await _prompt_and_resume(client, payload)

    if output_format == "text" and not quiet:
        renderer.finish()

    if output_format == "json":
        typer.echo(json.dumps({"events": events, "response": payload}, indent=2))
        return

    _print_payload(payload, quiet=quiet)
    if payload.get("status") == "waiting_for_user":
        raise typer.Exit(code=2)


async def _prompt_and_resume(
    client: ClientSession,
    payload: dict[str, Any],
    *,
    max_prompt_loops: int = 5,
) -> dict[str, Any]:
    current = payload
    for _ in range(max_prompt_loops):
        if current.get("status") != "waiting_for_user":
            return current
        if not _stdin_is_tty():
            return current

        request = current.get("user_input_request")
        if not isinstance(request, dict):
            return current
        session_id = current.get("session_id")
        prompt_id = request.get("prompt_id")
        if not isinstance(session_id, str) or not isinstance(prompt_id, str):
            return current

        prompt = str(request.get("prompt") or "Response")
        value = typer.prompt(prompt, default="", show_default=False)
        result = await client.call_tool(
            "respond_to_user_input",
            {
                "session_id": session_id,
                "prompt_id": prompt_id,
                "value": value,
            },
        )
        current = _extract_result_payload(result)
    return current


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _extract_result_payload(result: object) -> dict[str, Any]:
    for content in result.content:  # type: ignore[union-attr]
        if hasattr(content, "text"):
            try:
                data = json.loads(content.text)
                if isinstance(data, dict):
                    return data
                return {"result": data}
            except (json.JSONDecodeError, TypeError):
                return {"raw_text": content.text}
    return {}


def _print_payload(payload: dict[str, Any], *, quiet: bool) -> None:
    if payload.get("status") == "waiting_for_user":
        _print_waiting_payload(payload, quiet=quiet)
        return

    answer = payload.get("answer")
    if answer is None:
        raw_text = payload.get("raw_text")
        if raw_text is not None:
            typer.echo(str(raw_text))
            return
        typer.echo(json.dumps(payload))
        return

    if quiet:
        typer.echo(str(answer))
        return

    typer.echo(f"\nAnswer: {answer}")
    _print_gap_or_clarification(payload)
    _print_provenance(payload)
    if payload.get("session_id"):
        typer.echo(f"Session: {payload['session_id']}")
    if payload.get("tokens_used"):
        typer.echo(f"Tokens: {payload['tokens_used']}")


def _print_waiting_payload(payload: dict[str, Any], *, quiet: bool) -> None:
    request = payload.get("user_input_request")
    prompt = None
    prompt_id = None
    if isinstance(request, dict):
        prompt = request.get("prompt")
        prompt_id = request.get("prompt_id")

    if quiet:
        typer.echo(str(prompt or "waiting_for_user"))
        return

    typer.echo("\nWaiting for user input")
    if prompt:
        typer.echo(str(prompt))
    if payload.get("session_id"):
        typer.echo(f"Session: {payload['session_id']}")
    if prompt_id:
        typer.echo(f"Prompt ID: {prompt_id}")


def _print_gap_or_clarification(payload: dict[str, Any]) -> None:
    gap = payload.get("verification_gap")
    if isinstance(gap, dict):
        typer.echo(f"Verification gap: {gap.get('requested_fact', 'unknown fact')}")
        typer.echo(f"Reason: {gap.get('reason', 'unknown')}")
        attempts = gap.get("attempted")
        if isinstance(attempts, list) and attempts:
            typer.echo(f"Attempts: {len(attempts)}")

    clarification = payload.get("clarification_request")
    if isinstance(clarification, dict):
        fields = clarification.get("missing_fields", [])
        if isinstance(fields, list):
            typer.echo(f"Clarification needed: {', '.join(str(field) for field in fields)}")
        prompt = clarification.get("prompt")
        if prompt:
            typer.echo(str(prompt))


def _print_provenance(payload: dict[str, Any]) -> None:
    provenance = payload.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        return
    refs: list[str] = []
    for record in provenance:
        if not isinstance(record, dict):
            continue
        service = record.get("service")
        tool = record.get("tool")
        args_hash = record.get("args_hash")
        if service and tool and args_hash:
            refs.append(f"{service}.{tool}:{args_hash}")
    if refs:
        typer.echo(f"Provenance: {', '.join(refs)}")


class EventRenderer:
    def __init__(self, *, verbose: bool) -> None:
        self._verbose = verbose
        self._pending_thought: dict[str, Any] | None = None

    def render(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")

        if kind == "text_delta":
            return

        if kind == "step_started" and event.get("step_kind") == "thought":
            self._flush_pending_thought(next_event=None)
            self._pending_thought = event
            return

        if kind == "step_completed" and event.get("step_kind") == "thought":
            return

        self._flush_pending_thought(next_event=event)

        if kind == "summary_update":
            typer.echo("- Summary updated")
            if self._verbose:
                _render_detail("summary", event.get("summary"))
            return

        if kind == "tool_call":
            typer.echo(f"- Tool: {_tool_label(event)}")
            if self._verbose:
                explanation = _tool_explanation(event)
                if explanation:
                    _render_detail("about", explanation)
                _render_detail("args", event.get("arguments", {}))
            return

        if kind == "tool_retry":
            attempt = event.get("attempt", "?")
            message = event.get("message")
            line = f"- Retry: {_tool_label(event)} (attempt {attempt})"
            if message:
                line = f"{line} - {message}"
            typer.echo(line)
            return

        if kind == "tool_result":
            status = "ok" if event.get("ok") else "failed"
            latency_ms = event.get("latency_ms")
            latency_suffix = f", {latency_ms} ms" if latency_ms is not None else ""
            typer.echo(f"- Result: {_tool_label(event)} [{status}{latency_suffix}]")
            if self._verbose:
                _render_detail("summary", event.get("summary"))
            return

        if kind == "run_completed" and self._verbose:
            answer_preview = event.get("answer_preview")
            if answer_preview:
                typer.echo("- Final answer ready")
                _render_detail("preview", answer_preview)
            return

        if kind == "run_failed":
            typer.echo(f"- Failed: {event.get('error', 'unknown error')}", err=True)

    def finish(self) -> None:
        self._flush_pending_thought(next_event=None)

    def _flush_pending_thought(self, next_event: dict[str, Any] | None) -> None:
        if self._pending_thought is None:
            return
        typer.echo(f"- Thinking: {_thinking_label(self._pending_thought, next_event)}")
        self._pending_thought = None


def _tool_label(event: dict[str, Any]) -> str:
    service = str(event.get("service", "")).strip()
    tool = str(event.get("tool", "")).strip()
    if service and tool:
        return f"{service}.{tool}"
    return tool or service or "unknown"


def _thinking_label(
    event: dict[str, Any],
    next_event: dict[str, Any] | None,
) -> str:
    title = str(event.get("title", "")).strip()
    if title not in {"", "model_request"}:
        return title.replace("_", " ")

    next_kind = "" if next_event is None else str(next_event.get("kind", "")).strip()
    next_step_kind = (
        "" if next_event is None else str(next_event.get("step_kind", "")).strip()
    )
    if next_kind == "tool_call" or (next_kind == "step_started" and next_step_kind == "tool_call"):
        return "planning next tool"
    if next_kind == "run_completed":
        return "composing final answer"
    if next_kind == "run_failed":
        return "handling run failure"
    return "model reasoning"


def _tool_explanation(event: dict[str, Any]) -> str:
    service = str(event.get("service", "")).strip()
    tool = str(event.get("tool", "")).strip()
    arguments = event.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    known_key = (service, tool)
    if known_key == ("analytics", "simple_return"):
        return _compose_explanation("calculate simple return", arguments)
    if known_key == ("analytics", "historical_volatility"):
        return _compose_explanation("calculate historical volatility", arguments)
    if known_key == ("analytics", "max_drawdown"):
        return _compose_explanation("calculate maximum drawdown", arguments)
    if known_key == ("analytics", "position_market_value"):
        return _compose_explanation("calculate position market value", arguments)
    if known_key == ("trades", "get_realised_pnl"):
        return _compose_explanation("calculate realised P&L", arguments)
    if known_key == ("trades", "get_average_execution_price"):
        return _compose_explanation("calculate average execution price", arguments)
    if known_key == ("instruments", "get_ohlcv_history"):
        return _compose_explanation("fetch OHLCV price history", arguments)
    if known_key == ("clients", "get_holding"):
        return _compose_explanation("look up a client holding", arguments)

    action = tool.replace("_", " ").strip()
    if action.startswith("get "):
        action = action.removeprefix("get ")
    return _compose_explanation(action or _tool_label(event), arguments)


def _compose_explanation(action: str, arguments: dict[str, Any]) -> str:
    instrument = _argument_value(
        arguments,
        "symbol",
        "ticker",
        "instrument",
        "instrument_id",
        "isin",
    )
    client = _argument_value(arguments, "client_id", "client", "client_name")
    period_days = _argument_value(
        arguments,
        "days",
        "lookback_days",
        "window_days",
        "period_days",
    )
    context_parts: list[str] = []
    if period_days is not None and period_days != "":
        context_parts.append(f"for the last {period_days} days")
    if client is not None and client != "":
        context_parts.append(f"for client {client}")
    if instrument is not None and instrument != "":
        context_parts.append(f"for {instrument}")

    if not context_parts:
        return action
    return f"{action} {' '.join(context_parts)}"


def _argument_value(arguments: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = arguments.get(key)
        if value is not None and value != "":
            return value
    return None


def _render_detail(label: str, value: Any) -> None:
    rendered = _format_detail_value(value)
    if not rendered:
        return
    if "\n" not in rendered:
        typer.echo(f"  {label}: {rendered}")
        return
    typer.echo(f"  {label}:")
    for line in rendered.splitlines():
        typer.echo(f"    {line}")


def _format_detail_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        compact = json.dumps(value, sort_keys=True)
        if len(compact) > 80 or _has_nested_structure(value):
            return json.dumps(value, sort_keys=True, indent=2)
        return compact
    return str(value)


def _has_nested_structure(value: Any) -> bool:
    if isinstance(value, dict):
        return any(isinstance(item, (dict, list)) for item in value.values())
    if isinstance(value, list):
        return any(isinstance(item, (dict, list)) for item in value)
    return False


if __name__ == "__main__":
    app()

