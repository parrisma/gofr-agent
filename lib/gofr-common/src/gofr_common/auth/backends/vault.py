"""Vault-backed storage backends.

Provides HashiCorp Vault storage for tokens and groups using KV v2 secrets engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional

from gofr_common.logger import Logger, create_logger

from ..tokens import TokenRecord
from .base import StorageUnavailableError
from .vault_client import VaultClient, VaultConnectionError

if TYPE_CHECKING:
    from ..groups import Group


# Default cache TTL in seconds (5 minutes)
DEFAULT_CACHE_TTL = 300

# Maximum time between full reloads (1 hour) - ensures expired tokens are swept
MAX_RELOAD_INTERVAL = 3600


@dataclass
class _CacheEntry:
    """Cache entry with timestamp for TTL checking."""
    record: Optional[TokenRecord]
    timestamp: float = field(default_factory=time.monotonic)

    def is_expired(self, ttl: float) -> bool:
        """Check if entry has exceeded TTL."""
        return (time.monotonic() - self.timestamp) > ttl


class VaultTokenStore:
    """Vault-backed token storage backend.

    Stores tokens in HashiCorp Vault KV v2 secrets engine.
    Each token is stored as a separate secret at {path_prefix}/tokens/{token_id}.

    Example:
        client = VaultClient(config)
        store = VaultTokenStore(client)
        store.put("uuid-1", token_record)
        record = store.get("uuid-1")
    """

    def __init__(
        self,
        client: VaultClient,
        path_prefix: str = "gofr/auth",
        logger: Optional[Logger] = None,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        """Initialize Vault-backed token store.

        Args:
            client: VaultClient instance for Vault operations
            path_prefix: Base path in Vault for storing tokens
            logger: Optional logger instance
            cache_ttl: Cache TTL in seconds (default: 5 minutes). Set to 0 to disable.
        """
        self.client = client
        self.path_prefix = path_prefix.rstrip("/")
        self.logger = logger or create_logger(name="vault-token-store")
        self._tokens_path = f"{self.path_prefix}/tokens"

        # TTL-based cache for token lookups
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._last_full_reload: float = 0.0

        self.logger.debug(
            "VaultTokenStore initialized",
            path_prefix=self.path_prefix,
            tokens_path=self._tokens_path,
            cache_ttl=cache_ttl,
        )

    def _token_path(self, token_id: str) -> str:
        """Get full Vault path for a token.

        Args:
            token_id: UUID string of the token

        Returns:
            Full path in Vault KV store
        """
        return f"{self._tokens_path}/{token_id}"

    def _get_from_cache(self, token_id: str) -> Optional[_CacheEntry]:
        """Get token from cache if valid.

        Returns:
            Cache entry if found and not expired, None otherwise
        """
        if self._cache_ttl <= 0:
            return None
        entry = self._cache.get(token_id)
        if entry and not entry.is_expired(self._cache_ttl):
            return entry
        return None

    def _put_in_cache(self, token_id: str, record: Optional[TokenRecord]) -> None:
        """Store token in cache."""
        if self._cache_ttl > 0:
            self._cache[token_id] = _CacheEntry(record=record)

    def _invalidate_cache(self, token_id: str) -> None:
        """Remove token from cache."""
        self._cache.pop(token_id, None)

    def _check_periodic_reload(self) -> None:
        """Trigger reload if max interval exceeded (ensures expiration sweep)."""
        now = time.monotonic()
        if (now - self._last_full_reload) > MAX_RELOAD_INTERVAL:
            self.logger.debug("Periodic cache reload triggered")
            self.reload()

    def get(self, token_id: str, bypass_cache: bool = False) -> Optional[TokenRecord]:
        """Retrieve a token record by ID.

        Args:
            token_id: UUID string of the token
            bypass_cache: If True, skip cache and query Vault directly

        Returns:
            TokenRecord if found, None otherwise

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        # Check periodic reload for expiration sweep
        self._check_periodic_reload()

        # Check cache first (unless bypassed)
        if not bypass_cache:
            cached = self._get_from_cache(token_id)
            if cached is not None:
                self.logger.debug("Cache hit", token_id=token_id)
                return cached.record

        # Query Vault
        try:
            data = self.client.read_secret(self._token_path(token_id))
            record = TokenRecord.from_dict(data) if data else None

            # Update cache
            self._put_in_cache(token_id, record)

            if record:
                self.logger.debug("Fetched from Vault", token_id=token_id)
            return record
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def get_by_name(self, name: str) -> Optional[TokenRecord]:
        """Retrieve a token record by name.

        Performs a linear scan over tokens. An indexed lookup can be added later
        if needed for larger datasets.
        """
        try:
            keys = self.client.list_secrets(self._tokens_path)
            for key in keys:
                if key.endswith("/"):
                    continue
                data = self.client.read_secret(self._token_path(key))
                if data and data.get("name") == name:
                    return TokenRecord.from_dict(data)
            return None
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def put(self, token_id: str, record: TokenRecord) -> None:
        """Store or update a token record.

        Args:
            token_id: UUID string of the token
            record: TokenRecord to store

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            self.client.write_secret(self._token_path(token_id), record.to_dict())
            # Update cache with new record
            self._put_in_cache(token_id, record)
            self.logger.debug("Token stored in Vault", token_id=token_id)
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def delete(self, token_id: str) -> bool:
        """Delete a token from Vault.

        Note: This performs a soft delete in Vault (marks versions as deleted).
        The secret can still be recovered using Vault's undelete.

        Args:
            token_id: UUID string of the token

        Returns:
            True if deleted, False if not found

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            result = self.client.delete_secret(self._token_path(token_id))
            # Invalidate cache entry
            self._invalidate_cache(token_id)
            if result:
                self.logger.debug("Token deleted from Vault", token_id=token_id)
            return result
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def list_all(self) -> Dict[str, TokenRecord]:
        """List all token records.

        Returns:
            Dictionary mapping token_id to TokenRecord

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            # List all token keys
            keys = self.client.list_secrets(self._tokens_path)

            # Fetch each token
            result: Dict[str, TokenRecord] = {}
            for key in keys:
                # Keys may have trailing slash for directories, skip those
                if key.endswith("/"):
                    continue
                data = self.client.read_secret(self._token_path(key))
                if data:
                    result[key] = TokenRecord.from_dict(data)

            return result
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def exists(self, token_id: str, retry_on_miss: bool = True) -> bool:
        """Check if a token exists.

        Args:
            token_id: UUID string of the token
            retry_on_miss: If True and token not found, invalidate cache and retry once.
                          This handles the case where a token was created externally.

        Returns:
            True if token exists, False otherwise

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        # Check periodic reload
        self._check_periodic_reload()

        # Check cache first
        cached = self._get_from_cache(token_id)
        if cached is not None:
            return cached.record is not None

        # Query Vault
        try:
            exists = self.client.secret_exists(self._token_path(token_id))

            if not exists and retry_on_miss:
                # Token not found - might be newly created externally
                # Invalidate any stale cache and do a direct Vault query
                self._invalidate_cache(token_id)
                self.logger.debug("Token not found, retrying after cache invalidation", token_id=token_id)

                # Direct query bypassing any potential connection caching
                record = self.get(token_id, bypass_cache=True)
                exists = record is not None

                if exists:
                    self.logger.info("Token found on retry (likely newly created)", token_id=token_id)

            # Cache the result (get() already cached if we did the retry)
            if not retry_on_miss or not exists:
                # Only cache if we didn't already via get()
                pass  # get() handles caching

            return exists
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def exists_name(self, name: str) -> bool:
        """Check if a token exists by name."""
        return self.get_by_name(name) is not None

    def reload(self) -> None:
        """Reload all tokens from Vault, refreshing the local cache.

        This clears the local cache and updates the last reload timestamp.
        Subsequent get/exists calls will fetch fresh data from Vault.
        """
        self._cache.clear()
        self._last_full_reload = time.monotonic()
        self.logger.debug("Cache cleared, full reload triggered")

    def clear(self) -> None:
        """Delete all tokens from Vault.

        Warning: This permanently deletes ALL tokens in the path prefix.

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            keys = self.client.list_secrets(self._tokens_path)
            for key in keys:
                if not key.endswith("/"):
                    self.client.delete_secret(self._token_path(key), hard=True)
            # Clear the local cache as well
            self._cache.clear()
            self.logger.info("All tokens cleared from Vault")
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def __len__(self) -> int:
        """Return number of tokens in store.

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            keys = self.client.list_secrets(self._tokens_path)
            return len([k for k in keys if not k.endswith("/")])
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e


