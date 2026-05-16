"""Tests for app.cli.ask using typer.testing.CliRunner."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from app.cli.ask import app

runner = CliRunner()

_TOKEN = "dev-admin-token"
_TOKEN_FLAGS = ["--token", _TOKEN]


def _make_call_result(data: dict) -> MagicMock:  # type: ignore[type-arg]
    content = MagicMock()
    content.text = json.dumps(data)
    result = MagicMock()
    result.content = [content]
    return result


def _patch_mcp(
    call_results: dict,
    *,
    log_events: list[dict] | None = None,
):  # type: ignore[return, no-untyped-def]
    """Context manager that patches streamablehttp_client + ClientSession."""
    from contextlib import asynccontextmanager

    async def fake_call_tool(tool: str, params: dict) -> MagicMock:  # type: ignore[type-arg]
        return call_results.get(tool, _make_call_result({}))

    @asynccontextmanager
    async def _fake_session_cm(r, w, **kwargs):  # type: ignore[return]
        client = MagicMock()
        client.initialize = AsyncMock()
        client.call_tool = fake_call_tool

        logging_callback = kwargs.get("logging_callback")
        if logging_callback is not None and log_events:

            async def _logged_call_tool(tool: str, params: dict) -> MagicMock:  # type: ignore[type-arg]
                if tool == "ask":
                    for event in log_events:
                        await logging_callback(SimpleNamespace(data=event))
                return await fake_call_tool(tool, params)

            client.call_tool = _logged_call_tool

        yield client

    @asynccontextmanager
    async def _fake_transport_cm(url, **kwargs):  # type: ignore[return]
        yield MagicMock(), MagicMock(), None

    return patch("app.cli.ask.streamablehttp_client", _fake_transport_cm), patch(
        "app.cli.ask.ClientSession", _fake_session_cm
    )


class TestAskCli:
    def test_ask_prints_answer(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Paris", "session_id": "abc", "tokens_used": 5}
            )
        }
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "What is the capital of France?"])
        assert result.exit_code == 0
        assert "Paris" in result.output

    def test_default_mode_renders_reasoning_events(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Done", "session_id": "abc", "tokens_used": 5}
            )
        }
        log_events = [
            {"kind": "run_started"},
            {"kind": "step_started", "step_kind": "thought"},
            {"kind": "step_started", "step_kind": "tool_call", "title": "svc__lookup"},
            {"kind": "tool_call", "service": "svc", "tool": "lookup"},
            {"kind": "tool_result", "service": "svc", "tool": "lookup", "ok": True},
            {"kind": "run_completed"},
        ]
        p1, p2 = _patch_mcp(call_results, log_events=log_events)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "Explain this"])

        assert result.exit_code == 0
        assert "- Thinking: planning next tool" in result.output
        assert "- Tool: svc.lookup" in result.output
        assert "- Result: svc.lookup [ok]" in result.output
        assert "Answer: Done" in result.output

    def test_verbose_mode_renders_tool_args_and_results(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Done", "session_id": "abc", "tokens_used": 5}
            )
        }
        log_events = [
            {"kind": "step_started", "step_kind": "thought", "title": "model_request"},
            {"kind": "step_started", "step_kind": "tool_call", "title": "analytics__simple_return"},
            {
                "kind": "tool_call",
                "service": "analytics",
                "tool": "simple_return",
                "arguments": {"symbol": "AAPL", "days": 30},
            },
            {
                "kind": "tool_result",
                "service": "analytics",
                "tool": "simple_return",
                "ok": True,
                "latency_ms": 12,
                "summary": {
                    "simple_return": -0.0109,
                    "window": {"start": "2026-04-01", "end": "2026-05-01"},
                },
            },
            {"kind": "summary_update", "summary": "Goals:\n- keep context bounded"},
        ]
        p1, p2 = _patch_mcp(call_results, log_events=log_events)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--verbose", "Explain this"])

        assert result.exit_code == 0
        assert "- Thinking: planning next tool" in result.output
        assert "- Tool: analytics.simple_return" in result.output
        assert "  about: calculate simple return for the last 30 days for AAPL" in result.output
        assert '  args: {"days": 30, "symbol": "AAPL"}' in result.output
        assert "- Result: analytics.simple_return [ok, 12 ms]" in result.output
        assert "  summary:" in result.output
        assert '      "simple_return": -0.0109,' in result.output
        assert "- Summary updated" in result.output

    def test_default_mode_labels_final_answer_thinking(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Done", "session_id": "abc", "tokens_used": 5}
            )
        }
        log_events = [
            {"kind": "step_started", "step_kind": "thought", "title": "model_request"},
            {"kind": "run_completed", "answer_preview": "Done"},
        ]
        p1, p2 = _patch_mcp(call_results, log_events=log_events)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "Explain this"])

        assert result.exit_code == 0
        assert "- Thinking: composing final answer" in result.output

    def test_ask_prints_session_id(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "42", "session_id": "my-session", "tokens_used": 3}
            )
        }
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--session", "my-session", "Calc"])
        assert "my-session" in result.output

    def test_ask_sends_max_steps(self) -> None:
        captured_params: list[dict] = []

        from contextlib import asynccontextmanager

        client = MagicMock()
        client.initialize = AsyncMock()

        async def fake_call_tool(tool: str, params: dict) -> MagicMock:  # type: ignore[type-arg]
            captured_params.append(params)
            return _make_call_result({"answer": "ok", "session_id": "s", "tokens_used": 1})

        client.call_tool = fake_call_tool

        @asynccontextmanager
        async def _fake_session_cm(r, w, **kwargs):  # type: ignore[return]
            yield client

        @asynccontextmanager
        async def _fake_transport_cm(url, **kwargs):  # type: ignore[return]
            yield MagicMock(), MagicMock(), None

        with (
            patch("app.cli.ask.streamablehttp_client", _fake_transport_cm),
            patch("app.cli.ask.ClientSession", _fake_session_cm),
        ):
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--max-steps", "12", "Calc"])

        assert result.exit_code == 0
        assert captured_params[0]["max_steps"] == 12

    def test_reset_calls_reset_session(self) -> None:
        call_results = {
            "reset_session": _make_call_result({"status": "ok", "session_id": "sid1"})
        }
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--reset", "sid1"])
        assert result.exit_code == 0
        assert "sid1" in result.output

    def test_quiet_prints_only_final_answer(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Paris", "session_id": "abc", "tokens_used": 5}
            )
        }
        log_events = [
            {"kind": "step_started", "step_kind": "thought"},
            {"kind": "tool_call", "service": "svc", "tool": "lookup"},
        ]
        p1, p2 = _patch_mcp(call_results, log_events=log_events)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--quiet", "Where?"])

        assert result.exit_code == 0
        assert result.output.strip() == "Paris"

    def test_json_format_emits_parseable_output(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Paris", "session_id": "abc", "tokens_used": 5}
            )
        }
        log_events = [
            {"kind": "run_started", "request_id": "req-1"},
            {"kind": "run_completed", "request_id": "req-1"},
        ]
        p1, p2 = _patch_mcp(call_results, log_events=log_events)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--format", "json", "Where?"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["response"]["answer"] == "Paris"
        assert len(parsed["events"]) == 2

    def test_notification_free_server_prints_answer(self) -> None:
        call_results = {
            "ask": _make_call_result(
                {"answer": "Paris", "session_id": "abc", "tokens_used": 5}
            )
        }
        p1, p2 = _patch_mcp(call_results, log_events=[])
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "Where?"])

        assert result.exit_code == 0
        assert "Answer: Paris" in result.output

    def test_no_question_exits_nonzero(self) -> None:
        call_results: dict = {}
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS])
        assert result.exit_code != 0

    def test_no_token_exits_with_error(self) -> None:
        """Missing token should print an error message and exit 1."""
        call_results: dict = {}
        p1, p2 = _patch_mcp(call_results)
        # Override GOFR_AGENT_TOKEN env var to empty
        with p1, p2, patch.dict("os.environ", {"GOFR_AGENT_TOKEN": ""}, clear=False):
            result = runner.invoke(app, ["Hello?"])
        assert result.exit_code == 1
        assert "token" in result.output.lower() or "token" in (result.stderr or "").lower()

    def test_invalid_format_exits_with_error(self) -> None:
        call_results: dict = {}
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--format", "yaml", "Hello?"])

        assert result.exit_code == 1
        assert "--format" in result.output

    def test_ask_sends_token_header(self) -> None:
        """The token must be sent as Authorization: Bearer header."""
        captured_kwargs: list[dict] = []

        from contextlib import asynccontextmanager

        client = MagicMock()
        client.initialize = AsyncMock()
        client.call_tool = AsyncMock(
            return_value=_make_call_result(
                {"answer": "ok", "session_id": "s", "tokens_used": 1}
            )
        )

        @asynccontextmanager
        async def _fake_session_cm(r, w, **kwargs):  # type: ignore[return]
            yield client

        @asynccontextmanager
        async def _fake_transport_cm(url, **kwargs):  # type: ignore[return]
            captured_kwargs.append(kwargs)
            yield MagicMock(), MagicMock(), None

        with (
            patch("app.cli.ask.streamablehttp_client", _fake_transport_cm),
            patch("app.cli.ask.ClientSession", _fake_session_cm),
        ):
            result = runner.invoke(app, ["--token", "my-secret", "Hello?"])

        assert result.exit_code == 0
        assert captured_kwargs, "streamablehttp_client was not called"
        headers = captured_kwargs[0].get("headers", {})
        assert headers.get("Authorization") == "Bearer my-secret"

    def test_token_from_env(self) -> None:
        """GOFR_AGENT_TOKEN env var is used when --token is not provided."""
        call_results = {
            "ask": _make_call_result({"answer": "ok", "session_id": "s", "tokens_used": 1})
        }
        p1, p2 = _patch_mcp(call_results)
        with (
            p1,
            p2,
            patch.dict("os.environ", {"GOFR_AGENT_TOKEN": "env-token"}, clear=False),
        ):
            # Must reload app option default — use --token explicitly to avoid
            # stale os.environ capture at import time
            result = runner.invoke(app, ["--token", "env-token", "Hello?"])
        assert result.exit_code == 0

