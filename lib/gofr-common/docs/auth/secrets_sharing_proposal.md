# Secrets Sharing Across GOFR Projects

## Problem Statement

All GOFR projects (gofr-dig, gofr-doc, gofr-plot, etc.) share a single Vault
instance and a single set of auth groups/tokens. Today the canonical `secrets/`
directory lives inside `gofr-common` and each project symlinks to it:

```
gofr-dig/secrets  →  gofr-dig/lib/gofr-common/secrets/
```

This works for one project, but breaks when multiple projects are checked out
independently — each gets its own `gofr-common` submodule with its own
`secrets/` directory. Secrets drift and are duplicated.

### What lives in `secrets/` today

| File                         | Purpose                            | Sensitivity |
|------------------------------|------------------------------------|-------------|
| `vault_root_token`           | Vault root token (dev/bootstrap)   | CRITICAL    |
| `vault_unseal_key`           | Single unseal key (dev mode)       | CRITICAL    |
| `vault_init_output`          | Raw init JSON                      | CRITICAL    |
| `bootstrap_tokens.json`      | Pre-signed admin/public JWTs       | HIGH        |
| `service_creds/<svc>.json`   | AppRole role_id + secret_id per svc| HIGH        |

None of these belong in Vault itself — they are needed to *reach* Vault in the
first place (chicken-and-egg).

### Container paths

| Context            | Path                               |
|--------------------|------------------------------------|
| Dev host           | `$PROJECT_ROOT/secrets/`           |
| Dev container      | bind-mount from host               |
| Prod container     | `/run/secrets/vault_creds` (Docker Secrets or bind) |


## Evaluated Options

### Option A: Your proposal — Named Docker Volume in gofr-common, symlinked up

```
docker volume create gofr-secrets
# gofr-common populates gofr-secrets at bootstrap time
# each project's compose.yml mounts gofr-secrets:/secrets:ro
# host dev: symlink $PROJECT/secrets → lib/gofr-common/secrets (unchanged)
```

**Pros:** Familiar pattern, single volume shared across stacks.  
**Cons:**
- Named volumes are opaque — cannot `ls` or edit from host without a helper
  container. Painful for debugging.
- On host dev (outside Docker) the symlink still points into one submodule
  copy — no improvement over today's situation.
- Volume lifecycle is separate from container lifecycle; accidental `docker
  volume prune` destroys secrets silently.
- Populating the volume requires a "seed" container or init job — extra
  moving part.

**Verdict:** Workable for containers but does not fix the host-dev problem.
Adds operational complexity without removing the symlink workaround.


### Option B: Bind-mount a single host directory (recommended)

Designate one canonical host path for secrets (outside any project repo):

```
~/.gofr/secrets/        # or /opt/gofr/secrets/ on prod hosts
├── vault_root_token
├── vault_unseal_key
├── vault_init_output
├── bootstrap_tokens.json
└── service_creds/
    ├── gofr-dig.json
    ├── gofr-doc.json
    └── gofr-plot.json
```

Every project bind-mounts the same host path:

```yaml
# compose.prod.yml (every project)
services:
  mcp:
    volumes:
      - ${GOFR_SECRETS_DIR:-~/.gofr/secrets}:/run/secrets:ro
```

On dev host, each project symlinks:

```bash
ln -sfn ~/.gofr/secrets  $PROJECT_ROOT/secrets
```

Or better — `gofr_env.py` resolves the path via env var:

```python
SECRETS_DIR = Path(os.environ.get("GOFR_SECRETS_DIR", WORKSPACE_ROOT / "secrets"))
```

**Pros:**
- One directory, all projects see the same files, no duplication.
- `ls`, `cat`, `vim` work directly — no helper containers.
- Survives `docker volume prune`.
- No symlink chain needed if GOFR_SECRETS_DIR is set.
- Prod and dev use the same env var; only the default changes.

**Cons:**
- Requires a one-time setup step per dev machine (`mkdir -p ~/.gofr/secrets`
  and seed it from bootstrap).
