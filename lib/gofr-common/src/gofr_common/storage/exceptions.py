"""Storage exceptions"""

class StorageError(Exception):
    """Base class for storage exceptions"""
    pass

class PermissionDeniedError(StorageError):
    """Raised when access to a resource is denied"""
    pass

class ResourceNotFoundError(StorageError):
    """Raised when a resource is not found"""
    pass

class InvalidFormatError(StorageError):
    """Raised when the format is invalid"""
    pass
