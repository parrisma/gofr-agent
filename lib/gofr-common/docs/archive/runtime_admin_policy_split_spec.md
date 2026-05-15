# Spec: Split Runtime vs Admin Vault Policies

## Objective
Harden Vault access controls by separating runtime service permissions from admin control permissions.

## Problem
Current policy composition in `src/gofr_common/auth/policies.py` grants runtime service roles write access to `secret/data/gofr/auth/*` via `POLICY_GOFR_CONFIG_READ`.

That is admin-grade authority and violates least privilege for runtime services.

## Current State (Observed)
- Runtime policies (`gofr-mcp-policy`, `gofr-web-policy`, `gofr-dig-policy`) include `POLICY_GOFR_CONFIG_READ`.
- `POLICY_GOFR_CONFIG_READ` currently includes:
  - read on `secret/data/gofr/config/*`
  - create/read/update/delete/list on `secret/data/gofr/auth/*`
  - list/read on `secret/metadata/gofr/auth/*`
- AppRole provisioning currently targets service role `gofr-dig` with `gofr-dig-policy` (+ logging policy).

## In Scope
- `lib/gofr-common/src/gofr_common/auth/policies.py`
- `scripts/setup_approle.py` (to wire an admin-control role where needed)
- Auth/bootstrap/admin script wiring where admin policy attachment is required
- Tests and docs affected by policy split

## Out of Scope
- Full secret-rotation framework
- Re-architecting all service onboarding flows
- Non-auth Vault secret domains outside this policy split

## Proposed Design
### 1) Create separate policy blocks
- `POLICY_GOFR_CONFIG_RUNTIME_READ`
  - Read-only access for runtime services:
    - `secret/data/gofr/config/*`
  - No write access to `gofr/auth/*`

- `POLICY_GOFR_AUTH_ADMIN`
  - Admin-only management access:
    - `secret/data/gofr/auth/*` (CRUD/list)
    - `secret/metadata/gofr/auth/*` (list/read)
    - Any additional minimal admin control paths needed for auth operations

### 2) Runtime policy composition
- `gofr-mcp-policy`, `gofr-web-policy`, `gofr-dig-policy` include:
  - runtime config read, and
  - runtime auth-store read (for token verification / group membership checks)
- Runtime policies must not include `POLICY_GOFR_AUTH_ADMIN`.

### 3) Admin control role and policy
- Add policy map entry for `gofr-admin-control-policy`.
- Provision dedicated AppRole (e.g., `gofr-admin-control`) for admin scripts.
- Admin scripts use this role for auth-management operations.

### 4) Backward compatibility and migration
- During migration, keep existing roles functional while provisioning admin role.
- Explicitly document one-time reprovision/restart steps to refresh role policy attachments.

## Security Requirements
- Runtime services cannot mutate `gofr/auth/*`.
- Admin capabilities are restricted to dedicated admin role only.
- No secret values logged.
- Error output includes cause + context + remediation.

## Acceptance Criteria
1. Runtime policies no longer grant write access to `secret/data/gofr/auth/*`.
2. Admin control policy exists and is attached only to admin role.
3. Runtime service startup and normal operations continue working.
4. Auth admin operations function under admin-control role.
5. Tests and docs updated to reflect policy split.

## Assumptions to Confirm
1. Role name `gofr-admin-control` is acceptable.
A1. yes
2. Policy name `gofr-admin-control-policy` is acceptable.
A2 yes
3. Runtime roles may still read `secret/data/gofr/config/*` for JWT/config needs.
A3. yes
4. We will keep one migration window where old role credentials may still exist until reprovision.
A4 dont understand this, sorry

## Open Questions
1. Should `setup_approle.py` provision admin role by default, or behind a flag?
A1. bny default
2. Which scripts should be first consumers of admin-control credentials (`auth_manager.sh`, `bootstrap_auth.sh`, both)?
A2, yes these two
3. Do you want immediate hard cutover (fail if admin role missing) or phased transition (warn + fallback)?
A3. hard cut over

## Risks
- Tightening runtime policy may surface hidden write dependencies in scripts/services.
- Admin-role cutover requires clear operator runbook to avoid auth tooling outages.

## Non-Code Validation Plan
- Validate policy documents generated in Vault.
- Validate role-policy bindings after provisioning.
- Validate runtime service behavior and admin command behavior separately.
