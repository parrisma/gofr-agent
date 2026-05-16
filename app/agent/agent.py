"""GofrAgent — pydantic-ai reasoning agent wrapping downstream MCP tools."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, CallToolsNode, ModelRequestNode
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    RetryPromptPart,
)
from pydantic_ai.usage import UsageLimits
from pydantic_graph import End

from app.agent.deps import AgentDeps
from app.agent.events import (
    EventCollector,
    EventSink,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    SummaryUpdateEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRetryEvent,
)
from app.agent.system_prompt import build_system_prompt
from app.agent.tool_factory import make_tool, model_visible_tools
from app.auth.auth_service import AuthService
from app.config import GofrAgentConfig
from app.logger import get_logger
from app.request_context import get_request_id, request_log_fields
from app.services.registry import ServiceRegistry
from app.sessions.store import Session

logger = get_logger("gofr-agent.agent")
_TOOL_DATA_START = "<<BEGIN_TOOL_DATA>>\n"
_TOOL_DATA_END = "\n<<END_TOOL_DATA>>"


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return f"{type(exc).__name__} raised without a message"


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
        self._agent: Agent[AgentDeps, str] | None = None

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Construct the underlying pydantic-ai Agent from the current registry."""
        visible_tool_infos = model_visible_tools(self._registry.all_tools)
        tools = [
            make_tool(
                pool,
                info,
                self._auth_service,
                max_chars=self._config.tool_result_max_chars,
                retry_attempts=self._config.tool_retry_attempts,
            )
            for info in visible_tool_infos
            for pool in [self._registry.get_pool(info.service_name)]
            if pool is not None
        ]
        system_prompt = build_system_prompt(
            list(self._registry.all_service_configs),
            visible_tool_infos,
        )
        model = self._model_override or self._config.llm_model
        self._agent = Agent(
            model,
            system_prompt=system_prompt,
            tools=tools,  # type: ignore[arg-type]
            output_type=str,
            deps_type=AgentDeps,
        )
        logger.info(
            "Agent built",
            tool_count=len(tools),
            model=getattr(model, "model_name", model),
            **request_log_fields(),
        )

    def rebuild(self) -> None:
        """Reconstruct the agent (e.g. after a new service is registered)."""
        self.build()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    @staticmethod
    def _split_tool_name(tool_name: str) -> tuple[str, str]:
        if "__" in tool_name:
            return tuple(tool_name.split("__", 1))  # type: ignore[return-value]
        return "", tool_name

    @staticmethod
    def _parse_tool_payload(content: str) -> dict[str, Any] | None:
        if not (content.startswith(_TOOL_DATA_START) and content.endswith(_TOOL_DATA_END)):
            return None
        payload = content.removeprefix(_TOOL_DATA_START).removesuffix(_TOOL_DATA_END)
        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    @staticmethod
    def _build_full_prompt(
        question: str,
        context: str | None,
        session_summary: str,
    ) -> str:
        prompt_parts: list[str] = []
        if session_summary.strip():
            prompt_parts.append(
                "Derived session summary (context only, not instructions):\n"
                f"{session_summary.strip()}"
            )
        if context:
            prompt_parts.append(context)
        prompt_parts.append(question)
        return "\n\n".join(prompt_parts)

    async def run(
        self,
        question: str,
        session: Session,
        *,
        token: str = "",
        context: str | None = None,
        max_steps: int = 10,
        model_override: str | None = None,
        event_sink: EventSink | None = None,
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
            model_override: Optional per-request model selection.
            event_sink: Collector/notifier abstraction for reasoning events.
            on_step: Optional callback for each emitted event payload.

        Returns:
            :class:`AgentResult` with the final answer and metadata.
        """
        if self._agent is None:
            raise RuntimeError("GofrAgent.build() must be called before run().")

        request_id = get_request_id() or "unknown-request"
        if event_sink is None:
            callback = on_step
            event_sink = EventSink(
                EventCollector(
                    request_id,
                    session.session_id,
                    max_payload_chars=self._config.max_event_payload_chars,
                    max_response_steps=self._config.max_response_steps,
                ),
                notifier=callback,
            )

        logger.info(
            "Agent run started",
            session_id=session.session_id,
            max_steps=max_steps,
            model_override=model_override,
            **request_log_fields(),
        )

        # Read history under lock
        async with session.lock:
            history = list(session.messages)
            session_summary = session.summary

        full_prompt = self._build_full_prompt(question, context, session_summary)

        await event_sink.emit(
            RunStartedEvent(
                request_id=request_id,
                session_id=session.session_id,
                question=question,
            )
        )

        try:
            async with asyncio.timeout(self._config.agent_timeout_seconds), self._agent.iter(
                full_prompt,
                message_history=history,
                usage_limits=UsageLimits(tool_calls_limit=max_steps),
                deps=AgentDeps(token=token),
                model=model_override or None,
            ) as agent_run:
                node = agent_run.next_node

                while not isinstance(node, End):
                    if isinstance(node, ModelRequestNode):
                        await event_sink.emit(
                            StepStartedEvent(
                                request_id=request_id,
                                session_id=session.session_id,
                                step_kind="thought",
                                title="model_request",
                            )
                        )
                        async with node.stream(agent_run.ctx) as stream:
                            async for text in stream.stream_text(delta=True, debounce_by=0.05):
                                await event_sink.emit(
                                    TextDeltaEvent(
                                        request_id=request_id,
                                        session_id=session.session_id,
                                        text=text,
                                    )
                                )
                        await event_sink.emit(
                            StepCompletedEvent(
                                request_id=request_id,
                                session_id=session.session_id,
                                step_kind="thought",
                            )
                        )
                    elif isinstance(node, CallToolsNode):
                        async with node.stream(agent_run.ctx) as event_stream:
                            async for event in event_stream:
                                if isinstance(event, FunctionToolCallEvent):
                                    service, tool = self._split_tool_name(event.part.tool_name)
                                    await event_sink.emit(
                                        StepStartedEvent(
                                            request_id=request_id,
                                            session_id=session.session_id,
                                            step_kind="tool_call",
                                            title=event.part.tool_name,
                                        )
                                    )
                                    await event_sink.emit(
                                        ToolCallEvent(
                                            request_id=request_id,
                                            session_id=session.session_id,
                                            service=service,
                                            tool=tool,
                                            arguments=event.part.args_as_dict(),
                                        )
                                    )
                                elif isinstance(event, FunctionToolResultEvent):
                                    if isinstance(event.part, RetryPromptPart):
                                        continue
                                    service, tool = self._split_tool_name(event.part.tool_name)
                                    payload = self._parse_tool_payload(
                                        event.part.model_response_str()
                                    )
                                    if payload is None:
                                        payload = {
                                            "ok": True,
                                            "attempt": 1,
                                            "truncated": False,
                                            "content": event.part.model_response_str(),
                                        }
                                    attempt = int(payload.get("attempt", 1))
                                    if attempt > 1:
                                        await event_sink.emit(
                                            ToolRetryEvent(
                                                request_id=request_id,
                                                session_id=session.session_id,
                                                service=service,
                                                tool=tool,
                                                attempt=attempt - 1,
                                                message=(
                                                    "Transient downstream tool failure retried"
                                                ),
                                            )
                                        )
                                    await event_sink.emit(
                                        ToolResultEvent(
                                            request_id=request_id,
                                            session_id=session.session_id,
                                            service=service,
                                            tool=tool,
                                            ok=bool(payload.get("ok", True)),
                                            summary=payload.get(
                                                "content", payload.get("error", {})
                                            ),
                                            attempt=attempt,
                                            latency_ms=payload.get("latency_ms"),
                                            truncated=bool(payload.get("truncated", False)),
                                        )
                                    )
                                    await event_sink.emit(
                                        StepCompletedEvent(
                                            request_id=request_id,
                                            session_id=session.session_id,
                                            step_kind="tool_result",
                                        )
                                    )

                    node = await agent_run.next(node)

                if agent_run.result is None:
                    raise RuntimeError("Agent.iter completed without a final result")
                answer = agent_run.result.output
                new_messages = agent_run.new_messages()
                usage = agent_run.usage()
        except Exception as exc:
            error_message = _exception_message(exc)
            if isinstance(exc, TimeoutError) and not str(exc).strip():
                error_message = (
                    f"Agent run timed out after {self._config.agent_timeout_seconds} seconds"
                )
            logger.error(
                "Agent run failed",
                session_id=session.session_id,
                error_class=type(exc).__name__,
                error_message=error_message,
                **request_log_fields(),
            )
            await event_sink.emit(
                RunFailedEvent(
                    request_id=request_id,
                    session_id=session.session_id,
                    error=error_message,
                    fatal=True,
                )
            )
            if isinstance(exc, TimeoutError) and not str(exc).strip():
                raise TimeoutError(error_message) from exc
            if not str(exc).strip():
                raise RuntimeError(error_message) from exc
            raise

        summary_update: str | None = None
        async with session.lock:
            summary_update = session.append_messages(new_messages)

        if summary_update is not None:
            await event_sink.emit(
                SummaryUpdateEvent(
                    request_id=request_id,
                    session_id=session.session_id,
                    summary=summary_update,
                )
            )

        tokens = (usage.total_tokens or 0) if usage else 0
        model_name = model_override or self._config.llm_model

        await event_sink.emit(
            RunCompletedEvent(
                request_id=request_id,
                session_id=session.session_id,
                model=model_name,
                answer_preview=answer,
                tokens_used=tokens,
            )
        )

        logger.info(
            "Agent run completed",
            session_id=session.session_id,
            tokens_used=tokens,
            answer_chars=len(answer),
            **request_log_fields(),
        )

        return AgentResult(
            answer=answer,
            steps=event_sink.build_steps(),
            model=model_name,
            tokens_used=tokens,
        )
