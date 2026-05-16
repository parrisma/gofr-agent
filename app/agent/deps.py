"""Per-run dependencies passed to pydantic-ai tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolArtifact:
    """Structured output captured from a downstream tool call."""

    artifact_id: str
    service: str
    tool: str
    arguments: dict[str, Any]
    value: Any


@dataclass
class AgentDeps:
    """Dependencies shared by tools during one agent run."""

    token: str
    artifacts: list[ToolArtifact] = field(default_factory=list)

    def remember_tool_result(
        self,
        *,
        service: str,
        tool: str,
        arguments: dict[str, Any],
        value: Any,
    ) -> str:
        artifact_id = f"tool_result_{len(self.artifacts) + 1}"
        self.artifacts.append(
            ToolArtifact(
                artifact_id=artifact_id,
                service=service,
                tool=tool,
                arguments=dict(arguments),
                value=value,
            )
        )
        return artifact_id
