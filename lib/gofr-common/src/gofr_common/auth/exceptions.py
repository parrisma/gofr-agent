"""Authentication exceptions with consistent hierarchy.

All auth exceptions inherit from AuthError which includes an HTTP status code
for easy conversion to HTTPException in middleware.

Hierarchy:
    AuthError (401)
    ├── TokenError (401)
    │   ├── TokenNotFoundError (401)
    │   ├── TokenRevokedError (401)
    │   ├── TokenExpiredError (401)
    │   └── TokenValidationError (401)
    ├── GroupError (403)
    │   ├── InvalidGroupError (403)
    │   ├── GroupNotFoundError (403)
    │   └── GroupAccessDeniedError (403)
    └── AuthenticationError (401)
        └── FingerprintMismatchError (401)
"""


class AuthError(Exception):
    """Base exception for all authentication errors.

    Includes HTTP status code for easy conversion to HTTPException.
    Default status code is 401 (Unauthorized).
    """

    status_code: int = 401
    default_message: str = "Authentication error"

    def __init__(self, message: str | None = None):
        """Initialize the exception.

        Args:
            message: Error message. Uses default_message if not provided.
        """
        self.message = message or self.default_message
        super().__init__(self.message)


# =============================================================================
# Token Errors (401)
# =============================================================================


class TokenError(AuthError):
    """Base exception for token-related errors."""

    default_message = "Token error"


class TokenNotFoundError(TokenError):
    """Raised when a token is not found in the store."""

    default_message = "Token not found in store"


class TokenRevokedError(TokenError):
    """Raised when a token has been revoked."""

    default_message = "Token has been revoked"


class TokenExpiredError(TokenError):
    """Raised when a token has expired."""

    default_message = "Token has expired"


class TokenValidationError(TokenError):
    """Raised when token validation fails (invalid signature, claims, etc)."""

    default_message = "Token validation failed"


class TokenServiceError(TokenError):
    """Base exception for token service operation errors."""

    default_message = "Token service error"


# =============================================================================
# Group Errors (403)
# =============================================================================


class GroupError(AuthError):
    """Base exception for group-related errors."""

    status_code = 403
    default_message = "Group access error"


class InvalidGroupError(GroupError):
    """Raised when token references an invalid or defunct group."""

    default_message = "Invalid or defunct group"


class GroupNotFoundError(GroupError):
    """Raised when a group is not found."""

    default_message = "Group not found"


class GroupAccessDeniedError(GroupError):
    """Raised when user doesn't have required group membership."""

    default_message = "Group access denied"


# =============================================================================
# Authentication Errors (401)
# =============================================================================


class AuthenticationError(AuthError):
    """Base exception for authentication failures."""

    default_message = "Authentication failed"


class FingerprintMismatchError(AuthenticationError):
    """Raised when token fingerprint doesn't match request."""

    default_message = "Token fingerprint mismatch - possible token theft"


# =============================================================================
# Backward Compatibility
# =============================================================================

# For backward compatibility with existing code that imports from token_service
# These are aliased here so both import paths work
__all__ = [
    # Base
    "AuthError",
    # Token errors
    "TokenError",
    "TokenNotFoundError",
    "TokenRevokedError",
    "TokenExpiredError",
    "TokenValidationError",
    "TokenServiceError",
    # Group errors
    "GroupError",
    "InvalidGroupError",
    "GroupNotFoundError",
    "GroupAccessDeniedError",
    # Auth errors
    "AuthenticationError",
    "FingerprintMismatchError",
]
