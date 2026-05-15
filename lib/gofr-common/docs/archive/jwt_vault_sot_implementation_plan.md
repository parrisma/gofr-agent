# Implementation Plan: JWT Vault Single Source of Truth (Architecture A)

Status: Executed
Depends on: `jwt_vault_sot_spec.md`

## Confirmed Decisions from Spec
1. Vault is the only source for JWT secret (`secret/gofr/config/jwt-signing-secret`).
2. Apply change to both:
   - `lib/gofr-common/scripts/auth_manager.sh`
   - `lib/gofr-common/scripts/bootstrap_auth.sh`
3. Preserve `--docker` semantics (hostname selection only).
4. Remove auth-tooling dependency on `docker/.env`.
5. Vault hard dependency is acceptable for auth control tooling.
6. Short-term root-token bootstrap path is acceptable.

## Clarification: Long-Term Alternative to Root Token
Long-term target: use dedicated admin control AppRole (least privilege) for day-2 auth operations; keep root token for initial break-glass/bootstrap only.

## Scope
- Refactor auth control scripts to load JWT secret from Vault only.
- Remove hard requirement to source `docker/.env` in auth control flows.
- Update docs and help text that currently mention `.env` as auth source.
- Validate with targeted + full test runs.

## Out of Scope
- Full policy redesign (runtime vs admin split) implementation.
- JWT secret rotation feature.
- AppRole redesign beyond preserving existing bootstrap behavior.

## Mandatory Test Gates
1. Baseline full suite before code changes:
   - `./scripts/run_tests.sh`
2. Targeted verification during implementation:
   - auth CLI/wrapper focused checks
   - code quality checks
3. Acceptance full suite after all changes:
   - `./scripts/run_tests.sh`

## Step-by-Step Plan

### Step 1 — Capture baseline and identify `.env` dependencies
Deliverables:
- Run baseline full suite and record outcome.
- Enumerate all `.env` assumptions in `auth_manager.sh` and `bootstrap_auth.sh` (including help text/errors).

Verification:
- Baseline result logged.
- Dependency list documented in execution notes.

### Step 2 — Refactor `auth_manager.sh` to Vault-only secret resolution
Deliverables:
- Remove hard-fail on missing `docker/.env`.
- Keep ports loading from `gofr_ports.env`.
- Resolve Vault token from explicit env and secure token file fallback.
- Fetch JWT secret from Vault path `secret/gofr/config/jwt-signing-secret`.
- Export `GOFR_JWT_SECRET` only for process execution.
- Add cause/context/remediation error messages for:
  - missing token
  - Vault unreachable
  - missing JWT path

Verification:
- `auth_manager.sh --docker groups list` works with no `docker/.env` dependency.
- Failure modes are actionable and secret-safe.

### Step 3 — Refactor `bootstrap_auth.sh` to Vault-only JWT sourcing
Deliverables:
- Remove requirement text and behavior that expects JWT from `.env`.
- Read JWT secret from Vault path using configured Vault token/URL.
- Maintain existing prefix/env mode semantics.
- Keep `--docker` behavior unchanged except for source-of-truth switch.

Verification:
- Bootstrap wrapper runs with Vault-sourced JWT and no `.env` auth dependency.
- Error handling mirrors required cause/context/remediation format.

### Step 4 — Documentation update for source-of-truth contract
Deliverables:
- Update script usage/help text and comments in both wrappers.
- Update relevant docs under `lib/gofr-common/docs/auth/` and script docs to remove `.env` as auth source.
- Document break-glass bootstrap path and long-term AppRole target.

Verification:
- No docs instruct JWT auth sourcing from `docker/.env` for auth tooling.

### Step 5 — Tests and security checks
Deliverables:
- Add/adjust tests for both wrappers and/or auth bootstrap flows as appropriate.
- Verify no JWT secret value is printed.
- Verify no new plaintext secret files are introduced.

Verification:
- Targeted tests pass.
- Code quality gate passes.

### Step 6 — Optional cleanup of local `docker/.env` auth coupling
Deliverables:
- Ensure auth tooling no longer depends on `docker/.env`.
- If present locally, treat as non-authoritative legacy artifact.
- Do not require it for successful auth control operations.

Verification:
- Removing/renaming local `docker/.env` does not break auth wrappers.

### Step 7 — Final acceptance and closeout
Deliverables:
- Run final full suite and record result.
- Record completed outcomes and any residual follow-ups.

Verification:
- Full suite passes.
- Acceptance criteria from spec are met.

## Execution Log (to update during execution)
- Baseline full-suite run: DONE (`./scripts/run_tests.sh` → `506 passed`)
- Step 1: DONE (confirmed `.env` dependency points in wrappers + docs)
- Step 2: DONE (`auth_manager.sh` now Vault-sources JWT; removed hard dependency on `docker/.env`)
- Step 3: DONE (`bootstrap_auth.sh` now Vault-sources JWT and no longer instructs `.env` sourcing)
- Step 4: DONE (updated wrapper/help/manual docs to reflect Vault-only JWT path)
- Step 5: DONE (live wrapper validations passed for `auth_manager.sh` and `bootstrap_auth.sh`)
- Step 6: DONE (removed legacy `docker/.env`; verified auth manager still works)
- Step 7 / acceptance full-suite run: DONE (`./scripts/run_tests.sh` → `506 passed`)

## Change Control Rule
If implementation reveals behavior outside this plan, stop and document delta before proceeding.

## Approval
Do not start implementation until this plan is approved.

Plan approved and fully executed.
