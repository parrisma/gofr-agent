"""Intent-constraint extraction and runtime tool-call checks."""

from __future__ import annotations

import re

from app.agent.contracts import IntentConstraints, OutputFormat

_DO_NOT_USE_SERVICE_RE = re.compile(
    r"do\s+not\s+(?:call|use)\s+(?:the\s+)?(?P<name>[a-zA-Z0-9_-]+)(?:\s+service)?",
    re.IGNORECASE,
)
_USE_ONLY_SERVICE_RE = re.compile(
    r"use\s+only\s+(?:the\s+)?(?P<name>[a-zA-Z0-9_-]+)(?:\s+service)?",
    re.IGNORECASE,
)


def _clean_names(values: list[str] | None) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in cleaned:
            cleaned.append(stripped)
    return cleaned


def build_intent_constraints(
    *,
    instructions: str | None = None,
    forbidden_services: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    allowed_services: list[str] | None = None,
    tools_only: bool | None = None,
    output_format: OutputFormat | None = None,
    no_commentary: bool | None = None,
) -> IntentConstraints:
    """Build constraints from structured fields and explicit instructions only."""

    constraints = IntentConstraints(
        forbidden_services=_clean_names(forbidden_services),
        forbidden_tools=_clean_names(forbidden_tools),
        allowed_services=_clean_names(allowed_services),
        tools_only=bool(tools_only),
        output_format=output_format,
        no_commentary=bool(no_commentary),
    )

    if instructions:
        for match in _DO_NOT_USE_SERVICE_RE.finditer(instructions):
            name = match.group("name")
            if name not in constraints.forbidden_services:
                constraints.forbidden_services.append(name)
        for match in _USE_ONLY_SERVICE_RE.finditer(instructions):
            name = match.group("name")
            if name not in constraints.allowed_services:
                constraints.allowed_services.append(name)
        lowered = instructions.lower()
        if "tools only" in lowered:
            constraints.tools_only = True
        if "no commentary" in lowered:
            constraints.no_commentary = True

    return constraints


def check_tool_allowed(
    constraints: IntentConstraints,
    *,
    service: str,
    tool: str,
) -> tuple[bool, str | None]:
    """Return whether a tool call is allowed by the current constraints."""

    full_tool_name = f"{service}__{tool}"
    dotted_tool_name = f"{service}.{tool}"
    if service in constraints.forbidden_services:
        return False, f"service '{service}' is forbidden"
    if tool in constraints.forbidden_tools or full_tool_name in constraints.forbidden_tools:
        return False, f"tool '{full_tool_name}' is forbidden"
    if dotted_tool_name in constraints.forbidden_tools:
        return False, f"tool '{dotted_tool_name}' is forbidden"
    if constraints.allowed_services and service not in constraints.allowed_services:
        return False, f"service '{service}' is outside allowed_services"
    return True, None
