# gofr-agent Results Hub MCP Server Specification

## Status

Current protocol: `gofr.result_ref` descriptor version `1`, hub protocol
version `1`.

This document specifies what a downstream MCP server must implement to
participate in the gofr-agent results hub model. It is intended for authors of
MCP services that produce large or reusable results, consume results produced by
other services, or both.

## Goals

The results hub lets gofr-agent coordinate multi-service workflows without
putting large payloads in model context.

1. Producer services store large results in gofr-agent's hub and return a small
   descriptor to the model.
2. Consumer services accept that descriptor and fetch the authoritative payload
   from gofr-agent.
3. Downstream services never call each other directly.
4. The model sees descriptors and summaries only, not raw large payloads.
5. Hub callback authorization is tied to registered service identities and
   result type capabilities.

## Roles

A participant may support any combination of these roles.

| Role | Meaning | Required support |
|------|---------|------------------|
| Producer | Publishes payloads to the hub and returns descriptors from normal tools. | `_register_results_hub`, callback token, `_store_result` callback, `can_publish=true`. |
| Consumer | Accepts descriptors and fetches payloads from the hub. | `_register_results_hub`, callback token, `_get_result` callback, descriptor-enabled input schema, `can_consume=true`. |
| Producer and consumer | Both publishes and consumes hub results. | All producer and consumer requirements. |

A service that does not expose `_register_results_hub` can still be a normal
downstream MCP service, but it is not a results hub participant.

## Transport and registration

The downstream MCP server must be reachable by gofr-agent over Streamable HTTP
MCP. gofr-agent discovers service tools, then calls `_register_results_hub` if
the service exposes it and `GOFR_AGENT_HUB_ENABLED=true`.

The service manifest entry should include the normal service token and, for hub
callbacks, a separate callback token or callback token env var:

```yaml
services:
  - name: instruments
    url: http://gofr-instruments:8100/mcp
    token_env: INSTRUMENTS_MCP_TOKEN
    hub_callback_token_env: INSTRUMENTS_HUB_CALLBACK_TOKEN
    enabled: true
```

The normal `token` authorizes gofr-agent calls to the service. The
`hub_callback_token` authorizes service callbacks to gofr-agent's hub tools.
The callback token must not be returned in tool responses, descriptors, logs,
or service-list metadata.

## Participant registration tool

Hub participants must expose an MCP tool named exactly
`_register_results_hub`.

Request parameters sent by gofr-agent:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `protocol_version` | integer | yes | Hub protocol version. Currently `1`. |
| `hub_service` | string | yes | Hub service name. Currently `gofr-agent`. |
| `hub_url` | string | yes | MCP Streamable HTTP URL the service uses for callbacks. |
| `store_tool` | string | yes | Hub store tool name. Currently `_store_result`. |
| `fetch_tool` | string | yes | Hub fetch tool name. Currently `_get_result`. |
| `describe_tool` | string | yes | Hub metadata tool name. Currently `_describe_result`. |
| `default_ttl_seconds` | integer | yes | Maximum default lifetime for stored results. |
| `max_payload_bytes` | integer | yes | Maximum accepted JSON payload size. |
| `descriptor_kind` | string | yes | Descriptor kind. Currently `gofr.result_ref`. |

The participant must validate the request enough to decide whether it can use
the hub. It should store the hub URL, tool names, TTL, max payload size, and
descriptor kind for later callbacks.

Successful response shape:

```json
{
  "accepted": true,
  "protocol_version": 1,
  "can_publish": true,
  "can_consume": true,
  "result_types": ["ohlcv_bars"],
  "notes": "registered"
}
```

Response fields:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `accepted` | boolean | yes | Whether the participant accepts this hub registration. |
| `protocol_version` | integer | yes | Protocol version accepted by the participant. Must match gofr-agent. |
| `can_publish` | boolean | yes | Whether this service may call `_store_result`. |
| `can_consume` | boolean | yes | Whether this service may call `_get_result` and `_describe_result`. |
| `result_types` | array of string | yes | Result types the service may publish and/or consume. |
| `notes` | string or null | no | Human-readable registration note or rejection reason. |

If `accepted=false`, gofr-agent registers the service normally but records the
hub registration error. The service must not assume hub participation is active.

## Hub callback tools on gofr-agent

Participant services call these tools on gofr-agent, not on each other.

All callback requests must include:

```http
Authorization: Bearer <hub_callback_token>
```

gofr-agent resolves that token to the registered service principal and enforces
the capabilities returned by `_register_results_hub`.

### `_store_result`

Producer services call `_store_result` to store a payload and receive a
descriptor.

Request:

