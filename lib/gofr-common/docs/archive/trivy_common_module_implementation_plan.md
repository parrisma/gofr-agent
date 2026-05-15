# Implementation Plan: Shared Trivy Container Vulnerability Scanner Module

Status: Executed
Depends on: [trivy_common_module_proposal.md](trivy_common_module_proposal.md)

## Confirmed Decisions From Proposal
- Module namespace: `gofr_common.security_scan`
- Default policy fail threshold: `HIGH` (and `CRITICAL`)
- Default `ignore-unfixed`: `false`
- Output in phase 1: JSON only (no SARIF)
- Image signing/attestation: out of scope for phase 1

## Scope for This Plan
Implement a reusable Trivy-based container scanner in `gofr-common` with:
- Python API
- CLI entrypoint
- policy evaluation
- normalized JSON reporting
- tests and docs

No code in this plan. This is execution sequencing only.

## Baseline and Acceptance Gates (Mandatory)
1. Baseline test run before implementation:
   - Run full suite with `./scripts/run_tests.sh` from repository root.
   - Record result in this plan under "Execution Log".
2. Acceptance test run after implementation:
   - Re-run full suite with `./scripts/run_tests.sh`.
   - Record result in this plan under "Execution Log".
3. Targeted tests are required per step before full-suite acceptance.

## Step-by-Step Execution Plan

### Step 1 — Define module structure and config contract
Deliverables:
- Create `src/gofr_common/security_scan/` package skeleton.
- Define config object and env mapping for:
  - `{PREFIX}_TRIVY_ENABLED`
  - `{PREFIX}_TRIVY_SEVERITIES`
  - `{PREFIX}_TRIVY_FAIL_ON_SEVERITY`
  - `{PREFIX}_TRIVY_TIMEOUT_SECONDS`
  - `{PREFIX}_TRIVY_IGNORE_UNFIXED`
  - `{PREFIX}_TRIVY_IGNORE_FILE`
  - `{PREFIX}_TRIVY_REPORT_PATH`
- Add explicit validation rules and defaults.

Verification:
- Unit tests for config parsing/validation and defaults.

### Step 2 — Implement Trivy execution wrapper
Deliverables:
- Implement command builder for image scan invocations.
- Implement process execution with timeout and bounded retry policy.
- Implement structured error classification:
  - command-not-found
  - timeout
  - non-zero scanner failure
  - malformed scanner output

Verification:
- Unit tests with subprocess mocking for each error class and success path.

### Step 3 — Implement result normalization
Deliverables:
- Define stable normalized report schema for phase 1 JSON output.
- Map raw Trivy JSON fields into normalized structure.
- Include summary counts by severity and scanner category.

Verification:
- Fixture-driven unit tests for normalization consistency.
- Regression test to ensure stable output keys/order-sensitive expectations where needed.

### Step 4 — Implement policy engine
Deliverables:
- Implement policy evaluator using confirmed defaults:
  - fail on `HIGH` and `CRITICAL`
  - `ignore-unfixed=false`
- Support optional ignore file path when provided.
- Produce deterministic policy decision payload (`pass`/`fail`, reasons).

Verification:
- Unit tests for all severity combinations and ignore-unfixed behavior.
- Unit tests for ignore-file interactions and edge cases.

### Step 5 — Implement service API and CLI interface
Deliverables:
- Python service entrypoint to run scan + normalize + evaluate policy.
- CLI command interface exposing target image and env-prefix behavior.
- Exit code contract:
  - `0` pass
  - non-zero for policy failure or execution error

Verification:
- Unit tests for API contract.
- CLI tests validating flags, output path behavior, and exit semantics.

### Step 6 — Integrate with gofr-common exports and docs
Deliverables:
- Update package exports (`__init__` surfaces) for security scan module.
- Add/update docs in `lib/gofr-common/docs/` describing:
  - usage
  - env vars
  - policy defaults
  - exit codes
  - known limitations for phase 1

Verification:
- Documentation sanity check and examples validated against CLI/API behavior.

### Step 7 — Add quality and security checks for new module
Deliverables:
- Extend/add tests under `test/code_quality/` if needed for module-specific constraints.
- Ensure no secrets are logged; structured logging only.
- Validate input sanitization for image refs and file paths.

Verification:
- Targeted quality/security tests pass.

### Step 8 — Pilot integration in gofr-dig (non-blocking adapter step)
Deliverables:
- Add a minimal invocation path in gofr-dig tooling/CI to call common module.
- Keep integration scoped and reversible for pilot.

Verification:
- Targeted integration test or scripted validation showing artifact output + policy exit behavior.

### Step 9 — Final regression and acceptance
Deliverables:
- Run final targeted tests for new module.
- Run full suite: `./scripts/run_tests.sh`.
- Document outcomes in "Execution Log".

Verification:
- All required tests pass.
- No unresolved regressions introduced.

## Execution Log (to be updated during execution)
- Baseline full-suite run: DONE (`./scripts/run_tests.sh` → `506 passed`)
- Step 1: DONE (created `src/gofr_common/security_scan/` package and env-driven config contract)
- Step 2: DONE (implemented Trivy runner with timeout + bounded retries + structured execution errors)
- Step 3: DONE (implemented normalization to stable report schema + severity counting)
- Step 4: DONE (implemented policy evaluator for threshold + ignore-unfixed behavior)
- Step 5: DONE (implemented service orchestration and CLI entrypoint with exit-code contract)
- Step 6: DONE (integrated exports + added module docs)
- Step 7: DONE (added targeted tests covering config, policy, runner, service, and CLI contracts)
- Step 8: DONE (added pilot invocation script: `scripts/scan_container_security.sh`)
- Step 9 / acceptance full-suite run: DONE (`./scripts/run_tests.sh` → `506 passed`)

## Change-Control Rule During Execution
If any step reveals requirements not covered here, stop and document the delta before proceeding.

## Approval
Plan was approved and executed.
