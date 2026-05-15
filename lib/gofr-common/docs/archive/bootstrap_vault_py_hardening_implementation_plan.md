# bootstrap_vault.py hardening implementation plan

1. Replace localhost default
   - Add `resolve_vault_url()` that never returns localhost.
   - Load `config/gofr_ports.env` when present (simple KEY=VALUE parser).
   - Default URL:
     - in containers: http://gofr-vault:<port>
     - on host: http://host.docker.internal:<port>

2. Harden token discovery
   - Prefer `GOFR_VAULT_TOKEN`, then `VAULT_TOKEN`, else read `secrets/vault_root_token`.
   - Apply best-effort permissions: secrets dir 0700, token file 0600.

3. Replace print()
   - Implement `eprint(msg)` using stderr write.

4. Keep compatibility
   - Continue to set the same env vars expected by `scripts/bootstrap_auth.py`.

5. Validate
   - `uv run python -m py_compile scripts/bootstrap_vault.py`
   - Run with no env in dev container to ensure it targets `gofr-vault`.

6. Commit/push
   - Commit in gofr-common and update gofr-doc submodule pointer.