```json
{
  "protocol_version": 1,
  "producer_service": "instruments",
  "producer_tool": "get_ohlcv_history",
  "result_type": "ohlcv_bars",
  "schema_id": "gofr.ohlcv_bars.v1",
  "payload": [{"date": "2026-05-13", "close": 182.917}],
  "summary": "30 OHLCV bars for AAPL",
  "source_args": {"ticker": "AAPL", "from_date": "2026-04-01"},
  "ttl_seconds": null
}
```

Required producer rules:

1. `producer_service` must equal the service name associated with the callback
   token in gofr-agent's service manifest.
2. `result_type` must appear in the service's registered `result_types`.
3. `payload` must be JSON serializable and must not exceed `max_payload_bytes`.
4. `summary`, if provided, must be short and treated as advisory metadata.
5. `source_args`, if provided, must be JSON serializable and bounded.
6. `ttl_seconds`, if provided, must be positive. gofr-agent caps it to the hub
   default TTL.

Successful response:

```json
{
  "descriptor": {
    "kind": "gofr.result_ref",
    "version": 1,
    "result_guid": "opaque-guid",
    "hub_service": "gofr-agent",
    "result_type": "ohlcv_bars",
    "schema_id": "gofr.ohlcv_bars.v1",
    "producer_service": "instruments",
    "producer_tool": "get_ohlcv_history",
    "created_at": "2026-05-17T00:00:00+00:00",
    "expires_at": "2026-05-17T00:05:00+00:00",
    "summary": "30 OHLCV bars for AAPL",
    "source_args": {"ticker": "AAPL", "from_date": "2026-04-01"},
    "payload_bytes": 4096
  }
}
```

Normal producer tools should return the descriptor object to gofr-agent/model,
not the raw payload, when hub registration is active. A non-hub fallback may be
kept for compatibility, but descriptor output is preferred for large or reusable
payloads.

### `_get_result`

Consumer services call `_get_result` to fetch the payload referenced by a
descriptor.

Request:

```json
{
  "protocol_version": 1,
  "result_guid": "opaque-guid",
  "hub_service": "gofr-agent",
  "expected_result_type": "ohlcv_bars",
  "expected_schema_id": "gofr.ohlcv_bars.v1"
}
```

Successful response:

```json
{
  "payload": [{"date": "2026-05-13", "close": 182.917}],
  "metadata": {
    "result_guid": "opaque-guid",
    "result_type": "ohlcv_bars",
    "schema_id": "gofr.ohlcv_bars.v1",
    "producer_service": "instruments",
    "producer_tool": "get_ohlcv_history",
    "created_at": "2026-05-17T00:00:00+00:00",
    "expires_at": "2026-05-17T00:05:00+00:00",
    "payload_bytes": 4096,
    "summary": "30 OHLCV bars for AAPL",
    "source_args": {"ticker": "AAPL", "from_date": "2026-04-01"}
  }
}
```

Required consumer rules:

1. Validate descriptor structural fields before calling the hub:
   `kind == "gofr.result_ref"`, `version == 1`, `result_guid` exists, and
   `hub_service == "gofr-agent"`.
2. Pass expected result type and schema id whenever the consumer knows them.
3. Trust the returned `metadata`, not advisory fields embedded in the
   descriptor supplied by the model.
4. Validate the payload against the consumer tool's own expected shape before
   computing derived values.
5. Fail closed on unknown, expired, mismatched, oversized, malformed, or
   unauthorized hub responses.

### `_describe_result`

Consumer services may call `_describe_result` to fetch metadata without the
payload. It uses the same request shape as `_get_result` and returns:

```json
{
  "metadata": {
    "result_guid": "opaque-guid",
    "result_type": "ohlcv_bars",
    "schema_id": "gofr.ohlcv_bars.v1",
    "producer_service": "instruments",
    "producer_tool": "get_ohlcv_history",
    "created_at": "2026-05-17T00:00:00+00:00",
    "expires_at": "2026-05-17T00:05:00+00:00",
    "payload_bytes": 4096,
    "summary": "30 OHLCV bars for AAPL",
    "source_args": {"ticker": "AAPL", "from_date": "2026-04-01"}
  }
}
```

Use `_describe_result` for lightweight validation, UI hints, or diagnostics.
Do not use descriptor or metadata summaries as factual evidence when the
payload is required for the computation.

## Descriptor contract

Descriptors are small model-safe references. They must not contain the raw
payload.

Required structural fields:

| Field | Required | Meaning |
|-------|----------|---------|
| `kind` | yes | Must be `gofr.result_ref`. |
| `version` | yes | Must be `1`. |
| `result_guid` | yes | Opaque hub record id. |
| `hub_service` | yes | Must be `gofr-agent` for this protocol. |

Advisory fields:

