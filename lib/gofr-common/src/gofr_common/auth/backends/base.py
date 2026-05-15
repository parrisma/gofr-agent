"""Base protocols for storage backends.

Defines the abstract interfaces that all storage backends must implement.
Uses Python's Protocol for structural subtyping (duck typing with type hints).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Protocol, runtime_checkable

from ..tokens import TokenRecord

if TYPE_CHECKING:
    from ..groups import Group


class StorageError(Exception):
    """Base exception for storage backend errors."""
    pass


class StorageUnavailableError(StorageError):
    """Raised when storage backend is unavailable."""
    pass


@runtime_checkable
class TokenStore(Protocol):
    """Protocol for token storage backends.

    All token storage implementations must provide these methods.
    Tokens are keyed by their UUID string.

    Example:
        class MyTokenStore:
            def get(self, token_id: str) -> Optional[TokenRecord]:
                ...
            def put(self, token_id: str, record: TokenRecord) -> None:
                ...
            # ... other methods

        # MyTokenStore is a valid TokenStore due to structural subtyping
        store: TokenStore = MyTokenStore()
    """

    def get(self, token_id: str) -> Optional[TokenRecord]:
        """Retrieve a token record by ID.

        Args:
            token_id: UUID string of the token

        Returns:
            TokenRecord if found, None otherwise
        """
        ...

    def put(self, token_id: str, record: TokenRecord) -> None:
        """Store or update a token record.

        Args:
            token_id: UUID string of the token
            record: TokenRecord to store
        """
        ...

    def list_all(self) -> Dict[str, TokenRecord]:
        """List all token records.

        Returns:
            Dictionary mapping token_id to TokenRecord
        """
        ...

    def get_by_name(self, name: str) -> Optional[TokenRecord]:
        """Retrieve a token record by its friendly name.

        Args:
            name: Name of the token

        Returns:
            TokenRecord if found, None otherwise
        """
        ...

    def exists(self, token_id: str) -> bool:
        """Check if a token exists.

        Args:
            token_id: UUID string of the token

        Returns:
            True if token exists, False otherwise
        """
        ...

    def exists_name(self, name: str) -> bool:
        """Check if a token exists by name.

        Args:
            name: Name of the token

        Returns:
            True if token with this name exists, False otherwise
        """
        ...

    def reload(self) -> None:
        """Reload data from underlying storage.

        For Vault stores, clears any local cache.
        """
        ...


@runtime_checkable
class GroupStore(Protocol):
    """Protocol for group storage backends.

    All group storage implementations must provide these methods.
    Groups are keyed by their UUID string.

    Example:
        class MyGroupStore:
            def get(self, group_id: str) -> Optional[Group]:
                ...
            # ... other methods

        store: GroupStore = MyGroupStore()
    """

    def get(self, group_id: str) -> Optional[Group]:
        """Retrieve a group by ID.

        Args:
            group_id: UUID string of the group

        Returns:
            Group if found, None otherwise
        """
        ...

    def get_by_name(self, name: str) -> Optional[Group]:
        """Retrieve a group by name.

        Args:
            name: Name of the group

        Returns:
            Group if found, None otherwise
        """
        ...

    def put(self, group_id: str, group: Group) -> None:
        """Store or update a group.

        Args:
            group_id: UUID string of the group
            group: Group to store
        """
        ...

    def list_all(self) -> Dict[str, Group]:
        """List all groups.

        Returns:
            Dictionary mapping group_id to Group
        """
        ...

    def exists(self, group_id: str) -> bool:
        """Check if a group exists.

        Args:
            group_id: UUID string of the group

        Returns:
            True if group exists, False otherwise
        """
        ...

    def reload(self) -> None:
        """Reload data from underlying storage.

        For Vault stores, clears any local cache.
        """
        ...
