# Compose Dev Connectivity

This note describes the current local test/runtime environment defined by `docker/compose.dev.yml`, how containers reach each other on Docker networking, and how browser or other non-Docker clients should connect to `gofr-agent`.

## What starts the test environment

The normal entrypoint is:

```bash
./scripts/compose-dev-stack.sh start <OPENROUTER_API_KEY>
```

That wrapper:

- ensures the shared Docker network `gofr-net` exists
- runs `docker compose -f docker/compose.dev.yml --profile runtime up -d --build --force-recreate`
- starts `gofr-agent-runtime`, `valkey`, and the four fixture MCP services
- waits for `gofr-agent-runtime` to become healthy
- uses `docker/services.compose.dev.yml` as the runtime services manifest

The runtime container starts `gofr-agent` via:

```bash
./scripts/start-real-server.sh \
  --services-file /home/gofr/devroot/gofr-agent/docker/services.compose.dev.yml \
  --hub-store-backend external_cache \
  --hub-cache-url redis://gofr-agent-valkey:6379/0 \
  --hub-url http://gofr-agent-dev:8090/mcp
```

`start-real-server.sh` binds the server to `0.0.0.0:8090` inside the container and enables dev auth by default.

## Docker network used

The Compose stack uses one shared external bridge network:

- network name: `gofr-net`

All runtime services join `gofr-net`.

Important consequence:

- container names and service aliases such as `gofr-agent-dev`, `gofr-agent-runtime`, `gofr-agent-valkey`, and `gofr-agent-mcp-instruments` are only resolvable from other containers on `gofr-net`
- they are not stable or meaningful from a browser on the host
- raw container IPs are not stable and should not be used in UI or proxy config

## How the containerised services see each other

Inside `gofr-net`, the stack is expected to use Docker DNS service names only.

Current internal paths are:

- `gofr-agent` public MCP URL advertised to other containers: `http://gofr-agent-dev:8090/mcp`
- Valkey cache: `redis://gofr-agent-valkey:6379/0`
- Instruments fixture: `http://gofr-agent-mcp-instruments:8500/mcp`
- Clients fixture: `http://gofr-agent-mcp-clients:8501/mcp`
- Trades fixture: `http://gofr-agent-mcp-trades:8502/mcp`
- Analytics fixture: `http://gofr-agent-mcp-analytics:8503/mcp`

This is why the checked-in services manifest uses those hostnames: every service in the Compose stack is expected to resolve peers through Docker DNS on `gofr-net`.

## How external clients should connect

`gofr-agent` publishes container port `8090` to host port `8090`, so host-side clients should use the host-facing endpoint, not container names.

Use these rules:

### Browser on the same machine

- browser UI origin: typically `http://localhost:3000`
- `gofr-agent` health probe: `http://localhost:8090/ping` or `http://localhost:8090/health`
- `gofr-agent` MCP endpoint: `http://localhost:8090/mcp`

### UI dev server running on the host

If the Vite or other dev server runs directly on the host, its proxy target should be:

- `http://localhost:8090`

It should not target:

- `gofr-agent-dev`
- fixture container names such as `gofr-agent-mcp-instruments`
- ephemeral container IPs such as `172.x.x.x`

### UI or other client running in another Docker container

If the client is also containerised, the cleanest setup is to attach that container to `gofr-net` and target:

- `http://gofr-agent-dev:8090`

If a containerised client is not attached to `gofr-net`, it must use a host-published route instead. In that case, do not rely on container IPs; explicitly route through the Docker host and allow that host/origin in `gofr-agent` config.

### External service outside Docker

If a non-Docker process on the same machine needs the agent, use:

- `http://localhost:8090`

If a process on a different machine needs the agent, use the Docker host's reachable hostname or IP plus port `8090`, and add that host/origin to the inbound allowlists described below.

## Public endpoints and auth expectations

The runtime app exposes:

- `GET /ping`
- `GET /health`
- MCP on `/mcp`

In the current dev stack:

- `/ping` and `/health` are the public liveness/diagnostic probes
- `/mcp` is the MCP transport endpoint
- the runtime launcher sets `GOFR_AGENT_AUTH_MODE=dev`
- the accepted dev bearer token is `dev-admin-token`

For local UI MCP requests, send:

```http
Authorization: Bearer dev-admin-token
```

## CORS and transport security

There are two separate controls on inbound browser-facing traffic.

### 1. MCP transport-security allowlists

FastMCP transport security checks the incoming `Host` and `Origin` headers.

In the current Compose runtime, defaults are:

- `GOFR_AGENT_MCP_ALLOWED_HOSTS`
  - `gofr-agent-dev`
  - `gofr-agent-dev:8090`
  - `gofr-agent`
  - `gofr-agent:8090`
  - `gofr-agent-runtime`
  - `gofr-agent-runtime:8090`
  - `gofr-agent-workspace`
  - `gofr-agent-workspace:8090`
  - `gofr-agent-manual`
  - `gofr-agent-manual:8090`
  - `127.0.0.1`
  - `127.0.0.1:*`
  - `localhost`
  - `localhost:*`
  - `[::1]`
  - `[::1]:*`

- `GOFR_AGENT_MCP_ALLOWED_ORIGINS`
  - `http://localhost:3000`
  - `http://127.0.0.1:3000`
  - `http://gofr-console-dev:3000`

If the caller uses a different host header or different browser origin, that value must be added explicitly.

Examples:

- browser UI on `http://localhost:5173`: add `http://localhost:5173` to `GOFR_AGENT_MCP_ALLOWED_ORIGINS` and `GOFR_AGENT_CORS_ORIGINS`
- external caller hitting `http://192.168.1.20:8090`: add `192.168.1.20:8090` or a suitable wildcard pattern to `GOFR_AGENT_MCP_ALLOWED_HOSTS`
- containerised client hitting a different advertised hostname: add that hostname to `GOFR_AGENT_MCP_ALLOWED_HOSTS`

### 2. HTTP CORS middleware

The app also applies explicit CORS middleware when `GOFR_AGENT_CORS_ORIGINS` is set.

Current defaults are:

- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://gofr-console-dev:3000`

Allowed request headers include the MCP headers plus `Authorization` and `Content-Type`.

Practical rule:

- if a browser frontend talks directly to `gofr-agent`, its origin must be present in both `GOFR_AGENT_MCP_ALLOWED_ORIGINS` and `GOFR_AGENT_CORS_ORIGINS`

## Expected browser-facing model

The intended dev flow is:

1. Start the Compose runtime stack.
2. Keep container-to-container traffic on `gofr-net` using Docker service names.
3. Expose only `gofr-agent` to the host on port `8090`.
4. Let the browser or host-side UI connect to `http://localhost:8090`.
5. If a containerised UI wants direct network access, attach it to `gofr-net` and use `http://gofr-agent-dev:8090`.

## Common misconfigurations

These are expected to fail:

- browser or host-side Vite proxy targets `gofr-agent-dev` or any other Docker-only hostname
- browser or host-side Vite proxy targets fixture hostnames such as `gofr-agent-mcp-instruments`
- UI config points at a stale container IP such as `172.23.0.3`
- browser origin is not present in both the MCP origin allowlist and the CORS allowlist
- external clients hit the agent with a host header that is not present in `GOFR_AGENT_MCP_ALLOWED_HOSTS`

The safe defaults are:

- inside `gofr-net`: use Docker service names
- outside Docker on the same machine: use `localhost:8090`
- across machines: use a real host name or host IP and explicitly allow it