"""AppRole provisioning configuration + utilities.

This module defines the config format used by GOFR projects to declare
which Vault AppRoles they need and which policies should be attached.

The provisioning implementation is intentionally separate from any specific
project so it can be shared via gofr-common.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppRoleRoleConfig:
    role_name: str
    policies: tuple[str, ...]
    credentials_filename: str | None = None

    def credentials_basename(self) -> str:
        return self.credentials_filename or self.role_name


@dataclass(frozen=True, slots=True)
class AppRoleProvisioningConfig:
    schema_version: int
    project: str
    mount_point: str
    token_ttl: str
    token_max_ttl: str
    credentials_output_dir: str
    roles: tuple[AppRoleRoleConfig, ...]


class AppRoleConfigError(ValueError):
    """Raised when the AppRole provisioning config is invalid."""


def load_approle_config(config_path: Path) -> AppRoleProvisioningConfig:
    """Load and validate a per-project AppRole provisioning config."""

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppRoleConfigError(f"Config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise AppRoleConfigError(f"Invalid JSON in config file: {config_path}") from exc

    if not isinstance(raw, dict):
        raise AppRoleConfigError("Config must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise AppRoleConfigError(
            f"Unsupported schema_version: {schema_version!r} (expected 1)"
        )

    project = raw.get("project")
    if not isinstance(project, str) or not project.strip():
        raise AppRoleConfigError("'project' must be a non-empty string")

    mount_point = raw.get("mount_point", "approle")
    if not isinstance(mount_point, str) or not mount_point.strip():
        raise AppRoleConfigError("'mount_point' must be a non-empty string")

    token_ttl = raw.get("token_ttl", "1h")
    token_max_ttl = raw.get("token_max_ttl", "24h")
    if not isinstance(token_ttl, str) or not token_ttl.strip():
        raise AppRoleConfigError("'token_ttl' must be a non-empty string")
    if not isinstance(token_max_ttl, str) or not token_max_ttl.strip():
        raise AppRoleConfigError("'token_max_ttl' must be a non-empty string")

    credentials_output_dir = raw.get("credentials_output_dir", "secrets/service_creds")
    if not isinstance(credentials_output_dir, str) or not credentials_output_dir.strip():
        raise AppRoleConfigError("'credentials_output_dir' must be a non-empty string")

    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, list) or not roles_raw:
        raise AppRoleConfigError("'roles' must be a non-empty array")

    roles: list[AppRoleRoleConfig] = []
    for i, role_obj in enumerate(roles_raw):
        if not isinstance(role_obj, dict):
            raise AppRoleConfigError(f"roles[{i}] must be an object")

        role_name = role_obj.get("role_name")
        if not isinstance(role_name, str) or not role_name.strip():
            raise AppRoleConfigError(f"roles[{i}].role_name must be a non-empty string")

        policies_raw = role_obj.get("policies")
        if not isinstance(policies_raw, list) or not policies_raw:
            raise AppRoleConfigError(f"roles[{i}].policies must be a non-empty array")

        policies: list[str] = []
        for j, policy in enumerate(policies_raw):
            if not isinstance(policy, str) or not policy.strip():
                raise AppRoleConfigError(
                    f"roles[{i}].policies[{j}] must be a non-empty string"
                )
            policies.append(policy)

        credentials_filename = role_obj.get("credentials_filename")
        if credentials_filename is not None and (
            not isinstance(credentials_filename, str) or not credentials_filename.strip()
        ):
            raise AppRoleConfigError(
                f"roles[{i}].credentials_filename must be a non-empty string if provided"
            )

        roles.append(
            AppRoleRoleConfig(
                role_name=role_name,
                policies=tuple(policies),
                credentials_filename=credentials_filename,
            )
        )

    return AppRoleProvisioningConfig(
        schema_version=1,
        project=project,
        mount_point=mount_point,
        token_ttl=token_ttl,
        token_max_ttl=token_max_ttl,
        credentials_output_dir=credentials_output_dir,
        roles=tuple(roles),
    )
