"""Factory functions for creating storage backends.

Provides convenient factory functions to create Vault-backed token and group
stores based on configuration or environment variables.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal, Optional, Tuple

from gofr_common.logger import Logger, create_logger

from ..identity import VaultIdentity, VaultIdentityError
from .base import GroupStore, TokenStore

if TYPE_CHECKING:
    from .vault_client import VaultClient


BackendType = Literal["vault"]


class FactoryError(Exception):
    """Raised when factory fails to create a store."""

    pass


def create_token_store(
    backend: BackendType,
    *,
    # Vault backend options
    vault_client: Optional["VaultClient"] = None,
    vault_path_prefix: str = "gofr/auth",
    # Common options
    logger: Optional[Logger] = None,
) -> TokenStore:
    """Create a token store based on backend type.

    Args:
        backend: Type of backend - "vault" only
        vault_client: VaultClient for vault backend (required for "vault")
        vault_path_prefix: Path prefix in Vault for secrets
        logger: Optional logger instance

    Returns:
        TokenStore implementation

    Raises:
        FactoryError: If required options are missing

    Example:
        # Vault store
        client = VaultClient(config)
        store = create_token_store("vault", vault_client=client)
    """
    if backend != "vault":
        raise FactoryError("Only 'vault' backend is supported")

    if vault_client is None:
        raise FactoryError("'vault_client' is required for vault backend")
    # Late import to avoid circular dependency
    from .vault import VaultTokenStore

    return VaultTokenStore(
        client=vault_client,
        path_prefix=vault_path_prefix,
        logger=logger,
    )


def create_group_store(
    backend: BackendType,
    *,
    # Vault backend options
    vault_client: Optional["VaultClient"] = None,
    vault_path_prefix: str = "gofr/auth",
    # Common options
    logger: Optional[Logger] = None,
) -> GroupStore:
    """Create a group store based on backend type.

    Args:
        backend: Type of backend - "vault" only
        vault_client: VaultClient for vault backend (required for "vault")
        vault_path_prefix: Path prefix in Vault for secrets
        logger: Optional logger instance

    Returns:
        GroupStore implementation

    Raises:
        FactoryError: If required options are missing

    Example:
        # Vault store
        client = VaultClient(config)
        store = create_group_store("vault", vault_client=client)
    """
    if backend != "vault":
        raise FactoryError("Only 'vault' backend is supported")

    if vault_client is None:
        raise FactoryError("'vault_client' is required for vault backend")
    # Late import to avoid circular dependency
    from .vault import VaultGroupStore

    return VaultGroupStore(
        client=vault_client,
        path_prefix=vault_path_prefix,
        logger=logger,
    )


def create_vault_client_from_env(
    prefix: str = "GOFR",
    *,
    logger: Optional[Logger] = None,
) -> "VaultClient":
    """Create a VaultClient from environment variables.

    Prefers AppRole credentials injected at /run/secrets/vault_creds
    (via VaultIdentity with background token renewal). Falls back to
    env-based VaultConfig (token or AppRole via env vars).

    Reads configuration from environment:
        - {PREFIX}_VAULT_URL: Vault server URL
        - {PREFIX}_VAULT_TOKEN: Vault token (or use AppRole)
        - {PREFIX}_VAULT_ROLE_ID: AppRole role ID
        - {PREFIX}_VAULT_SECRET_ID: AppRole secret ID

    Args:
        prefix: Environment variable prefix (e.g., "GOFR_DOC")
        logger: Optional logger instance

    Returns:
        Authenticated VaultClient

    Raises:
        FactoryError: If authentication fails
    """
    from .vault_client import VaultClient
    from .vault_config import VaultConfig

    log = logger or create_logger(name="vault-factory")
    prefix = prefix.rstrip("_")
    env_prefix = prefix.upper().replace("-", "_")

    if VaultIdentity.is_available():
        try:
            identity = VaultIdentity(
                vault_addr=os.environ.get(f"{env_prefix}_VAULT_URL"),
            ).login()
            # Start background token renewal to prevent expiration (AppRole tokens
            # have 1h TTL by default). Without this, long-running services fail
            # after the initial token expires.
            identity.start_renewal()
            client = identity.get_client()
            log.info(
                "VaultIdentity authenticated with auto-renewal enabled",
                vault_addr=identity.vault_addr,
            )
            return client
        except VaultIdentityError as e:
            raise FactoryError(f"Vault identity login failed: {e}") from e
    else:
        # Fall back to env-based config (token or AppRole via env vars)
        vault_config = VaultConfig.from_env(prefix)
        return VaultClient(vault_config, logger=logger)


def create_stores_from_env(
    prefix: str = "GOFR",
    *,
    vault_client: Optional["VaultClient"] = None,
    logger: Optional[Logger] = None,
) -> Tuple[TokenStore, GroupStore]:
    """Create token and group stores from environment variables.

        Reads configuration from environment:
        - {PREFIX}_AUTH_BACKEND: Must be "vault"
        - {PREFIX}_VAULT_URL: Vault server URL (if vault_client not provided)
        - {PREFIX}_VAULT_TOKEN: Vault token (if vault_client not provided)
        - {PREFIX}_VAULT_ROLE_ID: AppRole role ID (if vault_client not provided)
        - {PREFIX}_VAULT_SECRET_ID: AppRole secret ID (if vault_client not provided)
        - {PREFIX}_VAULT_MOUNT_POINT: KV mount point (default: "secret")
        - {PREFIX}_VAULT_PATH_PREFIX: Path prefix (default: "{prefix}/auth")

    Args:
        prefix: Environment variable prefix (e.g., "GOFR_DIG")
        vault_client: Optional pre-built VaultClient. If None, creates one
            via create_vault_client_from_env().
        logger: Optional logger instance

    Returns:
        Tuple of (TokenStore, GroupStore)

    Raises:
        FactoryError: If configuration is invalid or missing

    Example:
        # With GOFR_DIG_AUTH_BACKEND=vault and vault env vars set
        token_store, group_store = create_stores_from_env("GOFR_DIG")

        # Or share a VaultClient with JwtSecretProvider
        client = create_vault_client_from_env("GOFR_DIG")
        token_store, group_store = create_stores_from_env("GOFR_DIG", vault_client=client)
    """
    log = logger or create_logger(name="store-factory")

    # Normalize prefix (strip trailing underscore if present)
    prefix = prefix.rstrip("_")

    # Read backend type
    backend_str = os.environ.get(f"{prefix}_AUTH_BACKEND", "").lower()

    if backend_str != "vault":
        raise FactoryError(
            f"Invalid backend type '{backend_str or 'unset'}'. "
            f"Set {prefix}_AUTH_BACKEND=vault and configure Vault env vars."
        )

    backend: BackendType = backend_str  # type: ignore

    log.debug(f"Creating stores with backend: {backend}", prefix=prefix)

    # Late imports for vault
    from .vault import VaultGroupStore, VaultTokenStore

    # Build VaultClient if not provided
    if vault_client is None:
        vault_client = create_vault_client_from_env(prefix, logger=logger)

    # Get path prefix (default to lowercase prefix)
    default_prefix = f"{prefix.lower().replace('_', '/')}/auth"
    path_prefix = os.environ.get(
        f"{prefix}_VAULT_PATH_PREFIX",
        default_prefix,
    )

    log.debug(
        "Using vault backend",
        path_prefix=path_prefix,
    )

    return (
        VaultTokenStore(
            client=vault_client,
            path_prefix=path_prefix,
            logger=logger,
        ),
        VaultGroupStore(
            client=vault_client,
            path_prefix=path_prefix,
            logger=logger,
        ),
    )
