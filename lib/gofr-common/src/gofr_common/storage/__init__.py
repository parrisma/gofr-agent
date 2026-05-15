"""Storage module for GOFR services

Provides generic blob storage with metadata and group-based access control.
"""

from .base import StorageBase
from .exceptions import (
    InvalidFormatError,
    PermissionDeniedError,
    ResourceNotFoundError,
    StorageError,
)
from .file_storage import FileStorage
from .metadata import BlobMetadata

__all__ = [
    "StorageBase",
    "FileStorage",
    "StorageError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "InvalidFormatError",
    "BlobMetadata",
]
