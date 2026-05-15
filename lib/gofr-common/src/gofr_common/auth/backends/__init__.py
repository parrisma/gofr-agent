"""Storage backends for GOFR authentication.

Vault is the only supported storage backend for tokens and groups.

Usage:
    from gofr_common.auth.backends import (
        TokenStore,
        GroupStore,
        VaultConfig,
        VaultClient,
        create_token_store,
        create_group_store,
        create_stores_from_env,
    )

    # Configure Vault connection
    vault_config = VaultConfig.from_env("GOFR_DIG")
    vault_client = VaultClient(vault_config)

    # Or use factory functions
    token_store, group_store = create_stores_from_env("GOFR_DIG")
"""

from .base import GroupStore, StorageError, StorageUnavailableError, TokenStore
from .factory import (
    BackendType,
    FactoryError,
    create_group_store,
    create_stores_from_env,
    create_token_store,
    create_vault_client_from_env,
)
from .vault import VaultGroupStore, VaultTokenStore
from .vault_client import (
    VaultAuthenticationError,
    VaultClient,
    VaultConnectionError,
    VaultError,
    VaultNotFoundError,
    VaultPermissionError,
)
from .vault_config import VaultConfig, VaultConfigError

__all__ = [
    # Protocols
    "TokenStore",
    "GroupStore",
    # Exceptions - Storage
    "StorageError",
    "StorageUnavailableError",
    # Exceptions - Vault Config
    "VaultConfigError",
    # Exceptions - Vault Client
    "VaultError",
    "VaultConnectionError",
    "VaultAuthenticationError",
    "VaultNotFoundError",
    "VaultPermissionError",
    # Exceptions - Factory
    "FactoryError",
    # Vault
    "VaultConfig",
    "VaultClient",
    "VaultTokenStore",
    "VaultGroupStore",
    # Factory functions
    "create_token_store",
    "create_group_store",
    "create_stores_from_env",
    "create_vault_client_from_env",
    "BackendType",
]
