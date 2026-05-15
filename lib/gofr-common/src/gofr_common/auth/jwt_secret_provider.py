"""JWT Secret Provider -- single accessor for the JWT signing secret.

Reads from Vault with a configurable TTL cache.  All Python consumers
(servers, CLI tools, tests) use this class instead of reading the secret
directly from env vars or Vault.

Thread-safe: the cached value is protected by a lock so the provider
can be shared across async/threaded servers.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional

from gofr_common.logger import Logger, create_logger

from .backends import VaultClient


class JwtSecretProvider:
    """Provides the JWT signing secret with time-based cache refresh from Vault."""

    def __init__(
        self,
        vault_client: VaultClient,
        vault_path: str = "gofr/config/jwt-signing-secret",
        cache_ttl_seconds: int = 300,
        logger: Optional[Logger] = None,
    ) -> None:
        """Initialise the provider.

        Args:
            vault_client: Authenticated VaultClient instance.
            vault_path: KV v2 path where the secret is stored.
                        The secret must have a ``value`` key.
            cache_ttl_seconds: How long (seconds) to cache the secret
                               before re-reading from Vault.  Default 300 (5 min).
            logger: Optional structured logger.
        """
        self._vault_client = vault_client
        self._vault_path = vault_path
        self._cache_ttl = cache_ttl_seconds

        if logger is not None:
            self._logger = logger
        else:
            self._logger = create_logger(name="jwt-secret-provider")

        self._lock = threading.Lock()
        self._cached_secret: Optional[str] = None
        self._cache_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self) -> str:
        """Return the current JWT secret, re-reading from Vault if the cache has expired.

        Raises:
            RuntimeError: If Vault does not contain a valid secret at the configured path.
        """
        with self._lock:
            now = time.monotonic()
            if self._cached_secret is not None and now < self._cache_expires_at:
                return self._cached_secret

            # Cache miss or expired -- read from Vault
            secret_data = self._vault_client.read_secret(self._vault_path)
            if not secret_data or "value" not in secret_data:
                raise RuntimeError(
                    f"JWT secret not found at Vault path '{self._vault_path}' "
                    f"or missing 'value' key"
                )

            new_secret: str = secret_data["value"]

            # Detect rotation
            if self._cached_secret is not None and new_secret != self._cached_secret:
                old_fp = self._fingerprint(self._cached_secret)
                new_fp = self._fingerprint(new_secret)
                self._logger.warning(
                    "JWT signing secret rotated in Vault",
                    old_fingerprint=old_fp,
                    new_fingerprint=new_fp,
                    vault_path=self._vault_path,
                )

            self._cached_secret = new_secret
            self._cache_expires_at = now + self._cache_ttl

            self._logger.debug(
                "JWT secret loaded from Vault",
                fingerprint=self._fingerprint(new_secret),
                ttl_seconds=self._cache_ttl,
            )

            return self._cached_secret

    @property
    def fingerprint(self) -> str:
        """SHA-256 fingerprint of the currently cached secret.

        Calls ``get()`` if there is no cached value yet, so this is
        never stale relative to the TTL.
        """
        secret = self.get()
        return self._fingerprint(secret)

    def invalidate(self) -> None:
        """Force the next ``get()`` call to re-read from Vault."""
        with self._lock:
            self._cache_expires_at = 0.0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(secret: str) -> str:
        digest = hashlib.sha256(secret.encode()).hexdigest()
        return f"sha256:{digest[:12]}"
