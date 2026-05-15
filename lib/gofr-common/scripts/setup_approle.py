#!/usr/bin/env python3
"""Shared GOFR AppRole provisioning entrypoint.

This script is intended to be called from project repos (via `uv run`) and is
configured by a per-project JSON file (default: `config/gofr_approles.json`).

Modes:
- default: full provision (sync policies + roles, then generate credentials)
- --policies-only: sync policies + roles without regenerating credentials
- --check: verify expected credential files exist

This script intentionally does not print secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from gofr_common.auth.admin import VaultAdmin
from gofr_common.auth.approle_provisioning import AppRoleConfigError, load_approle_config
from gofr_common.auth.backends.vault_client import VaultClient
from gofr_common.auth.backends.vault_config import VaultConfig
from gofr_common.auth.policies import POLICIES
from gofr_common.logger import get_logger
from gofr_common.vault.bootstrap import VaultBootstrap
from gofr_common.vault.secrets_discovery import (
    read_vault_root_token,
    read_vault_unseal_key,
    require_vault_bootstrap_artifacts,
)


def _read_ports_env_vault_port(ports_env_path: Path) -> str | None:
    if not ports_env_path.is_file():
        return None

    for line in ports_env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("GOFR_VAULT_PORT="):
            return line.split("=", 1)[1].strip()
    return None


def _resolve_vault_url(project_root: Path) -> str:
    vault_url = os.environ.get("GOFR_VAULT_URL") or os.environ.get("VAULT_ADDR")
    if vault_url:
        return vault_url

    vault_host = os.environ.get("GOFR_VAULT_HOST", "gofr-vault").strip() or "gofr-vault"
    vault_port = os.environ.get("GOFR_VAULT_PORT", "").strip()

    if not vault_port:
        ports_env_path = project_root / "lib" / "gofr-common" / "config" / "gofr_ports.env"
        vault_port = _read_ports_env_vault_port(ports_env_path) or ""

    if not vault_port:
        vault_port = "8201"

    return f"http://{vault_host}:{vault_port}"


def _validate_policies_exist(policy_names: list[str]) -> None:
    missing = [name for name in policy_names if name not in POLICIES]
    if missing:
        valid = ", ".join(sorted(POLICIES.keys()))
        missing_str = ", ".join(missing)
        raise AppRoleConfigError(
            "Config references unknown Vault policies: "
            f"{missing_str}. Valid policies: {valid}"
        )


def _ensure_dir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU)  # 0700
    except OSError:
        # Best-effort; some FS/mounts may ignore chmod.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision GOFR Vault AppRoles")
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd()),
        help="Project root directory (default: current working directory)",
    )
    parser.add_argument(
        "--config",
        default="config/gofr_approles.json",
        help="Path to project AppRole config JSON (default: config/gofr_approles.json)",
    )
    parser.add_argument(
        "--policies-only",
        action="store_true",
        help="Sync policies and roles only; do not regenerate credentials",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for expected credential files only; do not contact Vault",
    )

    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (project_root / config_path).resolve()

    try:
        config = load_approle_config(config_path)
    except AppRoleConfigError as exc:
        logger = get_logger("gofr")
        logger.error(
            "Invalid AppRole config",
            config_path=str(config_path),
            cause_type=type(exc).__name__,
            error=str(exc),
            remediation="Fix the config file and retry",
        )
        return 2

    logger = get_logger(config.project)

    mode = "check" if args.check else ("policies-only" if args.policies_only else "full")
    logger.info(
        "Starting AppRole provisioning",
        mode=mode,
        project=str(config.project),
        config_path=str(config_path),
    )

    credentials_dir = (project_root / config.credentials_output_dir).resolve()

    expected_files = [
        credentials_dir / f"{role.credentials_basename()}.json" for role in config.roles
    ]

    # Validate policy references before contacting Vault.
    all_policy_names: list[str] = []
    for role in config.roles:
        all_policy_names.extend(list(role.policies))
    try:
        _validate_policies_exist(all_policy_names)
    except AppRoleConfigError as exc:
        logger.error(
            "AppRole config references unknown policies",
            cause_type=type(exc).__name__,
            error=str(exc),
            remediation="Fix policy names in config to match gofr-common POLICIES",
        )
        return 2

    if args.check:
        missing = [str(p) for p in expected_files if not p.is_file()]
        if missing:
            logger.warning(
                "AppRole credential files missing",
                missing_files=missing,
                expected_dir=str(credentials_dir),
            )
            return 1
        logger.info("AppRole credential files present", expected_dir=str(credentials_dir))
        return 0

    artifacts = require_vault_bootstrap_artifacts(project_root=project_root, env=os.environ)
    vault_root_token = read_vault_root_token(artifacts)
    vault_unseal_key = read_vault_unseal_key(artifacts)

    vault_url = _resolve_vault_url(project_root)

    bootstrap = VaultBootstrap(vault_addr=vault_url)
    if not bootstrap.ensure_unsealed(vault_unseal_key):
        logger.error(
            "Vault is sealed or not reachable",
            vault_url=vault_url,
            remediation="Start and unseal Vault before provisioning AppRoles",
        )
        return 1

    client = VaultClient(VaultConfig(url=vault_url, token=vault_root_token))
    admin = VaultAdmin(client)

    try:
        admin.enable_approle_auth(mount_point=config.mount_point)
        admin.update_policies()

        for role in config.roles:
            primary = role.policies[0]
            extras = list(role.policies[1:])
            admin.provision_service_role(
                service_name=role.role_name,
                policy_name=primary,
                additional_policy_names=extras,
                token_ttl=config.token_ttl,
                token_max_ttl=config.token_max_ttl,
            )
            logger.info(
                "AppRole synced",
                role_name=role.role_name,
                policies=list(role.policies),
            )

        if args.policies_only:
            logger.info("Policy sync complete (credentials unchanged)")
            return 0

        _ensure_dir_private(credentials_dir)

        for role in config.roles:
            creds = admin.generate_service_credentials(role.role_name)
            out_path = credentials_dir / f"{role.credentials_basename()}.json"
            out_path.write_text(json.dumps(creds, indent=2) + "\n", encoding="utf-8")
            try:
                out_path.chmod(0o600)
            except OSError:
                pass

            logger.info(
                "Credentials written",
                role_name=role.role_name,
                output_file=str(out_path),
            )

        logger.info("Full provision complete", credentials_dir=str(credentials_dir))
        return 0

    except Exception as exc:
        logger.error(
            "AppRole provisioning failed",
            cause_type=type(exc).__name__,
            error=str(exc),
            remediation="Review config and Vault status, then retry",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
