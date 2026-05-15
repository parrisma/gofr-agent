"""
Vault Bootstrap Operations
==========================
Centralized Vault initialization, unsealing, and health check operations.

This module provides shared functionality for all GOFR services that use Vault.
Zero-Trust Bootstrap: All credentials stored in secrets/ or Vault only.

Usage:
    from gofr_common.vault.bootstrap import VaultBootstrap

    bootstrap = VaultBootstrap(vault_addr="http://gofr-vault:8201")

    # Check and unseal if needed
    if bootstrap.ensure_unsealed(unseal_key):
        pass  # Vault ready

    # Full initialization (first time only)
    if bootstrap.is_uninitialized():
        creds = bootstrap.initialize()
        bootstrap.save_credentials(creds, secrets_dir)
"""

import json
import logging
import os
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

try:
    from gofr_common.logger import get_logger

    logger = get_logger("vault.bootstrap")
except Exception:  # pragma: no cover
    logger = logging.getLogger("vault.bootstrap")


@dataclass
class VaultCredentials:
    """Vault initialization credentials."""
    root_token: str
    unseal_key: str

    def to_dict(self) -> dict:
        return {
            "root_token": self.root_token,
            "unseal_key": self.unseal_key
        }


class VaultBootstrap:
    """Centralized Vault bootstrap operations for GOFR services."""

    # Vault health status codes
    STATUS_HEALTHY = 200
    STATUS_STANDBY = 429
    STATUS_NOT_INITIALIZED = 501
    STATUS_SEALED = 503

    def __init__(
        self,
        vault_addr: Optional[str] = None,
        timeout: int = 10
    ):
        """Initialize VaultBootstrap.

        Args:
            vault_addr: Vault server URL (default: from VAULT_ADDR env or http://gofr-vault:8201)
            timeout: HTTP request timeout in seconds
        """
        self.vault_addr = vault_addr or os.getenv("VAULT_ADDR", "http://gofr-vault:8201")
        self.timeout = timeout

    def get_status(self) -> dict:
        """Get Vault health status.

        Returns:
            dict with status information including:
                - http_code: HTTP status code
                - initialized: bool
                - sealed: bool
                - error: Optional error message
        """
        try:
            req = urllib.request.Request(
                f"{self.vault_addr}/v1/sys/health",
                method='GET'
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read())
                    return {
                        "http_code": resp.status,
                        "initialized": data.get("initialized", False),
                        "sealed": data.get("sealed", False),
                        "error": None
                    }
            except urllib.error.HTTPError as e:
                # Vault uses HTTP errors for status
                try:
                    data = json.loads(e.read())
                    return {
                        "http_code": e.code,
                        "initialized": data.get("initialized", e.code != 501),
                        "sealed": data.get("sealed", e.code == 503),
                        "error": None
                    }
                except Exception:
                    return {
                        "http_code": e.code,
                        "initialized": e.code != 501,
                        "sealed": e.code == 503,
                        "error": str(e)
                    }
        except Exception as e:
            return {
                "http_code": 0,
                "initialized": False,
                "sealed": True,
                "error": str(e)
            }

    def is_healthy(self) -> bool:
        """Check if Vault is initialized and unsealed."""
        status = self.get_status()
        return status["http_code"] in (self.STATUS_HEALTHY, self.STATUS_STANDBY)

    def is_sealed(self) -> bool:
        """Check if Vault is sealed."""
        status = self.get_status()
        return status["http_code"] == self.STATUS_SEALED

    def is_uninitialized(self) -> bool:
        """Check if Vault needs initialization."""
        status = self.get_status()
        return status["http_code"] == self.STATUS_NOT_INITIALIZED

    def wait_for_ready(self, max_attempts: int = 30, delay: float = 1.0) -> bool:
        """Wait for Vault to be reachable.

        Args:
            max_attempts: Maximum number of attempts
            delay: Delay between attempts in seconds

        Returns:
            True if Vault became reachable, False otherwise
        """
        import time

        for _ in range(max_attempts):
            status = self.get_status()
            if status["http_code"] != 0:
                return True
            time.sleep(delay)
        return False

    def initialize(
        self,
        secret_shares: int = 1,
        secret_threshold: int = 1
    ) -> VaultCredentials:
        """Initialize Vault and return credentials.

        Args:
            secret_shares: Number of unseal key shares
            secret_threshold: Number of shares required to unseal

        Returns:
            VaultCredentials with root_token and unseal_key

        Raises:
            RuntimeError: If initialization fails
        """
        data = json.dumps({
            "secret_shares": secret_shares,
            "secret_threshold": secret_threshold
        }).encode()

        req = urllib.request.Request(
            f"{self.vault_addr}/v1/sys/init",
            data=data,
            headers={"Content-Type": "application/json"},
            method='PUT'
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                return VaultCredentials(
                    root_token=result["root_token"],
                    unseal_key=result["keys"][0]
                )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Vault: {e}")

    def unseal(self, unseal_key: str) -> bool:
        """Unseal Vault with the given key.

        Args:
            unseal_key: The unseal key

        Returns:
            True if unsealed successfully, False otherwise
        """
        data = json.dumps({"key": unseal_key}).encode()

        req = urllib.request.Request(
            f"{self.vault_addr}/v1/sys/unseal",
            data=data,
            headers={"Content-Type": "application/json"},
            method='PUT'
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read())
                return not result.get("sealed", True)
        except Exception:
            return False

    def ensure_unsealed(self, unseal_key: Optional[str] = None) -> bool:
        """Ensure Vault is unsealed, unsealing if necessary.

        Args:
            unseal_key: The unseal key (required if Vault is sealed)

        Returns:
            True if Vault is unsealed (or became unsealed), False otherwise
        """
        status = self.get_status()

        if status["http_code"] in (self.STATUS_HEALTHY, self.STATUS_STANDBY):
            return True

        if status["http_code"] == self.STATUS_SEALED:
            if unseal_key:
                return self.unseal(unseal_key)
            return False

        # Not initialized or not reachable
        return False

    def save_credentials(
        self,
        creds: VaultCredentials,
        secrets_dir: Path,
        permissions: int = 0o600
    ) -> None:
        """Save Vault credentials to secure storage.

        Args:
            creds: VaultCredentials to save
            secrets_dir: Directory to save credentials (will be created with 0700)
            permissions: File permissions for credential files (default: 0600)
        """
        # Ensure secrets directory exists with strict permissions
        secrets_dir.mkdir(parents=True, exist_ok=True)
        secrets_dir.chmod(stat.S_IRWXU)  # 0700

        # Write root token
        token_file = secrets_dir / "vault_root_token"
        token_file.write_text(creds.root_token.strip())
        token_file.chmod(permissions)

        # Write unseal key
        key_file = secrets_dir / "vault_unseal_key"
        key_file.write_text(creds.unseal_key.strip())
        key_file.chmod(permissions)

    def load_credentials(self, secrets_dir: Path) -> Optional[VaultCredentials]:
        """Load Vault credentials from secure storage.

        Args:
            secrets_dir: Directory containing credential files

        Returns:
            VaultCredentials if found, None otherwise
        """
        token_file = secrets_dir / "vault_root_token"
        key_file = secrets_dir / "vault_unseal_key"

        if not token_file.exists() or not key_file.exists():
            return None

        return VaultCredentials(
            root_token=token_file.read_text().strip(),
            unseal_key=key_file.read_text().strip()
        )

    def auto_init_and_unseal(
        self,
        secrets_dir: Path,
        force_init: bool = False,
        validate_token: bool = False,
        vault_url: Optional[str] = None,
    ) -> Tuple[bool, Optional[VaultCredentials]]:
        """Automatically initialize and/or unseal Vault.

        This is the main entry point for Zero-Trust Bootstrap.

        Args:
            secrets_dir: Directory for storing/loading credentials
            force_init: If True, initialize even if already initialized

        Returns:
            Tuple of (success: bool, credentials: Optional[VaultCredentials])
        """
        if vault_url:
            self.vault_addr = vault_url

        # Wait for Vault to be reachable
        if not self.wait_for_ready():
            return False, None

        status = self.get_status()
        creds = None

        # Handle uninitialized Vault
        if status["http_code"] == self.STATUS_NOT_INITIALIZED or force_init:
            logger.info("Initializing Vault")
            creds = self.initialize()
            self.save_credentials(creds, secrets_dir)
            logger.info("Vault initialized; credentials saved", extra={"secrets_dir": str(secrets_dir)})

            # Unseal the newly initialized Vault
            if self.unseal(creds.unseal_key):
                logger.info("Vault unsealed")
                return True, creds
            else:
                logger.error("Failed to unseal Vault after initialization")
                return False, creds

        # Handle sealed Vault
        if status["http_code"] == self.STATUS_SEALED:
            # Try to load existing credentials
            creds = self.load_credentials(secrets_dir)
            if not creds:
                logger.error(
                    "Vault is sealed but no credentials found",
                    extra={"secrets_dir": str(secrets_dir)},
                )
                return False, None

            logger.info("Unsealing Vault")
            if self.unseal(creds.unseal_key):
                logger.info("Vault unsealed")
                return True, creds
            else:
                logger.error("Failed to unseal Vault")
                return False, creds

        # Already healthy
        if status["http_code"] in (self.STATUS_HEALTHY, self.STATUS_STANDBY):
            # Load credentials if they exist
            creds = self.load_credentials(secrets_dir)
            logger.info("Vault is already initialized and unsealed")

            if validate_token and creds:
                if not self._token_valid(creds.root_token):
                    logger.error(
                        "Vault is healthy but loaded root token is invalid; refusing to report success",
                        extra={"secrets_dir": str(secrets_dir)},
                    )
                    return False, creds
            return True, creds

        logger.error("Vault not reachable", extra={"status": status})
        return False, None

    def _token_valid(self, token: str) -> bool:
        token = (token or "").strip()
        if not token:
            return False

        req = urllib.request.Request(
            f"{self.vault_addr}/v1/auth/token/lookup-self",
            headers={"X-Vault-Token": token},
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                _ = resp.read()
                return resp.status == 200
        except urllib.error.HTTPError:
            return False
        except Exception:
            return False


# Convenience function for shell scripts
def ensure_vault_ready(
    vault_addr: Optional[str] = None,
    secrets_dir: Optional[Path] = None,
    auto_init: bool = False
) -> bool:
    """Ensure Vault is ready for use.

    This is the main entry point for scripts that need Vault.

    Args:
        vault_addr: Vault server URL
        secrets_dir: Directory for credentials (default: ./secrets)
        auto_init: If True, initialize Vault if needed

    Returns:
        True if Vault is ready, False otherwise
    """
    if secrets_dir is None:
        secrets_dir = Path.cwd() / "secrets"

    bootstrap = VaultBootstrap(vault_addr)

    if auto_init:
        success, _ = bootstrap.auto_init_and_unseal(secrets_dir)
        return success
    else:
        # Just try to unseal with existing credentials
        creds = bootstrap.load_credentials(secrets_dir)
        if creds:
            return bootstrap.ensure_unsealed(creds.unseal_key)
        return bootstrap.is_healthy()