- Host-path bind-mounts are not available on remote Docker hosts (rare for
  this project's use case).

**Verdict: This is the recommended approach.** Simple, auditable, works
identically on host and in containers.


### Option C: Docker Secrets (Swarm mode / Compose Secrets)

```yaml
secrets:
  vault_root_token:
    file: ${GOFR_SECRETS_DIR:-~/.gofr/secrets}/vault_root_token
  vault_creds:
    file: ${GOFR_SECRETS_DIR:-~/.gofr/secrets}/service_creds/${COMPOSE_PROJECT_NAME}.json

services:
  mcp:
    secrets:
      - vault_creds
```

Inside the container, the file appears at `/run/secrets/vault_creds` — which
is already the path `VaultIdentity` expects.

**Pros:**
- Docker-native; secrets are tmpfs-mounted, never written to disk in the
  container's writable layer.
- Compose v2 supports `secrets:` in non-Swarm mode.
- Each service gets only the secrets it needs (least privilege).

**Cons:**
- Secrets are individual files, not a directory tree — awkward for
  `bootstrap_tokens.json` which is consumed by `gofr_env.py` as a file path.
- Per-service creds mapping adds boilerplate to every compose file.
- Still needs a canonical host location (same as Option B) to source the
  files — this is an overlay on top of Option B, not a replacement.

**Verdict:** Good hardening layer *on top of* Option B for prod containers.
Not sufficient on its own.


### Option D: Vault Agent auto-auth + templating

Run `vault agent` as a sidecar or init container. It handles AppRole login,
token renewal, and can template secrets to files:

```hcl
auto_auth {
  method "approle" {
    config = {
      role_id_file_path   = "/run/secrets/role_id"
      secret_id_file_path = "/run/secrets/secret_id"
    }
  }
  sink "file" {
    config = { path = "/run/secrets/vault_token" }
  }
}
```

**Pros:** Eliminates static vault tokens; auto-renews. Industry best practice.  
**Cons:** Significant complexity increase. Requires a sidecar per stack.
Doesn't solve the bootstrap chicken-and-egg (you still need role_id/secret_id
on disk somewhere).

**Verdict:** Future hardening step (see AUTH_HARDENING_PLAN.md item 6), not
the right time to adopt now. The simpler options solve the sharing problem.


## Implementation Plan: Option A — Named Docker Volume `gofr-secrets`

**Decision:** Use a named Docker volume for expediency. The volume is shared
across all GOFR project stacks. On the dev host, the project `secrets/`
symlink continues to work for IDE/script access.

### Current state (what we're changing from)

| Context | How secrets get there |
|---------|----------------------|
| Dev container (`run-dev.sh`) | Bind-mount of project dir; symlink `secrets/ → lib/gofr-common/secrets/` resolves |
| Prod image (`Dockerfile.prod`) | `COPY` bakes `service_creds/gofr-dig.json` into `/run/secrets/vault_creds` |
| Compose dev/prod | No secrets volume mounts |
| `gofr_env.py` | Resolves `WORKSPACE_ROOT/secrets/` via `__file__` traversal |
| `ensure_approle.sh` | Writes to `$PROJECT_ROOT/secrets/service_creds/` |

### Target state (what we're changing to)

| Context | Volume | Mount point |
|---------|--------|-------------|
| Dev container (`run-dev.sh`) | `gofr-secrets` | `/home/gofr/devroot/gofr-dig/secrets` |
| Prod containers (`compose.prod.yml`) | `gofr-secrets` | `/run/secrets:ro` |
| Test containers (`compose.dev.yml`) | `gofr-secrets-test` | `/run/secrets:ro` |
| Test runner (`run_tests.sh`) | `gofr-secrets-test` | mounted into dev container at test time |
| Prod image (`Dockerfile.prod`) | — | No longer bakes creds — volume provides them |
| `gofr_env.py` | — | Unchanged — `WORKSPACE_ROOT/secrets/` resolves to mount |
| `ensure_approle.sh` | — | Unchanged — writes to `$PROJECT_ROOT/secrets/` (backed by volume) |

**Two volumes, strict separation:**
- `gofr-secrets` — real credentials, shared by prod and dev containers
- `gofr-secrets-test` — test-only credentials, used by test compose stack
  and `run_tests.sh`. Never touches production secrets.

---

### Step-by-step plan

#### Step 1: Create the `gofr-secrets` volume in `run-dev.sh`

Add volume creation alongside the existing `gofr-dig-data-dev` volume:

