"""Conservative post-run grounding checks."""

from __future__ import annotations

import re

from app.agent.contracts import IntentConstraints, VerificationGap, VerificationGapReason
from app.agent.verification import attempts_from_steps, build_verification_gap
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo

_DIGIT_RE = re.compile(r"\d")
_NUMERIC_HINT_RE = re.compile(
    r"\b(price|return|quantity|volatility|pnl|value|amount|number|count|numeric)\b",
    re.IGNORECASE,
)
_CONTRADICTION_KEYS = {"currency", "exchange", "isin", "primary_mic", "sector"}


def _tool_calls(steps: list[dict]) -> list[dict]:
    return [step for step in steps if step.get("kind") == "tool_call"]


def _tool_results(steps: list[dict]) -> list[dict]:
    return [step for step in steps if step.get("kind") == "tool_result"]


def _registered_numeric_tool_exists(tools: list[MCPToolInfo]) -> bool:
    for tool in tools:
        text = f"{tool.name} {tool.description}"
        if _NUMERIC_HINT_RE.search(text):
            return True
    return False


def _relevant_service_names(question: str, services: list[ServiceConfig]) -> list[str]:
    lowered = question.lower()
    return [service.name for service in services if service.name.lower() in lowered]


def _failed_result_reason(results: list[dict]) -> VerificationGapReason:
    for result in results:
        summary = str(result.get("summary", "")).lower()
        if "forbidden" in summary or "outside allowed_services" in summary:
            return "constraint_blocked"
    return "tool_error"


def _scalar(value: object) -> str | None:
    if isinstance(value, str | int | float | bool):
        return str(value)
    return None


def _has_contradictory_results(results: list[dict]) -> bool:
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    for result in results:
        if result.get("ok") is False:
            continue
        summary = result.get("summary")
        if not isinstance(summary, dict):
            continue
        ticker = _scalar(summary.get("ticker")) or ""
        source = f"{result.get('service', '')}.{result.get('tool', '')}"
        for key in _CONTRADICTION_KEYS:
            value = _scalar(summary.get(key))
            if value is None:
                continue
            fact_key = (ticker, key)
            previous = seen.get(fact_key)
            if previous is None:
                seen[fact_key] = (value, source)
                continue
            previous_value, previous_source = previous
            if value != previous_value and source != previous_source:
                return True
    return False


def assess_grounding(
    *,
    request_id: str,
    question: str,
    answer: str,
    steps: list[dict],
    services: list[ServiceConfig],
    tools: list[MCPToolInfo],
    constraints: IntentConstraints,
) -> VerificationGap | None:
    """Return a verification gap if deterministic grounding rules fail."""

    calls = _tool_calls(steps)
    results = _tool_results(steps)
    answer_has_digit = _DIGIT_RE.search(answer) is not None

    if _has_contradictory_results(results):
        return build_verification_gap(
            request_id=request_id,
            requested_fact=question,
            reason="contradiction",
            attempted=attempts_from_steps(steps),
        )

    if constraints.tools_only and not calls and not results:
        reason = "no_service_registered" if not services else "tool_error"
        return build_verification_gap(
            request_id=request_id,
            requested_fact=question,
            reason=reason,
            attempted=attempts_from_steps(steps),
        )

    if answer_has_digit and not calls and _registered_numeric_tool_exists(tools):
        return build_verification_gap(
            request_id=request_id,
            requested_fact=question,
            reason="no_service_registered" if not services else "tool_error",
            attempted=attempts_from_steps(steps),
        )

    if results and all(result.get("ok") is False for result in results) and (
        answer_has_digit or constraints.tools_only
    ):
        return build_verification_gap(
            request_id=request_id,
            requested_fact=question,
            reason=_failed_result_reason(results),
            attempted=attempts_from_steps(steps),
        )

    if _relevant_service_names(question, services) and answer_has_digit and not calls:
        return build_verification_gap(
            request_id=request_id,
            requested_fact=question,
            reason="tool_error",
            attempted=attempts_from_steps(steps),
        )

    return None
