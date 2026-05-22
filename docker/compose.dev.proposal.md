# Proposal: Single `docker/compose.dev.yml` for gofr-agent + Valkey + fixtures

Date: 2026-05-22

## Goal

Replace the current split local runtime shape with one Compose-managed dev stack:

- `gofr-agent-dev`
- `gofr-agent-valkey`
- `gofr-agent-mcp-instruments`
- `gofr-agent-mcp-clients`
- `gofr-agent-mcp-trades`
- `gofr-agent-mcp-analytics`

All services should run on a single bridge network named `gofr-dev-net`.

The intended operator workflow becomes:

```bash
docker compose -f docker/compose.dev.yml --profile runtime up -d --build
docker compose -f docker/compose.dev.yml logs -f gofr-agent-runtime
docker compose -f docker/compose.dev.yml --profile workspace up -d --build
docker compose -f docker/compose.dev.yml down
```

## Current state

### 1. `docker/compose.dev.yml` is stale

The current file is a `gofr-doc` test stack, not a `gofr-agent` stack. It should
not be extended for agent runtime as-is.

### 2. Valkey is isolated in `docker/compose.agent-dev.yml`

This file is useful as a proof-of-concept, but it only starts Valkey and relies
on an external `gofr-net` network. It does not define the agent or fixtures.

### 3. Fixtures are Swarm-only today

`docker/compose.fixtures.yml` and `docker/fixtures-stack.sh` assume:

- Docker Swarm mode
- an attachable overlay network
- a post-deploy `docker network connect` step to bridge the dev container into
  the overlay

That is too much machinery for the local dev use case this repo actually wants.

### 4. Agent startup is still manual

Today the agent is typically started with `scripts/start-real-server.sh` after a
container or dev shell is already running. The unified Compose stack should own
that startup directly.

## Proposal

## Resolved decisions

1. Agent mode should be selectable.
  The single `compose.dev.yml` should support either a dedicated runtime
  container or an interactive workspace container, chosen explicitly via
  Compose profiles.
2. Fixture services do not need host port publishing.
  Internal-only DNS reachability on `gofr-dev-net` is sufficient as long as
  `gofr-agent` can reach them.
3. Legacy Swarm assets should be retired.
  After the unified Compose stack is in place and validated, remove
  `docker/compose.fixtures.yml`, `docker/fixtures-stack.sh`, and
  `docker/compose.agent-dev.yml`.

## Scope

The new `docker/compose.dev.yml` should be a local dev/runtime stack only.

Out of scope for this file:

- Swarm deployment
- Vault bootstrap
- MCPO or future web UI containers
- durable cache persistence

## Network model

Define a single Compose bridge network:

```yaml
networks:
  gofr-dev-net:
    name: gofr-dev-net
    driver: bridge
```

All services join this network. Container-to-container traffic always uses
service names, never `localhost` or `127.0.0.1`.

Examples:

- agent hub URL: `http://gofr-agent-dev:8090/mcp`
- cache URL: `redis://gofr-agent-valkey:6379/0`
- fixtures:
  - `http://gofr-agent-mcp-instruments:8500/mcp`
  - `http://gofr-agent-mcp-clients:8501/mcp`
  - `http://gofr-agent-mcp-trades:8502/mcp`
  - `http://gofr-agent-mcp-analytics:8503/mcp`

## Service layout

### `gofr-agent`

Use the existing dev image path from `docker/Dockerfile.dev`.

Implementation note: in the current VS Code dev-container plus Docker-socket
workflow, the Docker daemon does not see `/home/gofr/devroot/gofr-agent` as the
real workspace path. The Compose-managed agent services therefore need a
self-contained image with the repo copied in, not a repo bind mount.

Recommended shape:

- build from `docker/Dockerfile.dev` or consume `gofr-agent-dev:latest`
- copy the repo into the image and rebuild after source changes
- mount a named `data` volume
- optionally mount `/var/run/docker.sock` only if the interactive dev workflow
  still needs Docker CLI access inside the container
