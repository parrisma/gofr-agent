"""GofrAgent — pydantic-ai reasoning agent wrapping downstream MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from app.agent.system_prompt import build_system_prompt
from app.agent.tool_factory import make_tool
from app.auth.auth_service import AuthService
from app.config import GofrAgentConfig
from app.services.registry import ServiceRegistry
from app.sessions.store import Session

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Return value from a single :meth:`GofrAgent.run` call."""

    answer: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    tokens_used: int = 0


class GofrAgent:
    """Manages a pydantic-ai :class:`~pydantic_ai.Agent` backed by the registry.

    Call :meth:`build` once after construction (and again via :meth:`rebuild`
    whenever services change).
    """

    def __init__(
        self,
        config: GofrAgentConfig,
        registry: ServiceRegistry,
        auth_service: AuthService | None = None,
        *,
        model: Any = None,
    ) -> None:
        self._config = config
        self._registry = registry
        from app.auth.auth_service import FailClosedAuthService  # noqa: PLC0415

        self._auth_service: AuthService = auth_service or FailClosedAuthService()
        self._model_override: Any = model
        self._agent: Agent[str, str] | None = None

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Construct the underlying pydantic-ai Agent from the current registry."""
        tools = [
            make_tool(
                pool,
                info,
                self._auth_service,
                max_chars=self._config.tool_result_max_chars,
            )
            for info in self._registry.all_tools
            for pool in [self._registry.get_pool(info.service_name)]
            if pool is not None
        ]
        system_prompt = build_system_prompt(
            list(self._registry.all_service_configs),
            self._registry.all_tools,
        )
        model = self._model_override or self._config.llm_model
        self._agent = Agent(
            model,
            system_prompt=system_prompt,
            tools=tools,  # type: ignore[arg-type]
            output_type=str,
            deps_type=str,
        )
        logger.info(
            "Agent built with %d tool(s) on model '%s'.",
            len(tools),
            getattr(model, "model_name", model),
        )

    def rebuild(self) -> None:
        """Reconstruct the agent (e.g. after a new service is registered)."""
        self.build()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        question: str,
        session: Session,
        *,
        token: str = "",
        context: str | None = None,
        max_steps: int = 10,
        on_step: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> AgentResult:
        """Stream a pydantic-ai run, appending messages to *session*.

        Args:
            question: The user's question.
            session: Conversation session (history is read then updated).
            token: The caller's bearer token, forwarded as pydantic-ai deps so
                   tool functions can check downstream activity permissions.
            context: Optional extra context prepended to the question.
            max_steps: Maximum tool-call iterations.
            on_step: Async callback called for each tool-call/result event.

        Returns:
            :class:`AgentResult` with the final answer and metadata.
        """
        if self._agent is None:
            raise RuntimeError("GofrAgent.build() must be called before run().")

        full_prompt = f"{context}\n\n{question}" if context else question
        steps: list[dict[str, Any]] = []

        # Read history under lock
        async with session.lock:
            history = list(session.messages)

        async with self._agent.run_stream(
            full_prompt,
            message_history=history,
            usage_limits=UsageLimits(tool_calls_limit=max_steps),
            deps=token,
        ) as result:
            # Collect streaming text
            answer_parts: list[str] = []
            async for text in result.stream_text(delta=True):
                answer_parts.append(text)

            answer = "".join(answer_parts)

            # Collect new messages for history
            new_messages = result.new_messages()
            usage = result.usage()

        # Write history under lock
        async with session.lock:
            session.messages.extend(new_messages)

        tokens = (usage.total_tokens or 0) if usage else 0
        model_name = self._config.llm_model

        return AgentResult(
            answer=answer,
            steps=steps,
            model=model_name,
            tokens_used=tokens,
        )
