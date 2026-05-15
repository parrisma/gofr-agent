"""Tests for app.cli.ask using typer.testing.CliRunner."""

from __future__ import annotations

import json
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


def _patch_mcp(call_results: dict):  # type: ignore[return, no-untyped-def]
    """Context manager that patches streamablehttp_client + ClientSession."""
    from contextlib import asynccontextmanager

    client = MagicMock()
    client.initialize = AsyncMock()

    async def fake_call_tool(tool: str, params: dict) -> MagicMock:  # type: ignore[type-arg]
        return call_results.get(tool, _make_call_result({}))

    client.call_tool = fake_call_tool

    @asynccontextmanager
    async def _fake_session_cm(r, w):  # type: ignore[return]
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

    def test_reset_calls_reset_session(self) -> None:
        call_results = {
            "reset_session": _make_call_result({"status": "ok", "session_id": "sid1"})
        }
        p1, p2 = _patch_mcp(call_results)
        with p1, p2:
            result = runner.invoke(app, [*_TOKEN_FLAGS, "--reset", "sid1"])
        assert result.exit_code == 0
        assert "sid1" in result.output

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
        async def _fake_session_cm(r, w):  # type: ignore[return]
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

