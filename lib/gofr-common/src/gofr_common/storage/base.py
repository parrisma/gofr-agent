"""Base storage interface

Defines the abstract interface that all storage implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class StorageBase(ABC):
    """Abstract base class for blob storage implementations"""

    @abstractmethod
    def save(
        self, data: bytes, format: str, group: Optional[str] = None, **kwargs
    ) -> str:
        """
        Save data and return a unique identifier

        Args:
            data: Raw bytes to store
            format: Format/extension of the data (e.g., 'png', 'json', 'txt')
            group: Optional group name for access control
            **kwargs: Additional metadata to store

        Returns:
            Unique identifier (GUID) for the saved blob

        Raises:
            StorageError: If save fails
        """
        pass

    @abstractmethod
    def get(
        self, identifier: str, group: Optional[str] = None
    ) -> Optional[Tuple[bytes, str]]:
        """
        Retrieve data by identifier

        Args:
            identifier: Unique identifier for the blob
            group: Optional group name for access control

        Returns:
            Tuple of (data_bytes, format) or None if not found

        Raises:
            PermissionDeniedError: If group mismatch
            StorageError: If retrieval fails
        """
        pass

    @abstractmethod
    def delete(self, identifier: str, group: Optional[str] = None) -> bool:
        """
        Delete blob by identifier

        Args:
            identifier: Unique identifier for the blob
            group: Optional group name for access control

        Returns:
            True if deleted, False if not found

        Raises:
            PermissionDeniedError: If group mismatch
        """
        pass

    @abstractmethod
    def list(self, group: Optional[str] = None) -> List[str]:
        """
        List all stored identifiers

        Args:
            group: Optional group name to filter by

        Returns:
            List of identifier strings
        """
        pass

    @abstractmethod
    def exists(self, identifier: str, group: Optional[str] = None) -> bool:
        """
        Check if a blob exists

        Args:
            identifier: Unique identifier
            group: Optional group name for access control

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    def purge(self, age_days: int = 0, group: Optional[str] = None) -> int:
        """
        Delete blobs older than specified age

        Args:
            age_days: Minimum age in days (0 to delete all)
            group: Optional group name to filter by

        Returns:
            Number of blobs deleted
        """
        pass

    @abstractmethod
    def register_alias(self, alias: str, guid: str, group: str) -> None:
        """
        Register an alias for a GUID

        Args:
            alias: Alias string
            guid: GUID to associate with alias
            group: Group name (required for aliases)
        """
        pass

    @abstractmethod
    def get_alias(self, guid: str) -> Optional[str]:
        """
        Get alias for a GUID

        Args:
            guid: GUID string

        Returns:
            Alias string or None
        """
        pass

    @abstractmethod
    def resolve_guid(self, identifier: str) -> Optional[str]:
        """
        Resolve an alias or GUID to a GUID

        Args:
            identifier: Alias or GUID string

        Returns:
            GUID string if found, None otherwise
        """
        pass
