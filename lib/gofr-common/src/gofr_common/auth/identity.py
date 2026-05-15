"""
Vault Runtime Identity
======================
Handles AppRole-based authentication for runtime services.

Applications use this class to authenticate to Vault using injected credentials,
without ever touching the Root Token.
"""

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from .backends.vault_client import VaultClient, VaultError
from .backends.vault_config import VaultConfig

# Standard injection path (same in Dev bind-mount and Prod Docker Secrets)
DEFAULT_CREDS_PATH = "/run/secrets/vault_creds"


class VaultIdentityError(VaultError):
    """Raised when identity operations fail."""

    pass


class VaultIdentity:
    """Runtime identity for Vault AppRole authentication.

    Handles:
    - Loading credentials from injected file
    - AppRole login to obtain Client Token
    - Background token renewal
    - Graceful shutdown

    Example:
        identity = VaultIdentity()
        identity.login()

        # Get authenticated client for secret access
        client = identity.get_client()
        secret = client.read_secret("services/mcp/config")

        # On shutdown
        identity.stop()
    """

    def __init__(
        self,
        creds_path: str = DEFAULT_CREDS_PATH,
        vault_addr: Optional[str] = None,
        renewal_threshold: float = 0.75,  # Renew when 75% of TTL elapsed
    ):
        """Initialize identity loader.

        Args:
            creds_path: Path to credentials JSON file (role_id, secret_id)
            vault_addr: Vault server address (defaults to VAULT_ADDR env or localhost)
            renewal_threshold: Fraction of TTL at which to trigger renewal
        """
        self.creds_path = Path(creds_path)
        self.vault_addr = vault_addr or self._get_vault_addr()
        self.renewal_threshold = renewal_threshold

        self._client: Optional[VaultClient] = None
        self._token: Optional[str] = None
        self._token_ttl: int = 0
        self._renewal_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _get_vault_addr(self) -> str:
        """Get Vault address from environment."""
        import os

        return os.getenv("VAULT_ADDR", "http://gofr-vault:8201")

    def _load_credentials(self) -> Dict[str, str]:
        """Load AppRole credentials from injected file."""
        if not self.creds_path.exists():
            raise VaultIdentityError(
                f"Credentials not found at {self.creds_path}. "
                "Ensure the container has the secret mounted."
            )

        try:
            with open(self.creds_path) as f:
                creds = json.load(f)

            if "role_id" not in creds or "secret_id" not in creds:
                raise VaultIdentityError("Invalid credentials file: missing role_id or secret_id")

            return creds
        except json.JSONDecodeError as e:
            raise VaultIdentityError(f"Invalid JSON in credentials file: {e}")

    def login(self) -> "VaultIdentity":
        """Authenticate to Vault using AppRole.

        Returns:
            self for chaining

        Raises:
            VaultIdentityError: If login fails
        """
        creds = self._load_credentials()

        try:
            # Create config for AppRole auth (VaultConfig infers method from role_id/secret_id)
            config = VaultConfig(
                url=self.vault_addr,
                role_id=creds["role_id"],
                secret_id=creds["secret_id"],
            )

            # VaultClient handles the actual login
            self._client = VaultClient(config)

            # Get token info for renewal scheduling
            token_info = self._client._client.auth.token.lookup_self()
            self._token_ttl = token_info["data"].get("ttl", 3600)

            return self

        except Exception as e:
            raise VaultIdentityError(f"AppRole login failed: {e}") from e

    def start_renewal(self) -> "VaultIdentity":
        """Start background token renewal thread.

        Returns:
            self for chaining
        """
        if self._client is None:
            raise VaultIdentityError("Must call login() before start_renewal()")

        self._stop_event.clear()
        self._renewal_thread = threading.Thread(
            target=self._renewal_loop, daemon=True, name="vault-token-renewal"
        )
        self._renewal_thread.start()
        return self

    def _renewal_loop(self) -> None:
        """Background loop to renew token before expiry."""
        import logging

        log = logging.getLogger("vault-identity")

        while not self._stop_event.is_set():
            # Calculate sleep time (renew at threshold of TTL)
            sleep_time = max(self._token_ttl * self.renewal_threshold, 30)

            # Wait (interruptible)
            if self._stop_event.wait(timeout=sleep_time):
                break  # Stop event set

            # Attempt renewal
            try:
                if self._client:
                    self._client._client.auth.token.renew_self()
                    # Refresh TTL info
                    token_info = self._client._client.auth.token.lookup_self()
                    self._token_ttl = token_info["data"].get("ttl", 3600)
                    log.debug(f"Vault token renewed, new TTL: {self._token_ttl}s")
            except Exception as e:
                # Log failure but don't crash - next iteration will retry
                log.warning(f"Vault token renewal failed: {e}")

    def stop(self) -> None:
        """Stop the renewal thread gracefully."""
        self._stop_event.set()
        if self._renewal_thread and self._renewal_thread.is_alive():
            self._renewal_thread.join(timeout=5)

    def get_client(self) -> VaultClient:
        """Get the authenticated VaultClient.

        Returns:
            Authenticated VaultClient instance

        Raises:
            VaultIdentityError: If not logged in
        """
        if self._client is None:
            raise VaultIdentityError("Not logged in. Call login() first.")
        return self._client

    @staticmethod
    def is_available(creds_path: str = DEFAULT_CREDS_PATH) -> bool:
        """Check if AppRole credentials are available.

        Use this to determine auth strategy at startup.
        """
        return Path(creds_path).exists()

    def __enter__(self) -> "VaultIdentity":
        """Context manager entry."""
        self.login()
        self.start_renewal()
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit."""
        self.stop()
