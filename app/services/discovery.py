"""Tool discovery helpers for downstream MCP services."""

from __future__ import annotations

from dataclasses import dataclass

from app.exceptions import ToolDiscoveryError
from app.services import ServiceConfig
from app.services.pool import SessionPool


@dataclass
class MCPToolInfo:
    """Metadata for a single tool exposed by a downstream MCP service."""

    name: str
    description: str
    input_schema: dict  # type: ignore[type-arg]
    service_name: str
    model_visible: bool = True


def _tool_model_visible(tool: object) -> bool:
    if getattr(tool, "name", None) == "_register_results_hub":
        return False

    direct = getattr(tool, "modelVisible", None)
    if isinstance(direct, bool):
        return direct

    annotations = getattr(tool, "annotations", None)
    if isinstance(annotations, dict):
        annotated = annotations.get("modelVisible")
        if isinstance(annotated, bool):
            return annotated

    annotated = getattr(annotations, "modelVisible", None)
    if isinstance(annotated, bool):
        return annotated

    return True


async def discover_tools(
    pool: SessionPool,
    service: ServiceConfig,
) -> list[MCPToolInfo]:
    """Checkout one session and ask the service to list its tools.

    Args:
        pool: Active pool for the service.
        service: Configuration for the service (used for ``service_name``).

    Returns:
        List of :class:`MCPToolInfo` objects, one per exposed tool.

    Raises:
        :class:`~app.exceptions.ToolDiscoveryError`: If listing fails.
    """
    try:
        async with pool.checkout() as session:
            result = await session.list_tools()
    except Exception as exc:
        raise ToolDiscoveryError(
            f"Failed to discover tools for service '{service.name}': {exc}"
        ) from exc

    return [
        MCPToolInfo(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
            service_name=service.name,
            model_visible=_tool_model_visible(tool),
        )
        for tool in result.tools
    ]
