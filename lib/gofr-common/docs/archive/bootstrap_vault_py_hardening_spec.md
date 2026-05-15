# bootstrap_vault.py hardening spec

## Goal
Harden `scripts/bootstrap_vault.py` to be safe-by-default for operators and automation.

## Scope
Only `scripts/bootstrap_vault.py`.

## Problems observed
- Default Vault address is `http://localhost:8201` (violates platform rule: use Docker service names on gofr-net).
- Uses `print()` for error output (platform rule: no print()).
- Reads root token from disk without permission validation/hardening.
- Ignores existing GOFR_* env var conventions unless caller sets them manually.

## Proposed changes
1. Address resolution
   - Prefer `GOFR_VAULT_URL` if set.
   - Else prefer `VAULT_ADDR` if set.
   - Else auto-detect container and default to:
     - in containers: `http://gofr-vault:<port>`
     - on host: `http://host.docker.internal:<port>`
     (never localhost)
   - If `config/gofr_ports.env` exists, read `GOFR_VAULT_PORT` from it.

2. Root token handling
   - Prefer `GOFR_VAULT_TOKEN` then `VAULT_TOKEN` env.
   - Else read `secrets/vault_root_token`.
   - Ensure `secrets/` is 0700 and `vault_root_token` is 0600 (best-effort chmod).
   - Never echo the token.

3. Output and failure modes
   - Replace `print()` with minimal stderr output (`sys.stderr.write`).
   - Improve guidance on recovery (point to `scripts/manage_vault.sh bootstrap`).

## Non-goals
- Change Vault bootstrap semantics (delegated to `scripts/bootstrap_auth.py` / gofr_common.auth).
- Add dependencies.
