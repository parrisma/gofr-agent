"""Test-only prompt capture helpers for prompt-hardening snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.agent import GofrAgent
from app.agent.system_prompt import build_system_prompt
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo
from tests.helpers.prompt_hardening_report import redact_report_text


@dataclass(frozen=True)
class CapturedPrompt:
    """One redacted model-visible prompt snapshot."""

    name: str
    text: str


def capture_system_prompt(
    *,
    services: list[ServiceConfig],
    tools: list[MCPToolInfo],
    hardened: bool = True,
) -> CapturedPrompt:
    """Render and redact a system prompt for deterministic assertions."""
    prompt = build_system_prompt(
        services,
        tools,
        prompt_hardening_v2_enabled=hardened,
    )
    return CapturedPrompt(name="system", text=redact_report_text(prompt))


def capture_full_prompt(
    *,
    question: str,
    context: str | None = None,
    session_summary: str = "",
    instructions: str | None = None,
    asserted_facts: list[str] | None = None,
    pasted_content: list[str] | None = None,
    structured: bool = True,
) -> CapturedPrompt:
    """Render and redact a user prompt without invoking a model."""
    prompt = GofrAgent._build_full_prompt(
        question,
        context,
        session_summary,
        caller_content_structured_enabled=structured,
        instructions=instructions,
        asserted_facts=asserted_facts,
        pasted_content=pasted_content,
    )
    return CapturedPrompt(name="user", text=redact_report_text(prompt))
