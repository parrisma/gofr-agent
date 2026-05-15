"""Vault configuration for token/group storage.

Defines connection settings for HashiCorp Vault KV v2 backend.
Supports both token-based and AppRole authentication.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


class VaultConfigError(Exception):
    """Raised when Vault configuration is invalid."""
    pass


@dataclass
class VaultConfig:
    """Configuration for connecting to HashiCorp Vault.

    Supports two authentication methods:
    1. Token authentication: Set `token` directly
    2. AppRole authentication: Set both `role_id` and `secret_id`

    Example:
        # Token auth
        config = VaultConfig(
            url="https://vault.example.com:8200",
            token="hvs.xxxxx",
        )

        # AppRole auth
        config = VaultConfig(
            url="https://vault.example.com:8200",
            role_id="xxx-xxx-xxx",
            secret_id="yyy-yyy-yyy",
        )

        # From environment variables
        config = VaultConfig.from_env("GOFR_DIG")

    Attributes:
        url: Vault server URL (e.g., "https://vault.example.com:8200")
        token: Vault token for token-based authentication
        role_id: AppRole role ID for AppRole authentication
        secret_id: AppRole secret ID for AppRole authentication
        mount_point: KV v2 secrets engine mount point (default: "secret")
        path_prefix: Path prefix for all secrets (default: "gofr/auth")
        timeout: Connection timeout in seconds (default: 30)
        namespace: Vault namespace (for Vault Enterprise)
        verify_ssl: Whether to verify SSL certificates (default: True)
    """

    url: str
    token: Optional[str] = None
    role_id: Optional[str] = None
    secret_id: Optional[str] = None
    mount_point: str = "secret"
    path_prefix: str = "gofr/auth"
    timeout: int = 30
    namespace: Optional[str] = None
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Strip trailing slash from URL
        self.url = self.url.rstrip("/")

    @classmethod
    def from_env(cls, prefix: str = "GOFR") -> "VaultConfig":
        """Create VaultConfig from environment variables.

        Environment variables:
            {PREFIX}_VAULT_URL: Vault server URL (required)
            {PREFIX}_VAULT_TOKEN: Vault token (optional)
            {PREFIX}_VAULT_ROLE_ID: AppRole role ID (optional)
            {PREFIX}_VAULT_SECRET_ID: AppRole secret ID (optional)
            {PREFIX}_VAULT_MOUNT: KV mount point (default: "secret")
            {PREFIX}_VAULT_PATH_PREFIX: Path prefix (default: "gofr/auth")
            {PREFIX}_VAULT_TIMEOUT: Connection timeout (default: 30)
            {PREFIX}_VAULT_NAMESPACE: Vault namespace (optional)
            {PREFIX}_VAULT_VERIFY_SSL: SSL verification (default: "true")

        Args:
            prefix: Environment variable prefix (e.g., "GOFR_DIG")

        Returns:
            VaultConfig instance

        Raises:
            VaultConfigError: If required environment variables are missing
        """
        prefix = prefix.upper().replace("-", "_")

        url = os.environ.get(f"{prefix}_VAULT_URL")
        if not url:
            raise VaultConfigError(
                f"Missing required environment variable: {prefix}_VAULT_URL"
            )

        # Parse SSL verification
        verify_ssl_str = os.environ.get(f"{prefix}_VAULT_VERIFY_SSL", "true")
        verify_ssl = verify_ssl_str.lower() in ("true", "1", "yes")

        # Parse timeout
        timeout_str = os.environ.get(f"{prefix}_VAULT_TIMEOUT", "30")
        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 30

        return cls(
            url=url,
            token=os.environ.get(f"{prefix}_VAULT_TOKEN"),
            role_id=os.environ.get(f"{prefix}_VAULT_ROLE_ID"),
            secret_id=os.environ.get(f"{prefix}_VAULT_SECRET_ID"),
            mount_point=os.environ.get(f"{prefix}_VAULT_MOUNT", "secret"),
            path_prefix=os.environ.get(f"{prefix}_VAULT_PATH_PREFIX", "gofr/auth"),
            timeout=timeout,
            namespace=os.environ.get(f"{prefix}_VAULT_NAMESPACE"),
            verify_ssl=verify_ssl,
        )

    def validate(self) -> None:
        """Validate configuration is complete and usable.

        Raises:
            VaultConfigError: If configuration is invalid
        """
        # URL is required
        if not self.url:
            raise VaultConfigError("Vault URL is required")

        # URL must be http or https
        if not self.url.startswith(("http://", "https://")):
            raise VaultConfigError(
                f"Vault URL must start with http:// or https://, got: {self.url}"
            )

        # Must have either token OR (role_id AND secret_id)
        has_token = bool(self.token)
        has_approle = bool(self.role_id and self.secret_id)

        if not has_token and not has_approle:
            raise VaultConfigError(
                "Must provide either 'token' or both 'role_id' and 'secret_id' for authentication"
            )

        if has_token and has_approle:
            raise VaultConfigError(
                "Provide either 'token' or 'role_id/secret_id', not both"
            )

        # If partial AppRole config, that's an error
        if bool(self.role_id) != bool(self.secret_id):
            raise VaultConfigError(
                "AppRole auth requires both 'role_id' and 'secret_id'"
            )

        # Timeout must be positive
        if self.timeout <= 0:
            raise VaultConfigError(f"Timeout must be positive, got: {self.timeout}")

    @property
    def auth_method(self) -> str:
        """Return the authentication method based on configuration.

        Returns:
            "token" or "approle"
        """
        if self.token:
            return "token"
        return "approle"

    @property
    def tokens_path(self) -> str:
        """Return the full path for token storage.

        Returns:
            Path like "gofr/auth/tokens"
        """
        return f"{self.path_prefix}/tokens"

    @property
    def groups_path(self) -> str:
        """Return the full path for group storage.

        Returns:
            Path like "gofr/auth/groups"
        """
        return f"{self.path_prefix}/groups"