```bash
# Create shared secrets volume (shared across all GOFR projects)
SECRETS_VOLUME="gofr-secrets"
if ! docker volume inspect $SECRETS_VOLUME >/dev/null 2>&1; then
    echo "Creating volume: $SECRETS_VOLUME"
    docker volume create $SECRETS_VOLUME
fi
```

Then add the volume mount to the `docker run` command:

```bash
-v ${SECRETS_VOLUME}:/home/gofr/devroot/gofr-dig/secrets:rw \
```

This overlays the project's `secrets/` symlink with the volume contents.
Inside the container, `/home/gofr/devroot/gofr-dig/secrets/` points to the
volume — `gofr_env.py` resolves it transparently.

**File:** `docker/run-dev.sh`

#### Step 1b: Create the `gofr-secrets-test` volume in `run_tests.sh`

The test runner already starts an ephemeral Vault. Add test-secrets volume
creation alongside it:

```bash
# Create test-only secrets volume (isolated from production secrets)
SECRETS_TEST_VOLUME="gofr-secrets-test"
if ! docker volume inspect $SECRETS_TEST_VOLUME >/dev/null 2>&1; then
    echo "Creating test secrets volume: $SECRETS_TEST_VOLUME"
    docker volume create $SECRETS_TEST_VOLUME
fi
```

The volume is populated by the test Vault bootstrap (ephemeral, recreated each
test run if needed). The volume persists between runs to avoid repeated setup,
but it only ever contains test credentials.

**File:** `scripts/run_tests.sh`

#### Step 2: One-off migration — seed both volumes from existing secrets

Create a migration script `scripts/migrate_secrets_to_volume.sh` that seeds
**both** `gofr-secrets` and `gofr-secrets-test`:

```bash
#!/bin/bash
# One-off: copy existing secrets into the gofr-secrets Docker volumes.
# Seeds both gofr-secrets (prod/dev) and gofr-secrets-test (tests).
# Run once from the host (or dev container with Docker socket access).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="$PROJECT_ROOT/lib/gofr-common/secrets"

# Both volumes to seed
VOLUMES=("gofr-secrets" "gofr-secrets-test")

# Verify source exists
if [ ! -d "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/vault_root_token" ]; then
    echo "ERROR: Source secrets not found at $SOURCE_DIR"
    echo "  Expected: vault_root_token, vault_unseal_key, bootstrap_tokens.json, service_creds/"
    exit 1
fi

for VOLUME in "${VOLUMES[@]}"; do
    # Ensure volume exists
    if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
        echo "Creating volume: $VOLUME"
        docker volume create "$VOLUME"
    fi

    echo "Copying secrets from $SOURCE_DIR into volume $VOLUME ..."

    # Use a disposable Alpine container to copy files into the volume
    docker run --rm \
        -v "$SOURCE_DIR:/src:ro" \
        -v "$VOLUME:/dst" \
        alpine:3.19 sh -c '
            cp -a /src/. /dst/
            chmod 700 /dst
            chmod 600 /dst/vault_root_token /dst/vault_unseal_key 2>/dev/null || true
            chmod 600 /dst/service_creds/*.json 2>/dev/null || true
            echo "Contents of /dst:"
            ls -la /dst/
            ls -la /dst/service_creds/ 2>/dev/null || true
        '

    echo "Volume '$VOLUME' seeded successfully."
    echo ""
done

echo "Done. Both volumes seeded."
echo "Verify: docker run --rm -v gofr-secrets:/s:ro alpine ls -la /s/"
echo "Verify: docker run --rm -v gofr-secrets-test:/s:ro alpine ls -la /s/"
```

**File:** `scripts/migrate_secrets_to_volume.sh` (new)

#### Step 3: Mount `gofr-secrets-test` in `compose.dev.yml`

The dev compose file IS the test stack (`name: gofr-dig-test`). It uses the
test volume — never the production one:

```yaml
volumes:
  sessions-data:
  gofr-secrets-test:
    name: gofr-secrets-test
    external: true

services:
  mcp:
    volumes:
      - sessions-data:/home/gofr-dig/data/storage/sessions
      - gofr-secrets-test:/run/secrets:ro
  web:
    volumes:
      - sessions-data:/home/gofr-dig/data/storage/sessions
      - gofr-secrets-test:/run/secrets:ro
```

