"""Blob repository for generic storage

Handles raw binary data storage separately from metadata.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

# Use standard logging if gofr_common logger not available
try:
    from gofr_common.logger import get_logger
    logger = get_logger("storage.blob")
except ImportError:
    logger = logging.getLogger("storage.blob")


class BlobRepository(ABC):
    """Abstract base class for blob storage"""

    @abstractmethod
    def save(self, guid: str, data: bytes, format: str) -> None:
        """Save blob data"""
        pass

    @abstractmethod
    def get(self, guid: str, format: str) -> Optional[bytes]:
        """Get blob data by GUID and format"""
        pass

    @abstractmethod
    def delete(self, guid: str, format: Optional[str] = None) -> bool:
        """Delete blob by GUID (all formats if format not specified)"""
        pass

    @abstractmethod
    def exists(self, guid: str, format: Optional[str] = None) -> bool:
        """Check if blob exists (any format if format not specified)"""
        pass

    @abstractmethod
    def list_all(self) -> List[str]:
        """List all blob GUIDs"""
        pass

    @abstractmethod
    def get_format(self, guid: str) -> Optional[str]:
        """Try to detect format for a GUID"""
        pass


class FileBlobRepository(BlobRepository):
    """File-based blob storage"""

    def __init__(self, storage_dir: Path):
        """
        Initialize file blob repository

        Args:
            storage_dir: Directory to store blob files
        """
        self.storage_dir = storage_dir

        # Create storage directory if it doesn't exist
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Blob storage initialized at {self.storage_dir}")
        except Exception as e:
            logger.error(f"Failed to create storage directory: {e}")
            raise RuntimeError(f"Failed to create storage directory: {str(e)}")

    def _get_filepath(self, guid: str, format: str) -> Path:
        """Get file path for a blob"""
        return self.storage_dir / f"{guid}.{format.lower()}"

    def save(self, guid: str, data: bytes, format: str) -> None:
        """Save blob data to file"""
        filepath = self._get_filepath(guid, format)

        try:
            with open(filepath, "wb") as f:
                f.write(data)
            logger.debug(f"Blob saved: {guid}.{format} ({len(data)} bytes)")
        except Exception as e:
            logger.error(f"Failed to save blob {guid}: {e}")
            raise RuntimeError(f"Failed to save blob: {str(e)}")

    def get(self, guid: str, format: str) -> Optional[bytes]:
        """Get blob data from file"""
        filepath = self._get_filepath(guid, format)

        if filepath.exists():
            try:
                with open(filepath, "rb") as f:
                    data = f.read()
                logger.debug(f"Blob retrieved: {guid}.{format} ({len(data)} bytes)")
                return data
            except Exception as e:
                logger.error(f"Failed to read blob {guid}: {e}")
                raise RuntimeError(f"Failed to read blob: {str(e)}")

        return None

    def delete(self, guid: str, format: Optional[str] = None) -> bool:
        """Delete blob file(s)"""
        deleted = False

        if format:
            # Delete specific format
            filepath = self._get_filepath(guid, format)
            if filepath.exists():
                try:
                    filepath.unlink()
                    deleted = True
                    logger.debug(f"Blob deleted: {guid}.{format}")
                except Exception as e:
                    logger.error(f"Failed to delete blob {guid}: {e}")
        else:
            # Delete all files starting with guid
            for filepath in self.storage_dir.glob(f"{guid}.*"):
                try:
                    filepath.unlink()
                    deleted = True
                    logger.debug(f"Blob deleted: {filepath.name}")
                except Exception as e:
                    logger.error(f"Failed to delete blob file {filepath.name}: {e}")

        return deleted

    def exists(self, guid: str, format: Optional[str] = None) -> bool:
        """Check if blob exists"""
        if format:
            return self._get_filepath(guid, format).exists()

        # Check for any file starting with guid
        return any(self.storage_dir.glob(f"{guid}.*"))

    def list_all(self) -> List[str]:
        """List all blob GUIDs"""
        guids = set()
        for filepath in self.storage_dir.glob("*.*"):
            if filepath.is_file():
                guids.add(filepath.stem)
        return list(guids)

    def get_format(self, guid: str) -> Optional[str]:
        """Try to detect format for a GUID"""
        # Look for any file with this GUID
        for filepath in self.storage_dir.glob(f"{guid}.*"):
            if filepath.is_file():
                # Return extension without dot
                return filepath.suffix.lstrip(".").lower()
        return None
