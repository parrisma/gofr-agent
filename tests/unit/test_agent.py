"""Tests for app.agent.agent.GofrAgent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.agent import AgentResult, GofrAgent
from app.config import GofrAgentConfig
from app.services.discovery import MCPToolInfo
from app.services.registry import ServiceRegistry
from app.sessions.store import Session, SessionStore


def _make_config(**kw) -> GofrAgentConfig:  # type: ignore[no-untyped-def]
    defaults = {"llm_model": "test"}
    defaults.update(kw)
    return GofrAgentConfig(**defaults)


def _make_registry(tools: list[MCPToolInfo] | None = None) -> MagicMock:
    reg = MagicMock(spec=ServiceRegistry)
    reg.all_tools = tools or []
    reg.all_pools = {}
    reg.all_service_configs = []
    reg.get_pool = MagicMock(return_value=None)
    return reg


class TestGofrAgentBuild:
    def test_build_creates_agent(self) -> None:
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)
        ga.build()
        assert ga._agent is not None

    def test_rebuild_replaces_agent(self) -> None:
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)
        ga.build()
        first = ga._agent
        ga.rebuild()
        assert ga._agent is not first

    def test_run_before_build_raises(self) -> None:
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)
        store = SessionStore()

        async def _run() -> None:
            sess = await store.get_or_create(None)
            await ga.run("hello", sess)

        with pytest.raises(RuntimeError, match="build"):
            asyncio.get_event_loop().run_until_complete(_run())


class TestGofrAgentRun:
    async def test_run_returns_agent_result(self) -> None:
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)

        with patch("app.agent.agent.Agent") as MockAgent:
            mock_agent_inst = MagicMock()
            MockAgent.return_value = mock_agent_inst

            # Simulate run_stream context manager
            stream_result = MagicMock()

            async def _text_stream(delta: bool = False):  # type: ignore[return]
                for chunk in ["Hello ", "world"]:
                    yield chunk

            stream_result.stream_text = _text_stream
            stream_result.new_messages = MagicMock(return_value=[])
            stream_result.usage = MagicMock(return_value=MagicMock(total_tokens=42))

            mock_agent_inst.run_stream = _async_cm(stream_result)
            ga._agent = mock_agent_inst

            store = SessionStore()
            sess = await store.get_or_create(None)
            result = await ga.run("What is 2+2?", sess)

        assert isinstance(result, AgentResult)
        assert result.answer == "Hello world"
        assert result.tokens_used == 42

    async def test_run_appends_to_session_messages(self) -> None:
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)

        new_msgs = [MagicMock(), MagicMock()]

        with patch("app.agent.agent.Agent") as MockAgent:
            mock_agent_inst = MagicMock()
            MockAgent.return_value = mock_agent_inst

            stream_result = MagicMock()

            async def _ok_text(delta: bool = False):  # type: ignore[return]
                yield "ok"

            stream_result.stream_text = _ok_text
            stream_result.new_messages = MagicMock(return_value=new_msgs)
            stream_result.usage = MagicMock(return_value=None)

            mock_agent_inst.run_stream = _async_cm(stream_result)
            ga._agent = mock_agent_inst

            store = SessionStore()
            sess = await store.get_or_create(None)
            await ga.run("hello", sess)

        assert sess.messages == new_msgs

    async def test_concurrent_different_sessions_no_contention(self) -> None:
        """Two sessions can run concurrently."""
        config = _make_config()
        reg = _make_registry()
        ga = GofrAgent(config, reg)

        call_order: list[int] = []

        async def mock_run(sess_id: int, sess: Session) -> None:
            stream_result = MagicMock()

            async def _text_gen():  # type: ignore[return]
                call_order.append(sess_id)
                await asyncio.sleep(0.01)
                yield f"answer-{sess_id}"

            stream_result.stream_text = MagicMock(return_value=_text_gen())
            stream_result.new_messages = MagicMock(return_value=[])
            stream_result.usage = MagicMock(return_value=None)

            with patch.object(ga, "_agent") as mock_ag:
                mock_ag.run_stream = _async_cm(stream_result)
                await ga.run(f"q{sess_id}", sess)

        store = SessionStore()
        s1 = await store.get_or_create(None)
        s2 = await store.get_or_create(None)

        await asyncio.gather(mock_run(1, s1), mock_run(2, s2))
        assert set(call_order) == {1, 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(items: list[str]):  # type: ignore[return]
    for item in items:
        yield item


def _async_cm(result: MagicMock):  # type: ignore[return]
    """Return a mock that acts as an async context manager yielding *result*."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)

    def _factory(*args, **kwargs):  # type: ignore[return]
        return cm

    return _factory
