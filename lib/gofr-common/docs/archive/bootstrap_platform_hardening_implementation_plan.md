# bootstrap_platform.sh hardening implementation plan

1. Update shell options
   - Change `set -euo pipefail` to `set -Eeuo pipefail`.
   - Add `umask 077` near the top.

2. Logging hardening
   - When creating the log file, explicitly `touch` then `chmod 600` it before `tee` redirection.
   - Add a one-line warning that bootstrap logs may contain sensitive output depending on downstream scripts.

3. Secrets seeding messaging
   - Update `seed_secrets_volume()` messages to say it should copy runtime credentials (service_creds) only.
   - Explicitly warn not to copy Vault bootstrap artifacts into runtime volumes.

4. Validate
   - Run `bash -n scripts/bootstrap_platform.sh`.
   - Run `shellcheck` if available (optional).

5. Commit
   - Commit changes in gofr-common submodule.
   - Update gofr-doc submodule pointer and push.