- publish `8090:8090`

The unified file should support two mutually exclusive Compose profiles:

#### Profile `runtime`

This is the default runtime shape for local integration and smoke checks.

- service name: `gofr-agent-runtime`
- network alias: `gofr-agent-dev`
- starts `scripts/start-real-server.sh` automatically
- owns the published `8090:8090` binding

Startup command:

```bash
./scripts/start-real-server.sh \
  --services-file /home/gofr/devroot/gofr-agent/docker/services.compose.dev.yml \
  --hub-store-backend external_cache \
  --hub-cache-url redis://gofr-agent-valkey:6379/0 \
  --hub-url http://gofr-agent-dev:8090/mcp
```

#### Profile `workspace`

This is the interactive container option when a developer wants a long-running
shell/workspace container on `gofr-dev-net` and plans to start the agent
manually.

- service name: `gofr-agent-workspace`
- network alias: `gofr-agent-dev`
- starts with a passive command such as `tail -f /dev/null`
- can expose `8090:8090` when this profile is used instead of `runtime`

Only one of `runtime` or `workspace` should be active at a time, because both
want to represent the same logical agent host on the network.

Recommended default env for the Compose service:

- `GOFR_AGENT_LLM_MODEL=test`
  Reason: compose should be able to boot without a real API key.
- `OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}`
  Reason: developers can override to use a real model.
- `GOFR_AGENT_HUB_STORE_BACKEND=external_cache`
- `GOFR_AGENT_HUB_CACHE_URL=redis://gofr-agent-valkey:6379/0`
- `GOFR_AGENT_HUB_URL=http://gofr-agent-dev:8090/mcp`

Notes:

- The repo's active runtime port is `8090`. The older `8040/8041/8042` exposure
  in `Dockerfile.dev` looks inherited/stale and should not drive the new stack.
- `depends_on` should wait for Valkey health and fixture health so startup does
  not race downstream registration.
- The two agent-mode services should share the same image/mount/env base via a
  Compose anchor to avoid duplication.

### `valkey`

Reuse the existing Valkey settings, but move them into the unified compose file
and place the service on `gofr-dev-net`.

Recommended command:

```yaml
command:
  - valkey-server
  - --save
  - ""
  - --appendonly
  - "no"
  - --maxmemory
  - 256mb
  - --maxmemory-policy
  - noeviction
```

Healthcheck remains `valkey-cli ping`.

Publishing port `6379` is optional. It is not needed for the agent itself.

### Fixture services

Move the four fixtures out of Swarm mode and into the same Compose file.

For each fixture service:

- reuse `docker/Dockerfile.fixtures` image
- keep the existing service-specific `--service` and `--port` command args
- keep the local healthcheck
- place each service on `gofr-dev-net`
- remove Swarm-only `deploy:` sections
- remove overlay-network assumptions

Recommended service names:

- `mcp-instruments`
- `mcp-clients`
- `mcp-trades`
- `mcp-analytics`

Recommended hostnames:

- `gofr-agent-mcp-instruments`
- `gofr-agent-mcp-clients`
- `gofr-agent-mcp-trades`
- `gofr-agent-mcp-analytics`

Do not publish fixture host ports in the recommended local stack. The fixtures
should be internal-only services on `gofr-dev-net`.

### Services manifest

Instead of relying on `tmp/fixture-services.yml`, add a checked-in manifest for
the Compose stack, for example:

- `docker/services.compose.dev.yml`

This manifest should point at the fixture hostnames on `gofr-dev-net` and keep
the runtime deterministic.

## Proposed `docker/compose.dev.yml` structure

At a high level:

