"""Deterministic verification-gap and clarification helpers."""

from __future__ import annotations

import re

from app.agent.contracts import (
    ClarificationRequest,
    VerificationGap,
    VerificationGapAttempt,
    VerificationGapReason,
)

_TICKER_RE = re.compile(r"\b[A-Z]{1,6}\b")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FINANCE_RETURN_RE = re.compile(
    r"\b(?:compute|calculate|get|show|what(?:'s| is)|compare|estimate)\b"
    r"[^.?!]{0,80}\breturns?\b"
    r"|\breturns?\b[^.?!]{0,80}\b(?:for|of|on|over|between|from)\b"
)

DEFAULT_GAP_OPTIONS = [
    "register a service that can verify the requested fact",
    "supply the fact as caller-asserted input",
    "narrow the request to a verifiable or non-factual part",
]


def build_verification_gap(
    *,
    request_id: str,
    requested_fact: str,
    reason: VerificationGapReason,
    attempted: list[VerificationGapAttempt] | None = None,
    options: list[str] | None = None,
) -> VerificationGap:
    """Build a structured verification-gap response."""

    return VerificationGap(
        request_id=request_id,
        requested_fact=requested_fact,
        attempted=attempted or [],
        reason=reason,
        options=options or list(DEFAULT_GAP_OPTIONS),
    )


def build_clarification_request(
    *,
    request_id: str,
    question: str,
    missing_fields: list[str],
    reason: str = "materially_under_specified",
) -> ClarificationRequest:
    """Build a structured clarification request."""

    fields = ", ".join(missing_fields)
    return ClarificationRequest(
        request_id=request_id,
        question=question,
        missing_fields=missing_fields,
        reason=reason,
        prompt=f"Please provide the missing field(s): {fields}.",
    )


def detect_missing_fields(question: str) -> list[str]:
    """Conservatively detect missing fields for common finance questions."""

    lowered = question.lower()
    missing: list[str] = []
    asks_for_return = _FINANCE_RETURN_RE.search(lowered) is not None
    finance_terms = ("volatility", "holding", "price", "trades", "pnl")
    asks_for_finance_fact = asks_for_return or any(term in lowered for term in finance_terms)
    if asks_for_finance_fact and _TICKER_RE.search(question) is None:
        missing.append("ticker")
    if (
        (asks_for_return or any(term in lowered for term in ("volatility", "performance")))
        and _DATE_RE.search(question) is None
        and "last " not in lowered
    ):
        missing.append("date_range")
    if "volatility" in lowered and "day" not in lowered and "window" not in lowered:
        missing.append("window")
    if "holding" in lowered and "client" not in lowered and not re.search(r"\bC\d{3}\b", question):
        missing.append("client_id")
    return missing


def attempts_from_steps(steps: list[dict]) -> list[VerificationGapAttempt]:
    """Build gap attempts from collected reasoning steps."""

    attempts: list[VerificationGapAttempt] = []
    latest_args: dict[tuple[str | None, str | None], dict] = {}
    for step in steps:
        if step.get("kind") == "tool_call":
            key = (step.get("service"), step.get("tool"))
            args = step.get("arguments")
            latest_args[key] = args if isinstance(args, dict) else {}
            continue
        if step.get("kind") != "tool_result":
            continue
        service = step.get("service") if isinstance(step.get("service"), str) else None
        tool = step.get("tool") if isinstance(step.get("tool"), str) else None
        key = (service, tool)
        outcome = "ok" if step.get("ok") else "tool_error"
        attempts.append(
            VerificationGapAttempt(
                service=service,
                tool=tool,
                args_summary=latest_args.get(key, {}),
                outcome=outcome,
            )
        )
    return attempts