**File:** `docker/compose.dev.yml`

#### Step 4: Mount `gofr-secrets` in `compose.prod.yml`

Production stack uses the real secrets volume:

```yaml
volumes:
  gofr-dig-data:
    name: gofr-dig-data
  gofr-dig-prod-logs:
    name: gofr-dig-prod-logs
  gofr-secrets:
    name: gofr-secrets
    external: true

services:
  mcp:
    volumes:
      - gofr-dig-data:/home/gofr-dig/data
      - gofr-dig-prod-logs:/home/gofr-dig/logs
      - gofr-secrets:/run/secrets:ro
  web:
    volumes:
      - gofr-dig-data:/home/gofr-dig/data
      - gofr-dig-prod-logs:/home/gofr-dig/logs
      - gofr-secrets:/run/secrets:ro
```

**File:** `docker/compose.prod.yml`

#### Step 5: Remove baked-in secrets from `Dockerfile.prod`

Delete the three lines that copy creds into the image:

```dockerfile
# REMOVE these lines:
RUN mkdir -p /run/secrets && chown gofr-dig:gofr-dig /run/secrets
COPY --chown=gofr-dig:gofr-dig lib/gofr-common/secrets/service_creds/gofr-dig.json /run/secrets/vault_creds
RUN chmod 600 /run/secrets/vault_creds
```

Replace with just the directory creation (the volume mount will populate it):

```dockerfile
# Secrets are injected via the gofr-secrets Docker volume at runtime
RUN mkdir -p /run/secrets && chown gofr-dig:gofr-dig /run/secrets
```

**File:** `docker/Dockerfile.prod`

#### Step 6: Update `start-prod.sh` references

Change the creds-file check to look at the volume instead of the submodule path:

```bash
# Before:
VAULT_CREDS_FILE="$PROJECT_ROOT/lib/gofr-common/secrets/service_creds/gofr-dig.json"

# After: check the volume via a quick docker run
if docker run --rm -v gofr-secrets:/secrets:ro alpine test -f /secrets/service_creds/gofr-dig.json; then
    ok "Vault AppRole credentials found in gofr-secrets volume"
else
    warn "No AppRole credentials in gofr-secrets volume"
    warn "Run: ./scripts/migrate_secrets_to_volume.sh"
fi
```

Also update the vault_root_token path:

```bash
# Before:
VAULT_ROOT_TOKEN_FILE="$PROJECT_ROOT/secrets/vault_root_token"

# After: read from volume (via docker exec or keep host symlink as fallback)
# The host symlink still works for reading, so this can stay as-is for now
```

**File:** `docker/start-prod.sh`

#### Step 7: Update `ensure_approle.sh` to write into the volume

The script writes new AppRole creds. It needs to write into the volume.
Since it runs on the host (or in the dev container which has the volume
mounted at `$PROJECT_ROOT/secrets/`), the existing path works:

```bash
# This already works because:
# - On host: $PROJECT_ROOT/secrets/ is a symlink to lib/gofr-common/secrets/
#   AND run-dev.sh mounts gofr-secrets at the same path
# - In dev container: the volume IS mounted at $PROJECT_ROOT/secrets/
CREDS_FILE="$SECRETS_DIR/service_creds/gofr-dig.json"
```

No change needed if the dev container has the volume mounted and the host
symlink is kept as fallback. However, add a note:

```bash
# NOTE: In production, this writes to the gofr-secrets Docker volume
# (mounted at $PROJECT_ROOT/secrets/ in the dev container).
```

**File:** `scripts/ensure_approle.sh` (comment only)

#### Step 8: Verify and smoke test

```bash
# 1. Run migration (seeds both gofr-secrets and gofr-secrets-test)
./scripts/migrate_secrets_to_volume.sh

# 2. Verify both volumes
docker run --rm -v gofr-secrets:/s:ro alpine ls -la /s/
docker run --rm -v gofr-secrets-test:/s:ro alpine ls -la /s/

# 3. Restart dev container (uses gofr-secrets)
./docker/run-dev.sh

# 4. Inside dev container, verify secrets are visible
docker exec gofr-dig-dev ls -la /home/gofr/devroot/gofr-dig/secrets/
docker exec gofr-dig-dev cat /home/gofr/devroot/gofr-dig/secrets/vault_root_token

# 5. Rebuild prod image (without baked-in creds)
./docker/start-prod.sh --build

# 6. Run tests (uses gofr-secrets-test, never gofr-secrets)
./scripts/run_tests.sh
```

