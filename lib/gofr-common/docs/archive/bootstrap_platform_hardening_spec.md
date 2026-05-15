# bootstrap_platform.sh hardening spec

## Goal
Make `scripts/bootstrap_platform.sh` safer and easier to use for operators on clean machines while preserving its current behaviour (idempotent, guided prompts, shared infra bootstrap).

## Non-goals
- Change Vault semantics, policies, or secrets layout.
- Replace `manage_vault.sh` as the Vault authority.
- Add new external dependencies.

## Current problems
- ERR trap is not guaranteed to fire inside functions without `errtrace`.
- File logging via `tee` can unintentionally capture sensitive bootstrap output if any downstream command prints secrets.
- Some user-facing messages are stale (secrets seeding description no longer matches hardened runtime-only seeding scripts).
- Permissions hardening is not explicit (no `umask 077`).

## Proposed changes (behaviour-preserving)
1. Enable `errtrace` (`set -Eeuo pipefail`) so the `on_error` trap is effective in functions.
2. Set `umask 077` early so generated logs and any created local files default to restrictive permissions.
3. Harden logging:
   - keep file logging as default, but add a clear warning that logs may contain sensitive output.
   - ensure log file permissions are restrictive.
4. Update `seed_secrets_volume()` messaging to reflect Phase 1 hardening: runtime credentials only (service_creds) and never bootstrap artifacts (root token/unseal key).
5. Minor shell robustness:
   - quote variable expansions consistently.
   - ensure docker network/volume creation uses quoted names.

## Safety constraints
- Do not print Vault tokens, unseal keys, or root tokens.
- Prefer Docker service names on `gofr-net` (no localhost).
- Keep output ASCII-only.
