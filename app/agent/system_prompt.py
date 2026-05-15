"""Build the system prompt for GofrAgent from registry state."""

from __future__ import annotations

from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo

_PREAMBLE = """\
You are a reasoning agent with access to the following tools provided by \
downstream MCP services.

Use tools when they can answer the user's question more accurately or completely \
than you can from memory alone.
When you have enough information, answer directly without calling tools.
Always cite which tool or service provided the information you used.
"""

_FOOTER = """\

If no tool is relevant, answer from your own knowledge and say so explicitly.
"""


def build_system_prompt(
    services: list[ServiceConfig],
    tool_infos: list[MCPToolInfo],
) -> str:
    """Assemble a system prompt listing services and their available tools.

    Args:
        services: All registered :class:`~app.services.ServiceConfig` objects.
        tool_infos: All discovered :class:`~app.services.discovery.MCPToolInfo`
            objects (may span multiple services).

    Returns:
        A plain-text system prompt suitable for passing to pydantic-ai.
    """
    lines: list[str] = [_PREAMBLE]

    if not services:
        lines.append("(No downstream services are currently registered.)")
    else:
        lines.append("## Available Services\n")
        # Index tools by service name
        by_service: dict[str, list[MCPToolInfo]] = {}
        for ti in tool_infos:
            by_service.setdefault(ti.service_name, []).append(ti)

        for svc in services:
            lines.append(f"### {svc.name}")
            if svc.description:
                lines.append(f"  {svc.description}")
            svc_tools = by_service.get(svc.name, [])
            if svc_tools:
                for ti in svc_tools:
                    lines.append(f"  - `{ti.service_name}__{ti.name}`: {ti.description}")
            else:
                lines.append("  (no tools discovered)")
            lines.append("")

    lines.append(_FOOTER)
    return "\n".join(lines)
