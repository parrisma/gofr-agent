"""Factory that converts MCPToolInfo objects into pydantic-ai Tool instances."""

from __future__ import annotations

import re
from typing import Any

from mcp.types import TextContent
from pydantic_ai import Tool
from pydantic_ai._run_context import RunContext

from app.auth.auth_service import AuthService
from app.auth.permissions import downstream_activity, require_activity
from app.services.discovery import MCPToolInfo
from app.services.pool import SessionPool

_URL_RE = re.compile(r"https?://\S+")


def truncate_result(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, appending a notice if cut.

    If a URL is found in the original text it is preserved in the notice.
    """
    if len(text) <= max_chars:
        return text
    match = _URL_RE.search(text)
    if match:
        return text[:max_chars] + f"\n[... truncated. URL: {match.group()}]"
    return text[:max_chars] + "\n[... truncated]"


def make_tool(
    pool: SessionPool,
    info: MCPToolInfo,
    auth_service: AuthService,
    max_chars: int = 8000,
) -> Tool:  # type: ignore[type-arg]
    """Build a pydantic-ai :class:`Tool` that calls *info* via *pool*.

    The tool name is ``"<service_name>__<tool_name>"`` so names stay unique
    across multiple registered services.  The *auth_service* is used to
    authorise the downstream activity before making the call.
    """
    tool_name = f"{info.service_name}__{info.name}"
    tool_description = info.description
    activity = downstream_activity(info.service_name, info.name)

    async def _call(ctx: RunContext[str], **kwargs: Any) -> str:
        token: str = ctx.deps
        require_activity(auth_service, token, activity)
        async with pool.open_user_session(token) as session:
            result = await session.call_tool(info.name, kwargs)
        # Extract text content from MCP result (skip non-text content types)
        text_parts: list[str] = []
        for content in result.content:
            if isinstance(content, TextContent):
                text_parts.append(content.text)
        combined = "\n".join(text_parts)
        return truncate_result(combined, max_chars)

    return Tool(
        _call,
        name=tool_name,
        description=tool_description,
    )

