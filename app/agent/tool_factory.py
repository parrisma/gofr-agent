"""Factory that converts MCPToolInfo objects into pydantic-ai Tool instances."""

from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy
from time import perf_counter
from typing import Any

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for
from mcp.types import TextContent
from pydantic_ai import Tool
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry, SkipToolValidation

from app.agent.deps import AgentDeps
from app.auth.auth_service import AuthService
from app.auth.permissions import downstream_activity, require_activity
from app.exceptions import AuthorizationError, AuthTokenInvalidError, DownstreamToolError
from app.services.discovery import MCPToolInfo
from app.services.pool import SessionPool

_URL_RE = re.compile(r"https?://\S+")
_TOOL_DATA_START = "<<BEGIN_TOOL_DATA>>"
_TOOL_DATA_END = "<<END_TOOL_DATA>>"
_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
_DESCRIPTOR_SCHEMA_FLAG = "x-gofr-result-descriptor"
RESERVED_PROTOCOL_TOOLS = frozenset(
    {
        "_register_results_hub",
        "_store_result",
        "_get_result",
        "_describe_result",
    }
)


def is_model_visible_tool(info: MCPToolInfo) -> bool:
    """Return whether a discovered tool should be exposed to the model."""

    return info.model_visible and info.name not in RESERVED_PROTOCOL_TOOLS


def model_visible_tools(tool_infos: list[MCPToolInfo]) -> list[MCPToolInfo]:
    """Return the subset of discovered tools that are safe for model use."""

    return [info for info in tool_infos if is_model_visible_tool(info)]


def _token_from_deps(deps: AgentDeps | str) -> str:
    if isinstance(deps, AgentDeps):
        return deps.token
    return deps


def _artifacts_from_deps(deps: AgentDeps | str) -> list[Any]:
    if isinstance(deps, AgentDeps):
        return deps.artifacts
    return []


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


def _wrap_tool_payload(payload: dict[str, Any]) -> str:
    return f"{_TOOL_DATA_START}\n{json.dumps(payload, ensure_ascii=True)}\n{_TOOL_DATA_END}"


def _normalise_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict) or not schema:
        return deepcopy(_DEFAULT_INPUT_SCHEMA)

    normalised = deepcopy(schema)
    if normalised.get("type") is None:
        normalised["type"] = "object"
    if normalised.get("type") == "object" and not isinstance(normalised.get("properties"), dict):
        normalised["properties"] = {}
    return normalised


def _required_arg_names(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [name for name in required if isinstance(name, str)]


def _property_schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    prop_schema = properties.get(name)
    return prop_schema if isinstance(prop_schema, dict) else {}


def _is_descriptor_property(schema: dict[str, Any]) -> bool:
    return schema.get(_DESCRIPTOR_SCHEMA_FLAG) is True


def _schema_type(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    return schema_type if isinstance(schema_type, str) else ""


def _candidate_matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    if not schema:
        return True
    try:
        validator_for(schema)(schema).validate(value)
    except JsonSchemaValidationError:
        return False
    return True


def _candidate_for_missing_arg(
    deps: AgentDeps | str,
    name: str,
    prop_schema: dict[str, Any],
) -> Any:
    prop_type = _schema_type(prop_schema)
    for artifact in reversed(_artifacts_from_deps(deps)):
        if name in artifact.arguments:
            value = artifact.arguments[name]
            if _candidate_matches_schema(value, prop_schema):
                return value

        if isinstance(artifact.value, dict) and name in artifact.value:
            value = artifact.value[name]
            if _candidate_matches_schema(value, prop_schema):
                return value

        if prop_type in {"array", "object"} and _candidate_matches_schema(
            artifact.value,
            prop_schema,
        ):
            return artifact.value

    return None


def _enrich_missing_args(
    deps: AgentDeps | str,
    schema: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(args)
    for name in _required_arg_names(schema):
        if name in enriched:
            continue
        prop_schema = _property_schema(schema, name)
        if _is_descriptor_property(prop_schema):
            continue
        candidate = _candidate_for_missing_arg(deps, name, prop_schema)
        if candidate is not None:
            enriched[name] = candidate
    return enriched


def _missing_required_descriptor_arg(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    for name in _required_arg_names(schema):
        if name in args:
            continue
        if _is_descriptor_property(_property_schema(schema, name)):
            return name
    return None


def _json_value_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _normalise_structured_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"result"}:
        return value["result"]
    return value


def _structured_value_from_result(result: Any, combined_text: str) -> Any:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, (dict, list, str, int, float, bool)):
        return _normalise_structured_value(structured)
    parsed = _json_value_from_text(combined_text)
    return _normalise_structured_value(parsed)


def _remember_structured_result(
    deps: AgentDeps | str,
    *,
    service: str,
    tool: str,
    arguments: dict[str, Any],
    value: Any,
) -> str | None:
    if not isinstance(deps, AgentDeps) or not isinstance(value, (dict, list)):
        return None
    return deps.remember_tool_result(
        service=service,
        tool=tool,
        arguments=arguments,
        value=value,
    )


def _schema_retry_message(
    tool_name: str,
    schema: dict[str, Any],
    args: dict[str, Any],
    exc: JsonSchemaValidationError,
) -> str:
    required = _required_arg_names(schema)
    missing = [name for name in required if name not in args]

    parts = [f"Invalid arguments for {tool_name}: {exc.message}."]
    if required:
        parts.append(f"Required args: {', '.join(required)}.")
    if missing:
        parts.append(f"Missing args: {', '.join(missing)}.")
    if not args:
        parts.append("Do not call this tool with empty arguments.")
    if "bars" in missing:
        parts.append(
            "Fetch OHLCV bars first and pass the full `bars` array from "
            "`instruments__get_ohlcv_history`; do not replace `bars` with date fields."
        )

    path = ".".join(str(part) for part in exc.absolute_path)
    if path:
        parts.append(f"Validation path: {path}.")
    return " ".join(parts)


def _classify_tool_error(
    service: str,
    tool: str,
    exc: Exception,
) -> DownstreamToolError:
    if isinstance(exc, DownstreamToolError):
        return exc

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, OSError, ConnectionError)):
        return DownstreamToolError(
            service=service,
            tool=tool,
            message="Transient downstream tool failure",
            transient=True,
            fatal=False,
            recovery_hint="Retry may succeed once the downstream service recovers.",
        )

    if isinstance(exc, (AuthorizationError, AuthTokenInvalidError, ValueError, TypeError)):
        return DownstreamToolError(
            service=service,
            tool=tool,
            message=str(exc),
            transient=False,
            fatal=False,
            recovery_hint="Check tool arguments, token, and downstream permissions.",
        )

    return DownstreamToolError(
        service=service,
        tool=tool,
        message="Fatal downstream tool failure",
        transient=False,
        fatal=True,
        recovery_hint="Inspect the downstream service and server logs.",
    )


