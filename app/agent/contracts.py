"""Prompt-hardening contract models shared by agent surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VerificationGapReason = Literal[
    "no_service_registered",
    "tool_error",
    "empty_result",
    "schema_mismatch",
    "contradiction",
    "policy_denied",
    "constraint_blocked",
    "max_steps_reached",
]

AgentRunStatus = Literal["completed", "waiting_for_user", "cancelled"]
OutputFormat = Literal["json", "text"]


class StrictContractModel(BaseModel):
    """Base model for JSON-only contract payloads."""

    model_config = ConfigDict(extra="forbid")


class IntentConstraints(StrictContractModel):
    """Requester-supplied constraints that shape tool use and output."""

    forbidden_services: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    allowed_services: list[str] = Field(default_factory=list)
    tools_only: bool = False
    output_format: OutputFormat | None = None
    no_commentary: bool = False


class VerificationGapAttempt(StrictContractModel):
    """One attempted or considered verification source."""

    service: str | None = None
    tool: str | None = None
    args_summary: dict[str, Any] | str | None = None
    outcome: str


class VerificationGap(StrictContractModel):
    """Structured response when a factual request cannot be verified."""

    request_id: str
    requested_fact: str
    attempted: list[VerificationGapAttempt] = Field(default_factory=list)
    reason: VerificationGapReason
    options: list[str] = Field(default_factory=list)


class ClarificationRequest(StrictContractModel):
    """Structured ask-back for materially under-specified requests."""

    request_id: str
    question: str
    missing_fields: list[str]
    reason: str
    prompt: str


class HumanInputRequest(StrictContractModel):
    """Bounded prompt asking the caller for deterministic missing input."""

    prompt_id: str
    run_id: str
    session_id: str
    prompt: str
    input_schema: dict[str, Any] | None = None
    choices: list[str] | None = None
    created_at: datetime
    expires_at: datetime
    missing_fields: list[str] = Field(default_factory=list)


class HumanInputResponse(StrictContractModel):
    """Caller response to a pending human-input prompt."""

    session_id: str
    prompt_id: str
    value: Any


class ProvenanceRecord(StrictContractModel):
    """Recorded source for a tool-derived fact or tool attempt."""

    request_id: str
    service: str
    tool: str
    args_hash: str
    artifact_id: str | None = None
    attempt: int = 1
    ok: bool = True
    latency_ms: int | None = None
    truncated: bool = False
    as_of: str | None = None


class FactualClaimRecord(StrictContractModel):
    """A factual claim and its supporting provenance."""

    claim: str
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    verified: bool = False
    as_of: str | None = None
