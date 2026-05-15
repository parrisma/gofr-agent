# Spec: JWT Vault Single Source of Truth (Architecture A)

## Objective
Implement Recommended Target Architecture A from `jwt_bootstrap_recommendations.md`:
1. JWT signing secret is sourced from Vault only (`secret/gofr/config/jwt-signing-secret`).
2. `auth` control tooling no longer requires `docker/.env`.
3. `docker/.env` is not part of the auth control path.

## Problem
Current auth control flow in `lib/gofr-common/scripts/auth_manager.sh` hard-requires `docker/.env` and fails if it is missing, even though JWT secret source-of-truth is already Vault in other flows.

This creates:
- dual-source drift risk (`docker/.env` vs Vault)
- bootstrap confusion on fresh builds
- unnecessary dependency on local mutable file for security-critical control operations

## In Scope
- `lib/gofr-common/scripts/auth_manager.sh`
- Related auth-tool docs that currently claim/require `docker/.env` for JWT secret path
- Validation that auth manager commands work using Vault-based inputs

## Out of Scope
- Policy split (runtime vs admin AppRole) — handled in later recommendation steps
- New AppRole creation model — handled in later recommendation steps
- JWT rotation feature implementation

## Proposed Behavior
### New Source-of-Truth Contract
- Auth control tools resolve JWT secret from Vault path `secret/gofr/config/jwt-signing-secret`.
- If Vault is unavailable or unreadable, tool fails with actionable remediation.
- `docker/.env` is optional and must not be required for auth tooling.

### `auth_manager.sh` Resolution Strategy
1. Load ports config (`gofr_ports.env`) for Vault URL defaults.
2. Resolve Vault token from secure file (`secrets/vault_root_token`) or explicit env.
3. Resolve Vault address based on `--docker` flag (`gofr-vault` host in container mode).
4. Read JWT secret from Vault (`secret/gofr/config/jwt-signing-secret`).
5. Export `GOFR_JWT_SECRET` for the Python CLI process.

### Failure Behavior (required)
- If Vault token missing: fail with clear recovery options.
- If Vault path missing: fail with clear recovery options (run bootstrap script).
- If Vault unreachable: fail with endpoint context and next steps.

## Security Requirements
- Never print JWT secret value.
- Keep `GOFR_JWT_SECRET` process-local to command execution.
- Do not add new plaintext secret files.

## Acceptance Criteria
1. `./lib/gofr-common/scripts/auth_manager.sh --docker groups list` works without `docker/.env`.
2. Missing `docker/.env` no longer blocks auth manager execution.
3. JWT secret is loaded from Vault path `secret/gofr/config/jwt-signing-secret`.
4. Error messages include cause + context + remediation.
5. Existing auth manager command semantics remain unchanged.

## Assumptions (please confirm)
1. Using Vault root token for this transition is acceptable short-term for auth_manager script.
A1 - yes, what is longer term alternative ?
2. Vault path for JWT secret remains `secret/gofr/config/jwt-signing-secret`.
A2. yes
3. We should preserve current `--docker` behavior and only change secret source resolution.
A3. yes, --docker is just about hostnames not security
4. We should not delete `docker/.env`; only remove auth tooling dependency on it.
A4. delete it, we need to be sure only JWT in vault is used

## Open Questions
1. Should `auth_manager.sh` prefer AppRole credentials (if available) before root token, or keep root-token-first behavior for now?
A1. we need to bootstrap from ground zero - which fits that pattern
2. Should this change also be applied to `bootstrap_auth.sh` in the same PR, or keep this step scoped to `auth_manager.sh` only?
A2. apply to both, we need to get security sorted once and for all

## Risk Notes
- Removing `docker/.env` dependency can reveal hidden reliance in undocumented local workflows; this should be mitigated with explicit remediation messaging.
Understood, lets do it
- Vault availability becomes a hard dependency for auth control commands (which is desired for this architecture).
Understood, thats acceptable
