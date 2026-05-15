"""Vault client wrapper for KV v2 secrets engine.

Provides a thin wrapper around the hvac client with:
- Token and AppRole authentication
- KV v2 read/write/list/delete operations
- Error handling and custom exceptions
- Health checking and reconnection
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from gofr_common.logger import Logger, create_logger


class Forbidden(Exception):
    """Placeholder Forbidden error when hvac is unavailable."""


class InvalidPath(Exception):
    """Placeholder InvalidPath error when hvac is unavailable."""


class InvalidRequest(Exception):
    """Placeholder InvalidRequest error when hvac is unavailable."""


class HvacVaultError(Exception):
    """Placeholder VaultError when hvac is unavailable."""


try:
    import hvac
    from hvac import exceptions as hvac_exceptions

    Forbidden = hvac_exceptions.Forbidden  # type: ignore[assignment]
    InvalidPath = hvac_exceptions.InvalidPath  # type: ignore[assignment]
    InvalidRequest = hvac_exceptions.InvalidRequest  # type: ignore[assignment]
    HvacVaultError = hvac_exceptions.VaultError  # type: ignore[assignment]
except ImportError:
    hvac = None  # type: ignore[assignment]


if TYPE_CHECKING:
    from .vault_config import VaultConfig


class VaultError(Exception):
    """Base exception for Vault operations."""
    pass


class VaultConnectionError(VaultError):
    """Raised when unable to connect to Vault server."""
    pass


class VaultAuthenticationError(VaultError):
    """Raised when authentication to Vault fails."""
    pass


class VaultNotFoundError(VaultError):
    """Raised when a secret path is not found."""
    pass


class VaultPermissionError(VaultError):
    """Raised when permission is denied for an operation."""
    pass


class VaultClient:
    """Wrapper around hvac client for Vault KV v2 operations.

    Handles authentication (token or AppRole) and provides simplified
    methods for reading, writing, listing, and deleting secrets.

    Example:
        config = VaultConfig(
            url="https://vault.example.com:8200",
            token="hvs.xxxxx",
        )
        client = VaultClient(config)

        # Write a secret
        client.write_secret("myapp/config", {"key": "value"})

        # Read a secret
        data = client.read_secret("myapp/config")

        # List secrets
        keys = client.list_secrets("myapp")

        # Delete a secret
        client.delete_secret("myapp/config")
    """

    def __init__(
        self,
        config: "VaultConfig",
        logger: Optional[Logger] = None,
    ) -> None:
        """Initialize Vault client.

        Args:
            config: VaultConfig with connection settings
            logger: Optional logger instance

        Raises:
            ImportError: If hvac is not installed
            VaultConfigError: If config is invalid
        """
        # Allow patched hvac during tests even if dependency is not installed.
        if hvac is None:
            raise ImportError(
                "hvac is required for Vault integration. "
                "Install with: pip install gofr-common[vault]"
            )

        self.config = config
        self.logger = logger or create_logger(name="vault-client")

        # Validate config before proceeding
        config.validate()

        # Create hvac client
        self._client: hvac.Client = hvac.Client(  # type: ignore[union-attr]
            url=config.url,
            token=config.token if config.auth_method == "token" else None,
            namespace=config.namespace,
            verify=config.verify_ssl,
            timeout=config.timeout,
        )

        # Authenticate if using AppRole
        if config.auth_method == "approle":
            self._authenticate_approle()

        self.logger.debug(
            "VaultClient initialized",
            url=config.url,
            auth_method=config.auth_method,
            mount_point=config.mount_point,
        )

    def _authenticate_approle(self) -> None:
        """Authenticate using AppRole credentials.

        Raises:
            VaultAuthenticationError: If authentication fails
        """
        try:
            response = self._client.auth.approle.login(
                role_id=self.config.role_id,
                secret_id=self.config.secret_id,
            )
            self._client.token = response["auth"]["client_token"]
            self.logger.info("Authenticated to Vault via AppRole")
        except Exception as e:
            self.logger.error("AppRole authentication failed", error=str(e))
            raise VaultAuthenticationError(f"AppRole authentication failed: {e}") from e

    def is_authenticated(self) -> bool:
        """Check if client is authenticated.

        Returns:
            True if authenticated and token is valid
        """
        try:
            return self._client.is_authenticated()
        except Exception:
            return False

    def health_check(self) -> bool:
        """Check if Vault server is healthy and accessible.

        Returns:
            True if Vault is healthy and unsealed
        """
        try:
            self._client.sys.read_health_status(method="GET")
            # Health returns different codes for different states
            # 200 = initialized, unsealed, active
            # We just check we can reach it and it responds
            return True
        except Exception as e:
            self.logger.warning("Vault health check failed", error=str(e))
            return False

    def reconnect(self) -> None:
        """Reconnect and re-authenticate to Vault.

        Useful after network issues or token expiration.

        Raises:
            VaultAuthenticationError: If re-authentication fails
        """
        self.logger.info("Reconnecting to Vault")

        # Re-create client
        self._client = hvac.Client(  # type: ignore[union-attr]
            url=self.config.url,
            token=self.config.token if self.config.auth_method == "token" else None,
            namespace=self.config.namespace,
            verify=self.config.verify_ssl,
            timeout=self.config.timeout,
        )

        # Re-authenticate if using AppRole
        if self.config.auth_method == "approle":
            self._authenticate_approle()

        self.logger.info("Reconnected to Vault")

    def read_secret(self, path: str) -> Optional[Dict[str, Any]]:
        """Read a secret from KV v2.

        Args:
            path: Secret path (relative to mount point)

        Returns:
            Secret data dict, or None if not found

        Raises:
            VaultConnectionError: If unable to connect
            VaultPermissionError: If permission denied
        """
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.config.mount_point,
                raise_on_deleted_version=True,
            )
            if response and "data" in response and "data" in response["data"]:
                return response["data"]["data"]
            return None
        except InvalidPath:
            self.logger.debug("Secret not found", path=path)
            return None
        except Forbidden as e:
            self.logger.error("Permission denied reading secret", path=path)
            raise VaultPermissionError(f"Permission denied: {path}") from e
        except Exception as e:
            self.logger.error("Failed to read secret", path=path, error=str(e))
            raise VaultConnectionError(f"Failed to read secret: {e}") from e

    def write_secret(self, path: str, data: Dict[str, Any]) -> None:
        """Write a secret to KV v2.

        Args:
            path: Secret path (relative to mount point)
            data: Secret data to write

        Raises:
            VaultConnectionError: If unable to connect
            VaultPermissionError: If permission denied
        """
        try:
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self.config.mount_point,
            )
            self.logger.debug("Secret written", path=path)
        except Forbidden as e:
            self.logger.error("Permission denied writing secret", path=path)
            raise VaultPermissionError(f"Permission denied: {path}") from e
        except Exception as e:
            self.logger.error("Failed to write secret", path=path, error=str(e))
            raise VaultConnectionError(f"Failed to write secret: {e}") from e

    def delete_secret(self, path: str, hard: bool = False) -> bool:
        """Delete a secret from KV v2.

        Args:
            path: Secret path (relative to mount point)
            hard: If True, permanently delete all versions and metadata.
                  If False (default), soft delete (can be recovered with undelete).

        Returns:
            True if deleted, False if not found

        Raises:
            VaultConnectionError: If unable to connect
            VaultPermissionError: If permission denied
        """
        try:
            if hard:
                self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=path,
                    mount_point=self.config.mount_point,
                )
            else:
                self._client.secrets.kv.v2.delete_latest_version_of_secret(
                    path=path,
                    mount_point=self.config.mount_point,
                )
            self.logger.debug("Secret deleted", path=path, hard=hard)
            return True
        except InvalidPath:
            self.logger.debug("Secret not found for deletion", path=path)
            return False
        except Forbidden as e:
            self.logger.error("Permission denied deleting secret", path=path)
            raise VaultPermissionError(f"Permission denied: {path}") from e
        except Exception as e:
            self.logger.error("Failed to delete secret", path=path, error=str(e))
            raise VaultConnectionError(f"Failed to delete secret: {e}") from e

    def list_secrets(self, path: str) -> List[str]:
        """List secret keys at a path.

        Args:
            path: Path to list (relative to mount point)

        Returns:
            List of secret keys (names), empty if path doesn't exist

        Raises:
            VaultConnectionError: If unable to connect
            VaultPermissionError: If permission denied
        """
        try:
            response = self._client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point=self.config.mount_point,
            )
            if response and "data" in response and "keys" in response["data"]:
                return response["data"]["keys"]
            return []
        except InvalidPath:
            self.logger.debug("Path not found for listing", path=path)
            return []
        except Forbidden as e:
            self.logger.error("Permission denied listing secrets", path=path)
            raise VaultPermissionError(f"Permission denied: {path}") from e
        except Exception as e:
            self.logger.error("Failed to list secrets", path=path, error=str(e))
            raise VaultConnectionError(f"Failed to list secrets: {e}") from e

    def secret_exists(self, path: str) -> bool:
        """Check if a secret exists at the given path.

        Args:
            path: Secret path (relative to mount point)

        Returns:
            True if secret exists
        """
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.config.mount_point,
                raise_on_deleted_version=True,
            )
            return response is not None
        except InvalidPath:
            return False
        except Exception:
            return False