def make_tool(
    pool: SessionPool,
    info: MCPToolInfo,
    auth_service: AuthService,
    max_chars: int = 8000,
    retry_attempts: int = 2,
) -> Tool:  # type: ignore[type-arg]
    """Build a pydantic-ai :class:`Tool` that calls *info* via *pool*.

    The tool name is ``"<service_name>__<tool_name>"`` so names stay unique
    across multiple registered services.  The *auth_service* is used to
    authorise the downstream activity before making the call.
    """
    tool_name = f"{info.service_name}__{info.name}"
    tool_description = info.description
    activity = downstream_activity(info.service_name, info.name)
    input_schema = _normalise_input_schema(info.input_schema)
    schema_validator = validator_for(input_schema)(input_schema)

    async def _call(ctx: RunContext[AgentDeps | str], **kwargs: Any) -> str:
        kwargs = _enrich_missing_args(ctx.deps, input_schema, kwargs)
        token = _token_from_deps(ctx.deps)
        attempts = max(retry_attempts, 1)

        for attempt in range(1, attempts + 1):
            started_at = perf_counter()
            try:
                require_activity(auth_service, token, activity)
                async with pool.open_user_session(token) as session:
                    result = await session.call_tool(info.name, kwargs)

                text_parts: list[str] = []
                for content in result.content:
                    if isinstance(content, TextContent):
                        text_parts.append(content.text)

                if result.content and not text_parts:
                    raise DownstreamToolError(
                        service=info.service_name,
                        tool=info.name,
                        message="Tool returned no text content",
                        transient=False,
                        fatal=False,
                        recovery_hint="Check downstream response formatting.",
                    )

                combined = "\n".join(text_parts)
                truncated = len(combined) > max_chars
                wrapped = truncate_result(combined, max_chars)
                artifact_id = _remember_structured_result(
                    ctx.deps,
                    service=info.service_name,
                    tool=info.name,
                    arguments=kwargs,
                    value=_structured_value_from_result(result, combined),
                )
                payload: dict[str, Any] = {
                    "ok": True,
                    "service": info.service_name,
                    "tool": info.name,
                    "attempt": attempt,
                    "truncated": truncated,
                    "latency_ms": int((perf_counter() - started_at) * 1000),
                    "content": wrapped,
                }
                if artifact_id is not None:
                    payload["artifact_id"] = artifact_id
                return _wrap_tool_payload(payload)
            except Exception as exc:
                error = _classify_tool_error(info.service_name, info.name, exc)
                if error.transient and attempt < attempts:
                    continue
                if error.fatal:
                    raise error from exc
                return _wrap_tool_payload(
                    {
                        "ok": False,
                        "service": info.service_name,
                        "tool": info.name,
                        "attempt": attempt,
                        "truncated": False,
                        "error": error.as_payload(),
                    }
                )

        raise DownstreamToolError(
            service=info.service_name,
            tool=info.name,
            message="Downstream tool failed after retries were exhausted",
            transient=False,
            fatal=True,
            recovery_hint="Inspect downstream service health.",
        )

    async def _validate_arguments(ctx: RunContext[AgentDeps | str], **kwargs: Any) -> None:
        enriched = _enrich_missing_args(ctx.deps, input_schema, kwargs)
        missing_descriptor_arg = _missing_required_descriptor_arg(input_schema, enriched)
        if missing_descriptor_arg is not None:
            raise ModelRetry(
                f"Tool {tool_name} requires descriptor argument {missing_descriptor_arg}; "
                "pass it directly from the previous tool's response."
            )
        try:
            schema_validator.validate(enriched)
        except JsonSchemaValidationError as exc:
            raise ModelRetry(_schema_retry_message(tool_name, input_schema, enriched, exc)) from exc
        if enriched != kwargs:
            raise SkipToolValidation(enriched)

    tool = Tool.from_schema(
        function=_call,
        name=tool_name,
        description=tool_description,
        json_schema=input_schema,
        takes_ctx=True,
        args_validator=_validate_arguments,
    )
    tool.max_retries = max(retry_attempts, 1)
    return tool