---

### File change summary

| File | Action |
|------|--------|
| `docker/run-dev.sh` | Add `gofr-secrets` volume create + mount |
| `scripts/run_tests.sh` | Add `gofr-secrets-test` volume create |
| `scripts/migrate_secrets_to_volume.sh` | **New** — one-off migration script (seeds both volumes) |
| `docker/compose.dev.yml` | Add `gofr-secrets-test` external volume + mount on mcp, web |
| `docker/compose.prod.yml` | Add `gofr-secrets` external volume + mount on mcp, web |
| `docker/Dockerfile.prod` | Remove COPY of service_creds; keep mkdir /run/secrets |
| `docker/start-prod.sh` | Update creds-file check to use volume |
| `scripts/ensure_approle.sh` | Add comment (path already works via mount) |

### What stays the same

- `gofr_env.py` — unchanged, `WORKSPACE_ROOT/secrets/` resolves to the volume mount
- `VaultIdentity` — unchanged, reads `/run/secrets/vault_creds`
- `lib/gofr-common/secrets/` — kept as the original source; the migration copies FROM it
- `$PROJECT_ROOT/secrets` symlink — kept on host for backward compat; inside the container the volume overlays it

### Volume separation: `gofr-secrets` vs `gofr-secrets-test`

| Volume | Used by | Contains |
|--------|---------|----------|
| `gofr-secrets` | `run-dev.sh`, `compose.prod.yml` | Real creds — vault root token, unseal key, AppRole creds, bootstrap JWTs |
| `gofr-secrets-test` | `compose.dev.yml`, `run_tests.sh` | Test-only creds — from ephemeral test Vault, disposable |

Tests **never** mount or read from `gofr-secrets`. This prevents:
- Accidental mutation of production AppRole creds during test runs
- Test teardown or cleanup scripts touching real secrets
- CI/CD jobs that run tests from leaking production tokens

The migration script (Step 2) seeds **both** volumes — `gofr-secrets` with
real creds and `gofr-secrets-test` with a copy suitable for local testing.

### Multi-project sharing

When gofr-doc, gofr-plot, etc. are added, they simply:

1. Mount `gofr-secrets` in their `compose.prod.yml` (and `gofr-secrets-test` in
   their `compose.dev.yml`)
2. Add their own `service_creds/<project>.json` via `ensure_approle.sh`
3. All projects see the same `bootstrap_tokens.json`, `vault_root_token`, etc.

Both volumes are **external** (`external: true`) so they persist independently
of any single project's lifecycle. `docker compose down -v` on one project
does NOT destroy them.


## File-level changes

See "Step-by-step plan" above for the complete list.


## Security notes

- The `gofr-secrets` volume is `external: true` — it survives `docker compose
  down -v` and must be explicitly removed with `docker volume rm gofr-secrets`.
- Individual files inside the volume should be `chmod 600` (set by migration script).
- `.gitignore` rules in gofr-common already cover `**/secrets/` — the canonical
  source (`lib/gofr-common/secrets/`) is never committed.
- `vault_root_token` and `vault_unseal_key` are dev/bootstrap-only.
  Production Vault should use auto-unseal (cloud KMS) and the root token
  should be revoked after initial setup.
- AppRole `secret_id` has a limited TTL in production. `VaultIdentity`
  already handles renewal.
- **Volume security:** Named Docker volumes are stored at
  `/var/lib/docker/volumes/gofr-secrets/_data/` which is root-owned.
  Non-root users cannot access it directly on the host, which is appropriate.
- **K8s migration note:** When moving to K8s, replace the named Docker volume
  with K8s Secrets (simplest) or Vault CSI Provider (most secure). See the
  platform injection matrix in the evaluated options above.


## Migration path

1. Create `~/.gofr/secrets/` on dev machines.
2. Copy existing `lib/gofr-common/secrets/*` into it.
3. Set `GOFR_SECRETS_DIR=~/.gofr/secrets` in shell profile.
4. Existing symlinks continue to work as fallback.
5. Remove project-level `secrets/` symlinks once all projects adopt the env var.
