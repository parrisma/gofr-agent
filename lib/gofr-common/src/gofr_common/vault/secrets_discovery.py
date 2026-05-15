"""Vault bootstrap artifact discovery.

GOFR projects may store Vault bootstrap artifacts (root token, unseal key) in
multiple possible locations depending on whether they're running on the host,
inside a dev container, or using a shared Docker volume.

This module centralizes the discovery logic so individual projects do not
re-implement path probing.

Precedence order:
  1) GOFR_SHARED_SECRETS_DIR (explicit override)
  2) /run/gofr-secrets       (shared secrets volume mount)
  3) <project_root>/secrets
  4) <project_root>/lib/gofr-common/secrets

Notes:
- This module avoids logging and does not print secrets.
- Callers can read file contents explicitly when needed.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class VaultBootstrapArtifacts:
    """Paths to Vault bootstrap artifacts."""

    secrets_dir: Path
    root_token_file: Path
    unseal_key_file: Path


def _read_secret_file(path: Path, *, label: str) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{label} file is empty: {path}")
    return value


def read_vault_root_token(artifacts: VaultBootstrapArtifacts) -> str:
    """Read the Vault root token from the discovered artifacts."""

    return _read_secret_file(artifacts.root_token_file, label="vault_root_token")


def read_vault_unseal_key(artifacts: VaultBootstrapArtifacts) -> str:
    """Read the Vault unseal key from the discovered artifacts."""

    return _read_secret_file(artifacts.unseal_key_file, label="vault_unseal_key")


def candidate_secrets_dirs(
    project_root: Path,
    env: Mapping[str, str] | None = None,
    extra_candidates: Sequence[Path] | None = None,
) -> list[Path]:
    """Return candidate directories for Vault bootstrap artifacts."""

    env = env or {}

    candidates: list[Path] = []

    override = env.get("GOFR_SHARED_SECRETS_DIR", "").strip()
    if override:
        candidates.append(Path(override))

    candidates.append(Path("/run/gofr-secrets"))
    candidates.append(project_root / "secrets")
    candidates.append(project_root / "lib" / "gofr-common" / "secrets")

    if extra_candidates:
        candidates.extend(list(extra_candidates))

    # De-duplicate while preserving order
    seen: set[Path] = set()
    deduped: list[Path] = []
    for directory in candidates:
        directory = directory.expanduser()
        if directory in seen:
            continue
        seen.add(directory)
        deduped.append(directory)

    return deduped


def discover_vault_bootstrap_artifacts(
    project_root: Path,
    env: Mapping[str, str] | None = None,
    extra_candidates: Sequence[Path] | None = None,
) -> VaultBootstrapArtifacts | None:
    """Discover Vault bootstrap artifacts, returning None if not found."""

    for directory in candidate_secrets_dirs(
        project_root=project_root, env=env, extra_candidates=extra_candidates
    ):
        root_token_file = directory / "vault_root_token"
        unseal_key_file = directory / "vault_unseal_key"

        if root_token_file.is_file() and unseal_key_file.is_file():
            return VaultBootstrapArtifacts(
                secrets_dir=directory,
                root_token_file=root_token_file,
                unseal_key_file=unseal_key_file,
            )

    return None


def require_vault_bootstrap_artifacts(
    project_root: Path,
    env: Mapping[str, str] | None = None,
    extra_candidates: Sequence[Path] | None = None,
) -> VaultBootstrapArtifacts:
    """Discover Vault bootstrap artifacts, raising if not found."""

    artifacts = discover_vault_bootstrap_artifacts(
        project_root=project_root, env=env, extra_candidates=extra_candidates
    )
    if artifacts:
        return artifacts

    checked = candidate_secrets_dirs(
        project_root=project_root, env=env, extra_candidates=extra_candidates
    )
    checked_display = "\n".join(f"- {p}" for p in checked)
    raise FileNotFoundError(
        "Vault bootstrap artifacts not found (vault_root_token + vault_unseal_key).\n"
        "Checked the following directories:\n"
        f"{checked_display}\n"
        "Fix: mount the shared secrets volume at /run/gofr-secrets, set GOFR_SHARED_SECRETS_DIR, "
        "or run the platform bootstrap in one GOFR project first."
    )


def _vault_reachable(vault_url: str, timeout_s: float) -> bool:
    try:
        req = urllib.request.Request(f"{vault_url.rstrip('/')}/v1/sys/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            # Any HTTP response means the endpoint is reachable.
            _ = resp.read()
            return True
    except urllib.error.HTTPError:
        # Vault uses non-2xx for health states (sealed, standby, etc.).
        return True
    except Exception:
        return False


def validate_vault_token(vault_url: str, token: str, timeout_s: float = 2.0) -> bool:
    """Return True if the token is accepted by Vault.

    Notes:
    - This function does not log secrets.
    - Network failures are treated as invalid here; callers that need to
      distinguish unreachable Vault should check reachability separately.
    """

    token = (token or "").strip()
    if not token:
        return False

    req = urllib.request.Request(
        f"{vault_url.rstrip('/')}/v1/auth/token/lookup-self",
        headers={"X-Vault-Token": token},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            _ = resp.read()
            return resp.status == 200
    except urllib.error.HTTPError as e:
        # 403 is the common case for revoked/invalid tokens.
        return e.code == 200
    except Exception:
        return False


def discover_vault_bootstrap_artifacts_validated(
    project_root: Path,
    vault_url: str,
    env: Mapping[str, str] | None = None,
    extra_candidates: Sequence[Path] | None = None,
    timeout_s: float = 2.0,
) -> VaultBootstrapArtifacts | None:
    """Discover bootstrap artifacts and validate the root token against live Vault.

    Behavior:
    - If Vault is unreachable: return None (caller decides what to do).
    - If Vault is reachable: return the first candidate whose token validates.
    - Never raises for validation failures.
    """

    if not _vault_reachable(vault_url=vault_url, timeout_s=timeout_s):
        return None

    for directory in candidate_secrets_dirs(
        project_root=project_root, env=env, extra_candidates=extra_candidates
    ):
        root_token_file = directory / "vault_root_token"
        unseal_key_file = directory / "vault_unseal_key"

        if not (root_token_file.is_file() and unseal_key_file.is_file()):
            continue

        try:
            token = root_token_file.read_text(encoding="utf-8").strip()
        except Exception:
            continue

        if validate_vault_token(vault_url=vault_url, token=token, timeout_s=timeout_s):
            return VaultBootstrapArtifacts(
                secrets_dir=directory,
                root_token_file=root_token_file,
                unseal_key_file=unseal_key_file,
            )

    return None
