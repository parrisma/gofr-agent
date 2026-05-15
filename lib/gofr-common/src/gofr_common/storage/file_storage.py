"""File-based storage implementation

Uses separate metadata and blob repositories for better separation of concerns.
"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import StorageBase
from .blob import FileBlobRepository
from .exceptions import PermissionDeniedError
from .metadata import BlobMetadata, JsonMetadataRepository

# Use standard logging if gofr_common logger not available
try:
    from gofr_common.logger import get_logger
    logger = get_logger("storage.file")
except ImportError:
    logger = logging.getLogger("storage.file")


class FileStorage(StorageBase):
    """
    File-based blob storage using separate metadata and blob repositories

    This implementation provides better separation of concerns by splitting
    metadata management from binary data storage.
    """

    def __init__(self, storage_dir: str | Path):
        """
        Initialize file storage with separate repositories

        Args:
            storage_dir: Directory to store blobs and metadata
        """
        storage_path = Path(storage_dir)

        # Initialize repositories
        self.metadata_repo = JsonMetadataRepository(storage_path / "metadata.json")
        self.blob_repo = FileBlobRepository(storage_path)

        # Alias maps: group -> alias -> guid, guid -> alias
        self._alias_to_guid: Dict[str, Dict[str, str]] = {}
        self._guid_to_alias: Dict[str, str] = {}
        self._rebuild_alias_maps()

        logger.info(f"FileStorage initialized at {storage_path}")

    def save(
        self, data: bytes, format: str, group: Optional[str] = None, **kwargs
    ) -> str:
        """
        Save data using separate metadata and blob repositories

        Args:
            data: Raw bytes
            format: Format/extension (png, json, txt, etc.)
            group: Optional group name for access control
            **kwargs: Additional metadata

        Returns:
            GUID string (identifier without extension)

        Raises:
            RuntimeError: If save fails
        """
        guid = str(uuid.uuid4())

        logger.debug(f"Saving blob {guid} ({format}, {len(data)} bytes, group={group})")

        try:
            # Save blob first
            self.blob_repo.save(guid, data, format.lower())

            # Then save metadata
            metadata = BlobMetadata(
                guid=guid,
                format=format.lower(),
                size=len(data),
                created_at=datetime.utcnow().isoformat(),
                group=group,
                **kwargs
            )
            self.metadata_repo.save(metadata)

            logger.info(f"Blob saved: {guid}")
            return guid

        except Exception as e:
            # Cleanup blob if metadata save fails
            try:
                self.blob_repo.delete(guid, format.lower())
            except Exception:
                pass
            logger.error(f"Failed to save blob {guid}: {e}")
            raise RuntimeError(f"Failed to save blob: {str(e)}")

    def get(
        self, identifier: str, group: Optional[str] = None
    ) -> Optional[Tuple[bytes, str]]:
        """
        Retrieve data by GUID

        Args:
            identifier: GUID string (without extension)
            group: Optional group name for access control

        Returns:
            Tuple of (data_bytes, format) or None if not found

        Raises:
            ValueError: If GUID format is invalid
            PermissionDeniedError: If group mismatch
        """
        # Resolve alias if needed
        guid = self.resolve_guid(identifier)
        if not guid:
            # If not an alias, check if it's a valid GUID
            try:
                uuid.UUID(identifier)
                guid = identifier
            except ValueError:
                logger.warning(f"Invalid identifier format: {identifier}")
                return None

        # Get metadata
        metadata = self.metadata_repo.get(guid)

        # Check group access
        if metadata:
            if group is not None and metadata.group is not None and metadata.group != group:
                logger.warning(f"Group mismatch for {guid}: requested={group}, stored={metadata.group}")
                raise PermissionDeniedError(
                    f"Access denied: blob belongs to group '{metadata.group}', not '{group}'"
                )

        logger.debug(f"Retrieving blob {guid} (group={group})")

        # Try metadata format first, then fallback to detection
        if metadata:
            blob_data = self.blob_repo.get(guid, metadata.format)
            if blob_data:
                logger.info(f"Blob retrieved: {guid} ({metadata.format})")
                return (blob_data, metadata.format)

        # Fallback: try to detect format
        detected_format = self.blob_repo.get_format(guid)
        if detected_format:
            blob_data = self.blob_repo.get(guid, detected_format)
            if blob_data:
                logger.info(f"Blob retrieved (format detected): {guid} ({detected_format})")
                return (blob_data, detected_format)

        logger.warning(f"Blob not found: {guid}")
        return None

    def delete(self, identifier: str, group: Optional[str] = None) -> bool:
        """
        Delete blob by GUID

        Args:
            identifier: GUID string (without extension)
            group: Optional group name for access control

        Returns:
            True if deleted, False if not found

        Raises:
            PermissionDeniedError: If group mismatch
        """
        # Resolve alias if needed
        guid = self.resolve_guid(identifier)
        if not guid:
            try:
                uuid.UUID(identifier)
                guid = identifier
            except ValueError:
                return False

        # Get metadata
        metadata = self.metadata_repo.get(guid)

        # Check group access
        if metadata:
            if group is not None and metadata.group is not None and metadata.group != group:
                logger.warning(f"Group mismatch for deletion {guid}: requested={group}, stored={metadata.group}")
                raise PermissionDeniedError(
                    f"Access denied: blob belongs to group '{metadata.group}', not '{group}'"
                )

        # Delete blob
        blob_deleted = self.blob_repo.delete(guid, metadata.format if metadata else None)

        # Delete metadata
        meta_deleted = self.metadata_repo.delete(guid)

        # Remove from alias maps
        if guid in self._guid_to_alias:
            self._guid_to_alias[guid]
            del self._guid_to_alias[guid]
            # We don't easily know the group for the alias map without iterating,
            # but rebuild will fix it eventually. For now, just rebuild.
            self._rebuild_alias_maps()

        return blob_deleted or meta_deleted

    def list(self, group: Optional[str] = None) -> List[str]:
        """
        List all stored GUIDs

        Args:
            group: Optional group name to filter by

        Returns:
            List of GUID strings
        """
        return self.metadata_repo.list_all(group)

    def exists(self, identifier: str, group: Optional[str] = None) -> bool:
        """
        Check if a blob exists

        Args:
            identifier: GUID string
            group: Optional group name for access control

        Returns:
            True if exists, False otherwise
        """
        # Resolve alias if needed
        guid = self.resolve_guid(identifier)
        if not guid:
            try:
                uuid.UUID(identifier)
                guid = identifier
            except ValueError:
                return False

        # Check metadata first
        if self.metadata_repo.exists(guid):
            # Check group if needed
            if group:
                metadata = self.metadata_repo.get(guid)
                if metadata and metadata.group != group:
                    return False
            return True

        # Fallback to blob check
        return self.blob_repo.exists(guid)

    def purge(self, age_days: int = 0, group: Optional[str] = None) -> int:
        """
        Delete blobs older than specified age

        Args:
            age_days: Minimum age in days (0 to delete all)
            group: Optional group name to filter by

        Returns:
            Number of blobs deleted
        """
        if age_days < 0:
            raise ValueError("Age must be non-negative")

        to_delete = self.metadata_repo.filter_by_age(age_days, group)
        count = 0

        for metadata in to_delete:
            try:
                self.delete(metadata.guid, group)  # Pass group to verify permission
                count += 1
            except Exception as e:
                logger.error(f"Failed to purge blob {metadata.guid}: {e}")

        logger.info(f"Purged {count} blobs older than {age_days} days (group={group})")
        return count

    def register_alias(self, alias: str, guid: str, group: str) -> None:
        """
        Register an alias for a GUID

        Args:
            alias: Alias string
            guid: GUID to associate with alias
            group: Group name (required for aliases)
        """
        if not alias or not re.match(r"^[a-zA-Z0-9_-]+$", alias):
            raise ValueError("Alias must be alphanumeric (hyphens and underscores allowed)")

        # Check if alias already exists for this group
        if group in self._alias_to_guid and alias in self._alias_to_guid[group]:
            existing_guid = self._alias_to_guid[group][alias]
            if existing_guid != guid:
                raise ValueError(f"Alias '{alias}' already exists for group '{group}'")

        # Store in metadata (using extra fields)
        metadata = self.metadata_repo.get(guid)
        if not metadata:
            raise ValueError(f"GUID {guid} not found")

        if metadata.group != group:
            raise PermissionDeniedError(f"GUID {guid} does not belong to group {group}")

        # Update metadata with alias
        # We store aliases in a list in metadata to support multiple aliases per blob
        aliases = metadata.extra.get("aliases", [])
        if alias not in aliases:
            aliases.append(alias)
            metadata.extra["aliases"] = aliases
            self.metadata_repo.save(metadata)

        # Update in-memory maps
        self._rebuild_alias_maps()

    def get_alias(self, guid: str) -> Optional[str]:
        """
        Get alias for a GUID

        Args:
            guid: GUID string

        Returns:
            Alias string or None
        """
        return self._guid_to_alias.get(guid)

    def resolve_guid(self, identifier: str) -> Optional[str]:
        """
        Resolve an alias or GUID to a GUID

        Args:
            identifier: Alias or GUID string

        Returns:
            GUID string if found, None otherwise
        """
        # Check if it's a known alias (in any group - this might be ambiguous if aliases aren't unique globally)
        # For now, we'll search all groups. In a real system, we might need group context here.
        for group_aliases in self._alias_to_guid.values():
            if identifier in group_aliases:
                return group_aliases[identifier]

        # If not an alias, return as is (caller will validate if it's a GUID)
        return identifier

    def _rebuild_alias_maps(self) -> None:
        """Rebuild in-memory alias maps from metadata"""
        self._alias_to_guid = {}
        self._guid_to_alias = {}

        # Iterate all metadata
        # Note: This could be slow for large datasets. In production, use a database.
        all_guids = self.metadata_repo.list_all()

        for guid in all_guids:
            metadata = self.metadata_repo.get(guid)
            if metadata and "aliases" in metadata.extra:
                group = metadata.group or "default"

                if group not in self._alias_to_guid:
                    self._alias_to_guid[group] = {}

                for alias in metadata.extra["aliases"]:
                    self._alias_to_guid[group][alias] = guid
                    self._guid_to_alias[guid] = alias  # Last one wins for reverse lookup