class VaultGroupStore:
    """Vault-backed group storage backend.

    Stores groups in HashiCorp Vault KV v2 secrets engine.
    Each group is stored as a separate secret at {path_prefix}/groups/{group_id}.
    A name index is maintained at {path_prefix}/groups/_index/names for fast lookups.

    Example:
        client = VaultClient(config)
        store = VaultGroupStore(client)
        store.put("uuid-1", group)
        group = store.get_by_name("admin")
    """

    def __init__(
        self,
        client: VaultClient,
        path_prefix: str = "gofr/auth",
        logger: Optional[Logger] = None,
    ) -> None:
        """Initialize Vault-backed group store.

        Args:
            client: VaultClient instance for Vault operations
            path_prefix: Base path in Vault for storing groups
            logger: Optional logger instance
        """
        self.client = client
        self.path_prefix = path_prefix.rstrip("/")
        self.logger = logger or create_logger(name="vault-group-store")
        self._groups_path = f"{self.path_prefix}/groups"
        self._index_path = f"{self._groups_path}/_index/names"

        self.logger.debug(
            "VaultGroupStore initialized",
            path_prefix=self.path_prefix,
            groups_path=self._groups_path,
        )

    def _group_path(self, group_id: str) -> str:
        """Get full Vault path for a group.

        Args:
            group_id: UUID string of the group

        Returns:
            Full path in Vault KV store
        """
        return f"{self._groups_path}/{group_id}"

    def _load_name_index(self) -> Dict[str, str]:
        """Load the name->id index from Vault.

        Returns:
            Dictionary mapping group name to group_id
        """
        try:
            data = self.client.read_secret(self._index_path)
            if data is None:
                return {}
            return data
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed loading index", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def _save_name_index(self, index: Dict[str, str]) -> None:
        """Save the name->id index to Vault.

        Args:
            index: Dictionary mapping group name to group_id
        """
        try:
            self.client.write_secret(self._index_path, index)
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed saving index", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def get(self, group_id: str) -> Optional["Group"]:
        """Retrieve a group by ID.

        Args:
            group_id: UUID string of the group

        Returns:
            Group if found, None otherwise

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        # Late import to avoid circular dependency
        from ..groups import Group

        try:
            data = self.client.read_secret(self._group_path(group_id))
            if data is None:
                return None
            return Group.from_dict(data)
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def get_by_name(self, name: str) -> Optional["Group"]:
        """Retrieve a group by name.

        Uses the name index for efficient lookup.

        Args:
            name: Name of the group

        Returns:
            Group if found, None otherwise

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        index = self._load_name_index()
        group_id = index.get(name)
        if group_id is None:
            return None
        return self.get(group_id)

    def put(self, group_id: str, group: "Group") -> None:
        """Store or update a group.

        Also updates the name index.

        Args:
            group_id: UUID string of the group
            group: Group to store

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            # Get current group to check for name change
            old_group = self.get(group_id)

            # Write the group
            self.client.write_secret(self._group_path(group_id), group.to_dict())
            self.logger.debug("Group stored in Vault", group_id=group_id, name=group.name)

            # Update name index
            index = self._load_name_index()

            # Remove old name if it changed
            if old_group and old_group.name != group.name:
                index.pop(old_group.name, None)

            index[group.name] = group_id
            self._save_name_index(index)

        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def delete(self, group_id: str) -> bool:
        """Delete a group from Vault.

        Also removes from name index.

        Args:
            group_id: UUID string of the group

        Returns:
            True if deleted, False if not found

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            # Get group to find its name for index removal
            group = self.get(group_id)

            result = self.client.delete_secret(self._group_path(group_id))
            if result and group:
                # Remove from name index
                index = self._load_name_index()
                index.pop(group.name, None)
                self._save_name_index(index)
                self.logger.debug("Group deleted from Vault", group_id=group_id)
            return result
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def list_all(self) -> Dict[str, "Group"]:
        """List all groups.

        Returns:
            Dictionary mapping group_id to Group

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        # Late import to avoid circular dependency
        from ..groups import Group

        try:
            keys = self.client.list_secrets(self._groups_path)

            result: Dict[str, "Group"] = {}
            for key in keys:
                # Skip directories and index
                if key.endswith("/") or key == "_index":
                    continue
                data = self.client.read_secret(self._group_path(key))
                if data:
                    result[key] = Group.from_dict(data)

            return result
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def exists(self, group_id: str) -> bool:
        """Check if a group exists.

        Args:
            group_id: UUID string of the group

        Returns:
            True if group exists, False otherwise

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            return self.client.secret_exists(self._group_path(group_id))
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def reload(self) -> None:
        """Reload data from Vault.

        For Vault backend, this is a no-op since we don't cache locally.
        Each operation queries Vault directly.
        """
        self.logger.debug("Reload called (no-op for Vault backend)")

    def clear(self) -> None:
        """Delete all groups from Vault.

        Warning: This permanently deletes ALL groups in the path prefix.

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            keys = self.client.list_secrets(self._groups_path)
            for key in keys:
                if not key.endswith("/") and key != "_index":
                    self.client.delete_secret(self._group_path(key), hard=True)
            # Clear the name index
            self.client.delete_secret(self._index_path, hard=True)
            self.logger.info("All groups cleared from Vault")
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e

    def __len__(self) -> int:
        """Return number of groups in store.

        Raises:
            StorageUnavailableError: If Vault is unreachable
        """
        try:
            keys = self.client.list_secrets(self._groups_path)
            return len([k for k in keys if not k.endswith("/") and k != "_index"])
        except VaultConnectionError as e:
            self.logger.error("Vault connection failed", error=str(e))
            raise StorageUnavailableError(f"Vault unavailable: {e}") from e
