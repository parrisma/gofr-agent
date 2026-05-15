# Runtime/Admin Policy Split Runbook

## Purpose
Operational runbook for the hard cutover to split runtime Vault permissions from admin-control permissions.

## Scope
- Runtime roles keep read-only shared config access.
- Admin role `gofr-admin-control` owns auth-management operations.
- Auth admin wrappers consume `gofr-admin-control` AppRole credentials.

## One-Time Cutover Steps
1. Reprovision policies and AppRoles:
   - `uv run scripts/setup_approle.py`
2. Confirm credentials files exist:
   - `secrets/service_creds/gofr-dig.json`
   - `secrets/service_creds/gofr-admin-control.json`
3. Validate wrapper commands:
   - `./lib/gofr-common/scripts/auth_manager.sh --docker groups list`
   - `./lib/gofr-common/scripts/bootstrap_auth.sh --docker --groups-only`
4. Restart services if they cache stale credentials.

## Bootstrap Wrapper Noise Control
- Hard-cutover wrapper `bootstrap_auth.sh` now sets:
  - `GOFR_BOOTSTRAP_INSTALL_POLICIES=false`
  - `GOFR_BOOTSTRAP_STORE_JWT_SECRET=false`
- Reason: `gofr-admin-control` is scoped to auth-management and should not perform broad policy/JWT write operations.
- Outcome: expected Vault permission denials are avoided and logs stay informational during normal bootstrap usage.

## Expected Policy Model
- Runtime policies (`gofr-mcp-policy`, `gofr-web-policy`, `gofr-dig-policy`):
  - `read` on `secret/data/gofr/config/*`
  - `read` on `secret/data/gofr/auth/*`
  - optional `list/read` on `secret/metadata/gofr/auth/*`
  - no write access to `secret/data/gofr/auth/*`
- Admin policy (`gofr-admin-control-policy`):
  - auth CRUD/list on `secret/data/gofr/auth/*`
  - metadata list/read on `secret/metadata/gofr/auth/*`

## Common Failures and Recovery
### Admin credentials file missing
- Cause: `gofr-admin-control` role not provisioned or secrets volume missing.
- Context: wrappers require `secrets/service_creds/gofr-admin-control.json`.
- Recovery:
  1. Run `uv run scripts/setup_approle.py`.
  2. Verify file permissions and mount path for `secrets/service_creds`.

### AppRole login fails
- Cause: invalid/stale `role_id`/`secret_id`, Vault unavailable, or role-policy mismatch.
- Context: wrappers authenticate to Vault before running auth operations.
- Recovery:
  1. Ensure Vault is reachable.
  2. Reprovision role credentials with `uv run scripts/setup_approle.py`.
  3. Retry wrapper command.

### Wrapper shows policy/JWT storage warnings during bootstrap
- Cause: admin role is intentionally scoped for auth-management and may not own full Vault policy/JWT write paths.
- Context: `bootstrap_auth.py` attempts optional policy/JWT setup and continues when these steps are denied.
- Recovery:
  1. Continue if reserved groups/tokens were created successfully.
  2. Use elevated operational bootstrap flow only when policy/JWT re-seeding is required.
