#!/usr/bin/env python3
"""
Shared Vault bootstrap: ensure JWT secret, reserved groups, and bootstrap tokens.
Uses existing gofr_common.auth bootstrap_auth logic against the shared Vault.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def eprint(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def _in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_bytes()
        return b"docker" in cgroup or b"containerd" in cgroup
    except Exception:
        return False


def _read_env_file_value(file_path: Path, key: str) -> str | None:
    if not file_path.exists():
        return None
    try:
        for raw_line in file_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() != key:
                continue
            value = v.strip().strip('"').strip("'")
            return value
    except Exception:
        return None
    return None


def resolve_vault_url(project_root: Path) -> str:
    # Prefer GOFR_* env vars, then Vault-standard vars.
    explicit = os.environ.get("GOFR_VAULT_URL") or os.environ.get("VAULT_ADDR")
    if explicit:
        return explicit

    ports_file = project_root / "config" / "gofr_ports.env"
    port = _read_env_file_value(ports_file, "GOFR_VAULT_PORT") or "8201"

    if _in_container():
        return f"http://gofr-vault:{port}"
    return f"http://host.docker.internal:{port}"


def resolve_vault_token(secrets_dir: Path) -> str | None:
    # Prefer GOFR_* env vars, then Vault-standard vars.
    token = os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN")
    if token:
        return token

    root_token_file = secrets_dir / "vault_root_token"
    if not root_token_file.exists():
        return None

    try:
        token = root_token_file.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return token or None


# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SECRETS_DIR = PROJECT_ROOT / "secrets"

# Import bootstrap_auth from gofr-common
sys.path.insert(0, str(PROJECT_ROOT))
from scripts import bootstrap_auth  # type: ignore  # noqa: E402


def main() -> int:
    # Ensure secrets exist with restrictive permissions.
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SECRETS_DIR.chmod(0o700)
    except Exception:
        pass

    # Resolve Vault URL and token.
    vault_url = resolve_vault_url(PROJECT_ROOT)
    vault_token = resolve_vault_token(SECRETS_DIR)
    if not vault_token:
        eprint("[ERROR] Vault token not found.")
        eprint(
            f"[ERROR] Expected env GOFR_VAULT_TOKEN/VAULT_TOKEN or file: {SECRETS_DIR / 'vault_root_token'}"
        )
        eprint("[ERROR] Recovery: bootstrap Vault: ./scripts/manage_vault.sh bootstrap")
        return 1

    # Best-effort: ensure token file permissions are restrictive when present.
    token_path = SECRETS_DIR / "vault_root_token"
    if token_path.exists():
        try:
            token_path.chmod(0o600)
        except Exception:
            pass

    # Set env for bootstrap_auth
    os.environ.setdefault("GOFR_AUTH_BACKEND", "vault")
    os.environ.setdefault("GOFR_VAULT_URL", vault_url)
    os.environ.setdefault("GOFR_VAULT_TOKEN", vault_token)
    os.environ.setdefault("GOFR_VAULT_PATH_PREFIX", "gofr/auth")
    os.environ.setdefault("GOFR_VAULT_MOUNT_POINT", "secret")

    # Run bootstrap_auth main
    return bootstrap_auth.main()


if __name__ == "__main__":
    sys.exit(main())
