"""Per-run dependencies passed to pydantic-ai tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.agent.contracts import IntentConstraints, ProvenanceRecord, VerificationGapAttempt


def canonical_args_hash(arguments: dict[str, Any]) -> str:
    """Return a stable hash for JSON-serialisable tool arguments."""

    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ToolArtifact:
    """Structured output captured from a downstream tool call."""

    artifact_id: str
    service: str
    tool: str
    arguments: dict[str, Any]
    args_hash: str
    value: Any


@dataclass
class AgentDeps:
    """Dependencies shared by tools during one agent run."""

    token: str
    request_id: str = "unknown-request"
    session_id: str = "unknown-session"
    run_id: str | None = None
    intent_constraints: IntentConstraints = field(default_factory=IntentConstraints)
    artifacts: list[ToolArtifact] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    verification_attempts: list[VerificationGapAttempt] = field(default_factory=list)

    def remember_tool_result(
        self,
        *,
        service: str,
        tool: str,
        arguments: dict[str, Any],
        value: Any,
    ) -> str:
        args_hash = canonical_args_hash(arguments)
        artifact_id = f"tool_result_{len(self.artifacts) + 1}"
        self.artifacts.append(
            ToolArtifact(
                artifact_id=artifact_id,
                service=service,
                tool=tool,
                arguments=dict(arguments),
                args_hash=args_hash,
                value=value,
            )
        )
        return artifact_id

    def record_tool_call(
        self,
        *,
        service: str,
        tool: str,
        arguments: dict[str, Any],
        attempt: int,
        ok: bool,
        latency_ms: int | None = None,
        truncated: bool = False,
        artifact_id: str | None = None,
        as_of: str | None = None,
        outcome: str | None = None,
    ) -> ProvenanceRecord:
        args_hash = canonical_args_hash(arguments)
        record = ProvenanceRecord(
            request_id=self.request_id,
            service=service,
            tool=tool,
            args_hash=args_hash,
            artifact_id=artifact_id,
            attempt=attempt,
            ok=ok,
            latency_ms=latency_ms,
            truncated=truncated,
            as_of=as_of,
        )
        self.provenance.append(record)
        self.verification_attempts.append(
            VerificationGapAttempt(
                service=service,
                tool=tool,
                args_summary={"args_hash": args_hash},
                outcome=outcome or ("ok" if ok else "tool_error"),
            )
        )
        return record
