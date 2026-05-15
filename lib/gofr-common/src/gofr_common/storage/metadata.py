"""Metadata repository for blob storage

Separates metadata management from blob storage for better separation of concerns.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Use standard logging if gofr_common logger not available
try:
    from gofr_common.logger import get_logger
    logger = get_logger("storage.metadata")
except ImportError:
    logger = logging.getLogger("storage.metadata")


class BlobMetadata:
    """Immutable blob metadata"""

    def __init__(
        self,
        guid: str,
        format: str,
        size: int,
        created_at: str,
        group: Optional[str] = None,
        **kwargs,
    ):
        self.guid = guid
        self.format = format
        self.size = size
        self.created_at = created_at
        self.group = group
        self.extra = kwargs  # Additional metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        data = {
            "format": self.format,
            "size": self.size,
            "created_at": self.created_at,
        }
        if self.group is not None:
            data["group"] = self.group
        if self.extra:
            data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, guid: str, data: Dict[str, Any]) -> "BlobMetadata":
        """Create from dictionary representation"""
        return cls(
            guid=guid,
            format=data.get("format", "bin"),
            size=data.get("size", 0),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            group=data.get("group"),
            **{k: v for k, v in data.items() if k not in ["format", "size", "created_at", "group"]},
        )

    def __repr__(self) -> str:
        return f"BlobMetadata(guid={self.guid}, format={self.format}, size={self.size}, group={self.group})"


class MetadataRepository(ABC):
    """Abstract base class for metadata storage"""

    @abstractmethod
    def save(self, metadata: BlobMetadata) -> None:
        """Save metadata"""
        pass

    @abstractmethod
    def get(self, guid: str) -> Optional[BlobMetadata]:
        """Get metadata by GUID"""
        pass

    @abstractmethod
    def delete(self, guid: str) -> bool:
        """Delete metadata by GUID"""
        pass

    @abstractmethod
    def list_all(self, group: Optional[str] = None) -> List[str]:
        """List all GUIDs, optionally filtered by group"""
        pass

    @abstractmethod
    def exists(self, guid: str) -> bool:
        """Check if metadata exists"""
        pass

    @abstractmethod
    def filter_by_age(self, age_days: int, group: Optional[str] = None) -> List[BlobMetadata]:
        """Get metadata for blobs older than specified age"""
        pass


class JsonMetadataRepository(MetadataRepository):
    """JSON file-based metadata repository"""

    def __init__(self, metadata_file: Path):
        """
        Initialize JSON metadata repository

        Args:
            metadata_file: Path to JSON file
        """
        self.metadata_file = metadata_file
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Ensure metadata file exists"""
        if not self.metadata_file.exists():
            self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.metadata_file, "w") as f:
                json.dump({}, f)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """Load metadata from file"""
        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_all(self, data: Dict[str, Dict[str, Any]]) -> None:
        """Save all metadata to file"""
        with open(self.metadata_file, "w") as f:
            json.dump(data, f, indent=2)

    def save(self, metadata: BlobMetadata) -> None:
        """Save metadata"""
        data = self._load()
        data[metadata.guid] = metadata.to_dict()
        self._save_all(data)

    def get(self, guid: str) -> Optional[BlobMetadata]:
        """Get metadata by GUID"""
        data = self._load()
        if guid in data:
            return BlobMetadata.from_dict(guid, data[guid])
        return None

    def delete(self, guid: str) -> bool:
        """Delete metadata by GUID"""
        data = self._load()
        if guid in data:
            del data[guid]
            self._save_all(data)
            return True
        return False

    def list_all(self, group: Optional[str] = None) -> List[str]:
        """List all GUIDs, optionally filtered by group"""
        data = self._load()
        if group is None:
            return list(data.keys())

        return [
            guid for guid, meta in data.items()
            if meta.get("group") == group
        ]

    def exists(self, guid: str) -> bool:
        """Check if metadata exists"""
        data = self._load()
        return guid in data

    def filter_by_age(self, age_days: int, group: Optional[str] = None) -> List[BlobMetadata]:
        """Get metadata for blobs older than specified age"""
        data = self._load()
        result = []
        now = datetime.utcnow()

        for guid, meta_dict in data.items():
            # Filter by group if specified
            if group is not None and meta_dict.get("group") != group:
                continue

            # Check age
            try:
                created_at = datetime.fromisoformat(meta_dict.get("created_at", ""))
                age = (now - created_at).days
                if age >= age_days:
                    result.append(BlobMetadata.from_dict(guid, meta_dict))
            except (ValueError, TypeError):
                continue

        return result
