"""Integration tests for GofrAgent with a live mock MCP backend.

Uses ``pydantic_ai.models.test.TestModel`` (via llm_model="test") so no real
LLM is contacted.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.agent import GofrAgent
from app.auth import ALL_ACTIVITIES
from app.config import GofrAgentConfig
from app.services import ServiceConfig, ServicesManifest
from app.services.registry import ServiceRegistry
from app.sessions.store import SessionStore

_TOKEN = "allow-all"


class _AllowAll:
    """Auth service that grants every activity to every token."""

    def authorised_activities(self, token: str) -> str:  # noqa: ARG002
        return ",".join(ALL_ACTIVITIES + ["MCPServer*"])


def _config() -> GofrAgentConfig:
    return GofrAgentConfig(llm_model="test")


def _manifest(url: str) -> ServicesManifest:
    svc = ServiceConfig(name="mock", url=url, description="Mock test service")
    return ServicesManifest(services=[svc])


@pytest.fixture()
async def registry(mock_mcp_url: str) -> ServiceRegistry:
    reg = ServiceRegistry(_config())
    await reg.load_manifest(_manifest(mock_mcp_url))
    yield reg  # type: ignore[misc]
    await reg.shutdown()


@pytest.fixture()
def session_store() -> SessionStore:
    return SessionStore(ttl_minutes=60)


class TestAgentIntegration:
    async def test_agent_answers_with_test_model(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """TestModel returns a canned answer — verifies pipeline end-to-end."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        session = await session_store.get_or_create("s1")
        result = await agent.run("Hello", session, token=_TOKEN)

        assert isinstance(result.answer, str)
        assert len(result.answer) > 0

    async def test_session_history_accumulates(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """Messages are stored after each call."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        session = await session_store.get_or_create("s2")
        await agent.run("First question", session, token=_TOKEN)
        msg_count_after_first = len(session.messages)

        await agent.run("Second question", session, token=_TOKEN)
        msg_count_after_second = len(session.messages)

        assert msg_count_after_second > msg_count_after_first

    async def test_concurrent_sessions_isolated(
        self, registry: ServiceRegistry, session_store: SessionStore
    ) -> None:
        """Two concurrent sessions should not interfere with each other."""
        config = _config()
        agent = GofrAgent(config, registry, _AllowAll())
        agent.build()

        s1 = await session_store.get_or_create("concurrent-1")
        s2 = await session_store.get_or_create("concurrent-2")

        await asyncio.gather(
            agent.run("Question A", s1, token=_TOKEN),
            agent.run("Question B", s2, token=_TOKEN),
        )

        # Sessions remain independent
        assert s1.messages is not s2.messages
        assert len(s1.messages) > 0
        assert len(s2.messages) > 0
