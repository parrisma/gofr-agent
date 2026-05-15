# Proposal: Shared Trivy Container Vulnerability Scanner Module

## Purpose
Create a reusable `gofr-common` module that standardizes container vulnerability scanning across GOFR services using Trivy, with consistent outputs, policies, and CI/runtime integration.

## Problem
Today, container vulnerability scanning is not centralized in `gofr-common`, which creates risk of:
- Inconsistent scan behavior across projects
- Different severity thresholds and fail policies
- Non-uniform report formats, making aggregation and automation harder
- Duplicate implementation effort in each service

## Goals
- Provide one shared scanning module in `gofr-common` for all GOFR services.
- Support scanning Docker images by tag/digest and optional filesystem scans.
- Enforce a common vulnerability policy (severity levels, ignore handling, fail criteria).
- Emit structured machine-readable output for CI/CD and operational use.
- Integrate with existing GOFR logging and configuration patterns.

## Non-Goals
- Building a custom vulnerability engine (Trivy remains the scanner).
- Replacing per-project deployment workflows.
- Introducing a UI/dashboard in this phase.

## Proposed Module Scope
Proposed package area:
- `src/gofr_common/security_scan/` (or `src/gofr_common/vuln_scan/`)

Proposed responsibilities:
1. Trivy execution wrapper
   - Build and run standardized Trivy commands
   - Handle timeouts, retries, and process errors
2. Policy evaluation
   - Apply shared severity thresholds and fail/pass rules
   - Support ignore file and allowlist handling
3. Result normalization
   - Convert Trivy JSON output into a stable internal schema
   - Summarize counts by severity and scanner type
4. Report export
   - Write JSON artifacts for CI
   - Optional concise text summary for logs
5. Configuration binding
   - Read settings from GOFR env-prefix patterns

## Configuration Model (Proposed)
Shared environment variables (prefix-aware, e.g. `GOFR_DIG_`, `GOFR_DOC_`):
- `{PREFIX}_TRIVY_ENABLED` (default: true in CI, optional locally)
- `{PREFIX}_TRIVY_SEVERITIES` (default: `CRITICAL,HIGH`)
- `{PREFIX}_TRIVY_FAIL_ON_SEVERITY` (default: `HIGH`)
- `{PREFIX}_TRIVY_TIMEOUT_SECONDS` (default: 300)
- `{PREFIX}_TRIVY_IGNORE_UNFIXED` (default: false)
- `{PREFIX}_TRIVY_IGNORE_FILE` (optional path)
- `{PREFIX}_TRIVY_REPORT_PATH` (default project artifacts path)

## Standard Outputs (Proposed)
- Normalized JSON report containing:
  - target image
  - scan timestamp
  - vulnerabilities grouped by severity
  - policy decision (`pass`/`fail`)
  - reasons for failure
- Process exit semantics:
  - `0`: scan passed policy
  - non-zero: scanner error or policy failure

## Integration Points
- CI pipeline step in each project to call the shared module command.
- Optional pre-release gate in deployment scripts.
- Optional periodic scheduled scan for long-lived production images.

## Operational Expectations
- Use Trivy DB cache to reduce repeated scan latency.
- Use pinned Trivy version per platform baseline to avoid drift.
- Emit structured logs through GOFR logging primitives.
- Keep secrets out of scan logs and artifacts.

## Security and Reliability Requirements
- Validate all target inputs (image refs, paths).
- Use bounded execution (timeouts, controlled retries).
- Fail closed when policy cannot be evaluated.
- Distinguish scanner execution errors from policy failures.

## Rollout Plan (High-Level)
1. Build module in `gofr-common` with unit tests and policy tests.
2. Pilot integration in one service (recommended: `gofr-dig`).
3. Validate report compatibility in CI and tune policy thresholds.
4. Roll out to sister projects (`gofr-doc`, others).
5. Enforce as required gate once baseline false positives are resolved.

## Success Criteria
- All GOFR services use the same scanner module and policy contract.
- CI reports are consistent and machine-parseable across services.
- Policy failures are actionable and reproducible locally and in CI.
- Mean time to remediation improves via standardized output.

## Assumptions To Confirm
1. Trivy is the mandated scanner for GOFR container security checks.
2. Primary target is container image scanning; filesystem scan is secondary.
3. Policy gate should fail builds on `HIGH`/`CRITICAL` by default.
4. Shared module should expose both Python API and CLI entrypoint.
5. Initial rollout should prioritize CI integration over runtime daemon mode.

## Open Questions (Needs User Decision)
1. Module namespace: `security_scan` vs `vuln_scan`?
A1. security_scan
2. Default fail threshold: `HIGH` or `CRITICAL` only?
A2. HIGH
3. Should `ignore-unfixed` default to true or false?
A3. False
4. Should SARIF output be required in phase 1 for GitHub code scanning?
A4. `no` for phase 1, keep JSON only first
5. Should image signing/attestation checks be in-scope now or a later phase?
A5. later phase. Keep phase 1 focused on Trivy vulnerability scanning only.

