# JWT Secret Bootstrap and Admin AppRole Recommendations

## Scope
Security review and recommendations for JWT secret bootstrap and privileged secret access in GOFR, based on current assets and scripts under `lib/gofr-common`.

## Reviewed Assets
- Secrets inventory: `lib/gofr-common/secrets/`
  - `bootstrap_tokens.json`
  - `vault_root_token`
  - `vault_unseal_key`
  - `vault_init_output`
  - `service_creds/*.json`
- Scripts and modules:
  - `lib/gofr-common/scripts/manage_vault.sh`
  - `lib/gofr-common/scripts/bootstrap_auth.sh`
  - `lib/gofr-common/scripts/bootstrap_auth.py`
  - `lib/gofr-common/scripts/auth_env.sh`
  - `lib/gofr-common/scripts/auth_manager.sh`
  - `scripts/bootstrap_gofr_dig.sh`
  - `scripts/setup_approle.py`
  - `lib/gofr-common/src/gofr_common/auth/admin.py`
  - `lib/gofr-common/src/gofr_common/auth/policies.py`

## Current State (What Works)
1. JWT secret bootstrap already exists in Vault bootstrap flow:
   - `manage_vault.sh` creates `secret/gofr/config/jwt-signing-secret` if missing.
   - `bootstrap_gofr_dig.sh` also ensures the same secret path exists.
2. AppRole provisioning exists:
   - `setup_approle.py` provisions service roles and writes `service_creds/<service>.json`.
   - Policies are centrally defined and installed via `VaultAdmin.update_policies()`.
3. Runtime services can read JWT secret from Vault:
   - Startup scripts already read from `secret/gofr/config/jwt-signing-secret` and export runtime env.

## Security Gaps and Risks
1. Mixed and legacy secret sources
   - `auth_manager.sh` currently requires `docker/.env`, even though JWT secret is source-of-truth in Vault.
   - This creates dual-control risk and drift.

2. Over-broad policy scope for service roles
   - `POLICY_GOFR_CONFIG_READ` currently grants create/read/update/delete/list on `secret/data/gofr/auth/*`.
   - This is admin-grade authority, not least privilege for normal runtime services.

3. Secret file permissions are too permissive for critical bootstrap materials
   - Current observed modes under `lib/gofr-common/secrets/`:
     - `vault_root_token`: `rw-r--r--`
     - `vault_unseal_key`: `rw-r--r--`
     - `bootstrap_tokens.json`: `rw-r--r--`
     - `service_creds/gofr-mcp.json`, `service_creds/gofr-web.json`: `rw-r--r--`
   - These should be restricted to owner-only (`0600`) and directories (`0700`).

4. Root-token-centric operational paths remain available
   - Some flows still expect root token files for operational actions.
   - This increases blast radius during operator mistakes or host compromise.

## Recommended Target Architecture

### A. Single Source of Truth for JWT Secret
- JWT signing secret must exist only in Vault at:
  - `secret/gofr/config/jwt-signing-secret`
- Remove operational dependency on `docker/.env` for JWT usage in auth control scripts.
- `docker/.env` should not be required for auth tooling.

### B. Introduce Dedicated Admin Control AppRole
Create a dedicated control-plane role for admin scripts only.

Proposed role:
- `gofr-admin-control` (AppRole)

Proposed policy:
- `gofr-admin-control-policy`

Minimum required capabilities:
- Read/write JWT secret path:
  - `secret/data/gofr/config/jwt-signing-secret`
- Manage auth data paths:
  - `secret/data/gofr/auth/*`
  - `secret/metadata/gofr/auth/*`
- Manage service credentials path (if required by your pattern)
- No broad access to unrelated service secrets.

Only admin control scripts should use this role:
- `auth_manager.sh`
- `bootstrap_auth.sh`
- bootstrap/rotation scripts

Runtime service roles (`gofr-dig`, `gofr-web`, `gofr-mcp`) should be read-only where possible and should not have write access to auth control paths.

### C. Split Runtime vs Admin Policies
Refactor policy model in `auth/policies.py`:
- Runtime service policies:
  - Read-only to required config paths
  - No write on `gofr/auth/*`
- Admin control policy:
  - Explicit write for auth management
  - Bound to separate AppRole credentials and tighter operational controls

### D. Harden Secret-at-Rest Files
Apply and enforce permissions:
- `secrets/` directory: `0700`
- `vault_root_token`, `vault_unseal_key`, `bootstrap_tokens.json`: `0600`
- `service_creds/*.json`: `0600`

Add a bootstrap-time permission check/fix script step that fails closed if permissions are too open.

### E. Add a GOFR-common JWT Bootstrap/Rotation Control Script
Add a single canonical script under `lib/gofr-common/scripts/`, e.g.:
- `bootstrap_jwt_secret.sh` (or `manage_jwt_secret.sh`)

Required behavior:
1. Authenticate to Vault using admin control AppRole (not root token by default).
2. Check if JWT secret exists at canonical path.
3. Create if missing (bootstrap mode).
4. Optional rotate mode (write new value + emit rotation event).
5. Emit actionable structured logs.
6. Never print secret value.

Optional safety features:
- `--dry-run`
- `--require-confirm` for rotation
- versioned write + rollback guidance

## Operational Workflow (Recommended)
1. Platform bootstrap initializes Vault and enables AppRole auth.
2. Admin control AppRole and policy are provisioned.
3. `bootstrap_jwt_secret.sh` ensures JWT secret in Vault (idempotent).
4. Service AppRoles are provisioned with least-privilege runtime policies.
5. Services fetch JWT secret from Vault at startup via AppRole identity.
6. Auth management scripts use admin control AppRole for token/group administration.

## Priority Implementation Plan (Security Order)
1. **Immediate**: fix file permissions in `lib/gofr-common/secrets` and service credentials.
2. **Immediate**: stop requiring `docker/.env` in `auth_manager.sh`; use Vault-based loading.
3. **High**: split admin vs runtime Vault policies and remove runtime write capabilities.
4. **High**: add dedicated JWT bootstrap/rotation script in `gofr-common/scripts`.
5. **Medium**: reduce root token dependency in day-2 operations.

## Acceptance Criteria
- JWT secret bootstrap is idempotent and Vault-only.
- Admin operations run under dedicated admin AppRole (not runtime roles).
- Runtime roles cannot mutate auth control paths.
- No critical secret files are world/group-readable.
- `auth_manager.sh` works without `docker/.env` dependency.

## Notes
- This recommendation aligns with your objective: admin-only services/scripts can access core secrets such as JWT secret and admin token material.
- The current codebase already has most primitives; the main gap is policy separation, source-of-truth cleanup, and permission hardening.