```yaml
services:
  gofr-agent-runtime:
    profiles: ["runtime"]
    build:
      context: ..
      dockerfile: docker/Dockerfile.dev
    container_name: gofr-agent-runtime
    hostname: gofr-agent-runtime
    networks:
      gofr-dev-net:
        aliases: [gofr-agent-dev]
    command: ["./scripts/start-real-server.sh", "--services-file", "/home/gofr/devroot/gofr-agent/docker/services.compose.dev.yml", "--hub-store-backend", "external_cache", "--hub-cache-url", "redis://gofr-agent-valkey:6379/0", "--hub-url", "http://gofr-agent-dev:8090/mcp"]
    depends_on:
      valkey:
        condition: service_healthy
      mcp-instruments:
        condition: service_healthy
      mcp-clients:
        condition: service_healthy
      mcp-trades:
        condition: service_healthy
      mcp-analytics:
        condition: service_healthy
    ports:
      - "8090:8090"

  gofr-agent-workspace:
    profiles: ["workspace"]
    build:
      context: ..
      dockerfile: docker/Dockerfile.dev
    container_name: gofr-agent-workspace
    hostname: gofr-agent-workspace
    command: ["tail", "-f", "/dev/null"]
    networks:
      gofr-dev-net:
        aliases: [gofr-agent-dev]
    ports:
      - "8090:8090"

  valkey:
    image: valkey/valkey:8-alpine
    container_name: gofr-agent-valkey
    hostname: gofr-agent-valkey
    networks: [gofr-dev-net]

  mcp-instruments:
    image: gofr-agent-mcp-fixtures:latest
    hostname: gofr-agent-mcp-instruments
    command: ["--service", "instruments", "--port", "8500"]
    networks: [gofr-dev-net]

  mcp-clients:
    image: gofr-agent-mcp-fixtures:latest
    hostname: gofr-agent-mcp-clients
    command: ["--service", "clients", "--port", "8501"]
    networks: [gofr-dev-net]

  mcp-trades:
    image: gofr-agent-mcp-fixtures:latest
    hostname: gofr-agent-mcp-trades
    command: ["--service", "trades", "--port", "8502"]
    networks: [gofr-dev-net]

  mcp-analytics:
    image: gofr-agent-mcp-fixtures:latest
    hostname: gofr-agent-mcp-analytics
    command: ["--service", "analytics", "--port", "8503"]
    networks: [gofr-dev-net]

networks:
  gofr-dev-net:
    name: gofr-dev-net
    driver: bridge
```

## Legacy cleanup

In the unified shape, there should be no need to:

- initialise Swarm
- deploy a stack
- connect the dev container to an overlay after startup

The migration should remove these files entirely once the new stack is proven:

- `docker/compose.fixtures.yml`
- `docker/fixtures-stack.sh`
- `docker/compose.agent-dev.yml`

`docker/compose.dev.yml` should be replaced in place with the new agent stack,
not preserved as a parallel stale file.

## Migration plan

1. Archive or replace the stale `docker/compose.dev.yml`.
2. Fold `docker/compose.agent-dev.yml` Valkey settings into the new file.
3. Port the four fixtures from `docker/compose.fixtures.yml` into normal
   Compose services.
4. Add `docker/services.compose.dev.yml` for deterministic agent startup.
5. Add Compose profiles so the operator can choose `runtime` or `workspace`
  agent mode explicitly.
6. Point the runtime agent container command at `scripts/start-real-server.sh`.
7. Remove `compose.agent-dev.yml`, `compose.fixtures.yml`, and
  `fixtures-stack.sh`.

## Acceptance criteria

The unified stack is acceptable when all of the following work:

```bash
docker compose -f docker/compose.dev.yml --profile runtime up -d --build
docker compose -f docker/compose.dev.yml exec gofr-agent-runtime \
  curl -s http://gofr-agent-dev:8090/health
```

Expected health properties:

- `status: healthy`
- `hub_store.backend: external_cache`
- `hub_store.reachable: true`
- `downstream.total: 4`
- `downstream.healthy: 4`

And a live MCP check should show:

- 4 registered services
- hub-capable services: `instruments`, `analytics`