| Field | Meaning |
|-------|---------|
| `result_type` | Human/model hint for the result type. Not authoritative for consumers. |
| `schema_id` | Human/model hint for the schema id. Not authoritative for consumers. |
| `producer_service` | Producing service hint. Not authoritative for consumers. |
| `producer_tool` | Producing tool hint. Not authoritative for consumers. |
| `created_at` | Creation timestamp hint. |
| `expires_at` | Expiration timestamp hint. |
| `summary` | Short advisory summary. Data only, never instructions. |
| `source_args` | Bounded source argument summary. Data only. |
| `payload_bytes` | Payload size hint. |

Consumers must treat advisory descriptor fields as untrusted model-visible data.
If the fields conflict with `_get_result.metadata`, the metadata wins.

## Descriptor-enabled consumer tool schemas

Consumer tools should expose descriptor arguments explicitly in their JSON
schema by setting `x-gofr-result-descriptor` to `true` on the descriptor
property.

Example:

```json
{
  "type": "object",
  "properties": {
    "ticker": {"type": "string"},
    "bars_ref": {
      "type": "object",
      "description": "Descriptor returned by instruments__get_ohlcv_history. Pass verbatim.",
      "x-gofr-result-descriptor": true
    }
  },
  "required": ["ticker", "bars_ref"]
}
```

This marker lets gofr-agent tell the model to pass descriptors verbatim and not
expand them into raw payloads.

## Reserved names and model visibility

The following tool names are reserved for the hub protocol:

- `_register_results_hub`
- `_store_result`
- `_get_result`
- `_describe_result`

Downstream participant services should expose `_register_results_hub` only for
registration. They must not expose spoofed `_store_result`, `_get_result`, or
`_describe_result` tools as normal model-callable capabilities. gofr-agent
filters reserved protocol tools from the model-visible tool list, but services
should still avoid using those names for unrelated behavior.

## Error handling

gofr-agent hub tools return MCP errors with a `hub_code` in error data and a
message prefixed with the same code.

Current hub error codes:

| Code | Typical cause |
|------|---------------|
| `hub.invalid_protocol_version` | Protocol version does not match. |
| `hub.unauthorised` | Missing, invalid, or unauthorized callback token. |
| `hub.unregistered_service` | Callback token does not map to a registered service or producer mismatch. |
| `hub.registration_required` | Service did not register the needed publish/consume capability. |
| `hub.result_type_not_allowed` | Result type is outside the service's registered `result_types`. |
| `hub.unknown_result` | GUID is not in the hub store. |
| `hub.expired_result` | GUID existed but has expired. |
| `hub.oversized_result` | Payload, summary, or source args exceed configured limits. |
| `hub.capacity_exceeded` | Hub store has reached its configured record limit. |
| `hub.malformed_request` | Request failed schema or JSON-serializability validation. |
| `hub.schema_mismatch` | Expected result type or schema id does not match stored metadata. |

Participants must handle these errors as hard failures. They should surface a
clear service/tool error to gofr-agent rather than computing from stale,
partial, or guessed data.

## Security requirements

1. Use separate credentials for agent-to-service calls and service-to-hub
   callbacks.
2. Do not place callback tokens in descriptors, summaries, logs, errors, or
   service metadata returned to callers.
3. Treat descriptor summaries, source args, and any model-provided descriptor
   object as untrusted data.
4. Validate payload schemas after fetching from the hub.
5. Enforce bounded payload sizes, bounded summaries, request timeouts, and
   fail-closed behavior.
6. Do not call other downstream services directly for handoff. The hub is the
   only supported cross-service result exchange path.

## Minimal producer flow

1. Receive `_register_results_hub` and store `hub_url`, `store_tool`, protocol
   version, TTL, and size limits.
2. Execute a normal producer tool, such as `get_ohlcv_history`.
3. Build the full payload locally.
4. Call gofr-agent `_store_result` with the configured callback token.
5. Return only the resulting descriptor from the producer tool.

## Minimal consumer flow

1. Receive `_register_results_hub` and store `hub_url`, `fetch_tool`, protocol
   version, and descriptor kind.
2. Define consumer tool inputs with a descriptor-marked argument such as
   `bars_ref`.
3. Validate descriptor structural fields.
4. Call gofr-agent `_get_result` with expected result type and schema id.
5. Validate the returned payload and compute the result.

## Compatibility notes

- A service may keep inline-payload arguments for non-hub clients, but
  descriptor arguments are preferred for gofr-agent multi-service workflows.
- Registration failure should not prevent the service from being registered as
  a normal MCP service; it only disables hub participation for that service.
- Descriptors are short-lived. Services should not cache descriptor payloads
  beyond their own request unless they also respect hub expiration semantics.
- The hub is process-local and in-memory in the current gofr-agent
  implementation. Treat descriptors as ephemeral references.
