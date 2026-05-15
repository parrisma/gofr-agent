# Implementation Plan: Runtime vs Admin Vault Policy Split

Status: Draft for approval
Depends on: `runtime_admin_policy_split_spec.md`

## Confirmed Decisions
1. Admin role name: `gofr-admin-control`
2. Admin policy name: `gofr-admin-control-policy`
3. Runtime roles keep read access to `secret/data/gofr/config/*`
4. `setup_approle.py` provisions admin role by default
5. First consumers of admin role creds: `auth_manager.sh` and `bootstrap_auth.sh`
6. Cutover strategy: immediate hard cutover (no runtime fallback)

## Clarified Interpretation
- Spec item about “migration window” is superseded by hard cutover decision.
- Therefore this plan assumes no fallback to legacy runtime-write policy after rollout.

## Scope
- Split Vault policy blocks in `src/gofr_common/auth/policies.py`
- Provision/admin role wiring in `scripts/setup_approle.py`
- Update auth-control wrappers to require/admin credentials path
- Update docs + runbook for hard cutover operations
- Validate with tests and end-to-end command checks

## Out of Scope
- Secret rotation implementation
- Broad multi-project onboarding redesign

## Mandatory Test Gates
1. Baseline full suite before changes:
   - `./scripts/run_tests.sh`
2. Targeted checks during execution:
   - wrapper command checks + auth-related tests
3. Acceptance full suite after changes:
   - `./scripts/run_tests.sh`

## Step-by-Step Plan

### Step 1 — Baseline and dependency mapping
Deliverables:
- Run full baseline test suite and log result.
- Enumerate all code paths that rely on runtime auth write access and/or current role naming.

Verification:
- Baseline status recorded.
- Dependency notes captured in execution log.

### Step 2 — Split policy definitions
Deliverables:
- Refactor `policies.py` to create:
  - runtime config-read policy block
  - admin auth-management policy block
- Ensure runtime policies (`gofr-mcp`, `gofr-web`, `gofr-dig`) no longer include auth write permissions.
- Add `gofr-admin-control-policy` to policy map.

Verification:
- Static inspection confirms no runtime CRUD on `secret/data/gofr/auth/*`.
- Admin policy has required auth-management capabilities.

### Step 3 — Provision admin role by default
Deliverables:
- Update `scripts/setup_approle.py` to provision `gofr-admin-control` by default.
- Ensure credentials file for admin role is created with secure permissions.
- Keep existing service role provisioning intact for runtime services.

Verification:
- Provisioning output confirms admin role and creds creation.
- Role-policy bindings match expected split.

### Step 4 — Hard cutover in auth control wrappers
Deliverables:
- Update `auth_manager.sh` and `bootstrap_auth.sh` to consume admin-control credentials.
- Remove legacy fallback assumptions for runtime role write access.
- Fail closed if admin role credentials are missing/invalid.

Verification:
- `auth_manager.sh` admin operations work with admin creds.
- `bootstrap_auth.sh` works with admin creds.
- Missing admin creds returns actionable remediation.

### Step 5 — Docs and runbook updates
Deliverables:
- Update auth docs to reflect hard cutover and required admin role.
- Add explicit operator steps:
  - reprovision roles
  - refresh credentials
  - restart affected services/scripts

Verification:
- No docs suggest runtime roles can perform auth writes.
- Runbook includes cause/context/remediation for cutover failures.

### Step 6 — Targeted validation
Deliverables:
- Execute targeted commands/tests for:
  - policy upload
  - role provisioning
  - auth wrapper commands
- Confirm runtime services still start and read config/JWT as expected.

Verification:
- Targeted checks pass.
- No hidden runtime write dependencies remain.

### Step 7 — Full acceptance and closeout
Deliverables:
- Run acceptance full suite.
- Update execution log with outcomes.
- Document any residual follow-up items.

Verification:
- Full suite passes.
- Acceptance criteria from spec met.

## Execution Log (to update during execution)
- Baseline full-suite run: DONE (`./scripts/run_tests.sh` → 506 passed)
- Step 1: DONE
- Step 2: DONE
- Step 3: DONE
- Step 4: DONE
- Step 5: DONE
- Step 6: DONE
- Step 7 / acceptance full-suite run: DONE (`./scripts/run_tests.sh` → 506 passed)

## Change Control Rule
If implementation uncovers a dependency requiring fallback behavior, stop and document delta for decision before continuing.

## Approval
Do not start implementation until this plan is approved.
