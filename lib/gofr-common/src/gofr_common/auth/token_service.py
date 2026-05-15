"""Token Service for JWT operations.

Provides a focused service for JWT token creation, verification, and revocation.
Separated from group management for single responsibility.

This is a lower-level service. For most use cases, prefer using AuthService
which provides group validation and a higher-level API.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

import jwt

from gofr_common.logger import Logger, create_logger

from .backends import TokenStore
from .exceptions import (
    FingerprintMismatchError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenRevokedError,
    TokenServiceError,
    TokenValidationError,
)
from .tokens import TokenInfo, TokenRecord

if TYPE_CHECKING:
    from .jwt_secret_provider import JwtSecretProvider

# Re-export exceptions for backward compatibility
__all__ = [
    "TokenService",
    "TokenServiceError",
    "TokenNotFoundError",
    "TokenRevokedError",
    "TokenValidationError",
    "TokenExpiredError",
    "FingerprintMismatchError",
]


class TokenService:
    """Service for JWT token operations.

    Handles JWT token creation, verification, and revocation without
    any knowledge of groups or authorization. This is the core JWT
    engine that AuthService uses internally.

    Features:
    - JWT token creation with configurable expiry
    - Token verification with optional store validation
    - Soft-delete token revocation
    - Device fingerprinting support
    - Enhanced JWT claims (nbf, aud, jti)

    Example:
        from gofr_common.auth.backends import VaultConfig, VaultClient, VaultTokenStore
        from gofr_common.auth import JwtSecretProvider

        vault_config = VaultConfig.from_env("GOFR_DIG")
        vault_client = VaultClient(vault_config)
        store = VaultTokenStore(vault_client)
        provider = JwtSecretProvider(vault_client)
        tokens = TokenService(store=store, secret_provider=provider)

        # Create a token
        jwt_token = tokens.create(groups=["admin"])

        # Verify a token
        info = tokens.verify(jwt_token)
        print(info.groups)  # ["admin"]

        # Revoke a token
        tokens.revoke(jwt_token)
    """

    def __init__(
        self,
        store: TokenStore,
        secret_provider: "JwtSecretProvider",
        env_prefix: str = "GOFR",
        logger: Optional[Logger] = None,
        audience: Optional[str] = None,
    ) -> None:
        """Initialize the token service.

        Args:
            store: TokenStore instance for token persistence
            secret_provider: JwtSecretProvider that supplies the JWT signing secret
            env_prefix: Prefix for environment variables (e.g., "GOFR_DIG")
            logger: Optional logger instance
            audience: Optional JWT audience claim
        """
        self._env_prefix = env_prefix.upper().replace("-", "_")
        self._audience = audience or f"{self._env_prefix.lower()}-api"
        self._store = store
        self._token_name_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$")
        self._secret_provider = secret_provider

        # Setup logger
        if logger is not None:
            self._logger = logger
        else:
            logger_name = self._env_prefix.lower().replace("_", "-") + "-tokens"
            self._logger = create_logger(name=logger_name)

        self._logger.debug(
            "TokenService initialized",
            store_type=type(store).__name__,
            secret_fingerprint=self.secret_fingerprint,
        )

    @property
    def secret_key(self) -> str:
        """Get the current JWT signing secret from the provider."""
        return self._secret_provider.get()

    @property
    def secret_fingerprint(self) -> str:
        """Get a fingerprint of the secret for logging (doesn't expose secret)."""
        return self._secret_provider.fingerprint

    @property
    def audience(self) -> str:
        """Get the JWT audience claim."""
        return self._audience

    @property
    def store(self) -> TokenStore:
        """Get the underlying token store."""
        return self._store

    def reload(self) -> None:
        """Reload token store from backend."""
        self._store.reload()

    def create(
        self,
        groups: List[str],
        expires_in_seconds: int = 2592000,
        fingerprint: Optional[str] = None,
        name: Optional[str] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new JWT token.

        Args:
            groups: List of group names to embed in the token
            expires_in_seconds: Token lifetime (default: 30 days)
            fingerprint: Optional device fingerprint for binding
            extra_claims: Optional additional JWT claims

        Returns:
            JWT token string
        """
        self.reload()

        normalized_name: Optional[str] = None
        if name is not None:
            normalized_name = self._normalize_and_validate_token_name(name)
            if self._store.exists_name(normalized_name):
                raise TokenValidationError(f"Token name '{normalized_name}' already exists")

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=expires_in_seconds)

        # Create token record
        token_record = TokenRecord.create(
            groups=groups,
            name=normalized_name,
            expires_at=expires_at,
            fingerprint=fingerprint,
        )

        # Build JWT payload
        payload: Dict[str, Any] = {
            "jti": str(token_record.id),
            "groups": groups,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "nbf": int(now.timestamp()),
            "aud": self._audience,
        }

        if fingerprint:
            payload["fp"] = fingerprint

        if extra_claims:
            payload.update(extra_claims)

        jwt_token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # Store token record
        self._store.put(str(token_record.id), token_record)

        self._logger.info(
            "Token created",
            token_id=str(token_record.id),
            groups=groups,
            expires_in_seconds=expires_in_seconds,
            name=normalized_name,
        )

        return jwt_token

    def verify(
        self,
        token: str,
        fingerprint: Optional[str] = None,
        require_store: bool = True,
    ) -> TokenInfo:
        """Verify a JWT token.

        Args:
            token: JWT token string
            fingerprint: Optional device fingerprint to verify
            require_store: If True, token must exist in store (default)

        Returns:
            TokenInfo with token data

        Raises:
            TokenValidationError: If token is invalid
            TokenNotFoundError: If token not in store (when require_store=True)
            TokenRevokedError: If token has been revoked
        """
        try:
            self.reload()

            # Decode JWT
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": False,
                },
            )

            token_id = payload.get("jti")
            if not token_id:
                raise TokenValidationError("Token missing jti claim")

            groups = payload.get("groups")
            if not groups:
                raise TokenValidationError("Token missing groups claim")

            # Validate audience if present
            if "aud" in payload and payload["aud"] != self._audience:
                raise TokenValidationError("Token audience mismatch")

            # Validate fingerprint if present
            if "fp" in payload and fingerprint:
                if payload["fp"] != fingerprint:
                    self._logger.warning(
                        "Fingerprint mismatch",
                        token_id=token_id,
                    )
                    raise FingerprintMismatchError()

            # Store validation
            if require_store:
                if not self._store.exists(token_id):
                    raise TokenNotFoundError(f"Token {token_id} not found")

                record = self._store.get(token_id)
                if record is None:
                    raise TokenNotFoundError(f"Token {token_id} not found")

                if record.status == "revoked":
                    raise TokenRevokedError(f"Token {token_id} revoked")

                # Verify groups match
                if set(record.groups) != set(groups):
                    raise TokenValidationError("Token groups mismatch")

            return TokenInfo(
                token=token,
                groups=groups,
                expires_at=datetime.fromtimestamp(payload["exp"]),
                issued_at=datetime.fromtimestamp(payload["iat"]),
            )

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError()
        except jwt.ImmatureSignatureError:
            raise TokenValidationError("Token not yet valid")
        except jwt.InvalidTokenError as e:
            raise TokenValidationError(f"Invalid token: {e}")

    def revoke(self, token: str) -> bool:
        """Revoke a token.

        Args:
            token: JWT token string

        Returns:
            True if revoked, False if not found
        """
        self.reload()

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": True,
                    "verify_aud": False,
                },
            )
            token_id = payload.get("jti")
            if not token_id:
                return False
        except jwt.InvalidTokenError:
            return False

        if not self._store.exists(token_id):
            return False

        record = self._store.get(token_id)
        if record is None:
            return False

        if record.status == "revoked":
            return True  # Already revoked

        record.status = "revoked"
        record.revoked_at = datetime.utcnow()
        self._store.put(token_id, record)

        self._logger.info("Token revoked", token_id=token_id)
        return True

    def list_all(
        self,
        status: Optional[Literal["active", "revoked"]] = None,
    ) -> List[TokenRecord]:
        """List all tokens.

        Args:
            status: Optional filter by status

        Returns:
            List of TokenRecord objects
        """
        self.reload()
        records = list(self._store.list_all().values())

        if status is not None:
            records = [r for r in records if r.status == status]

        return records

    def get_by_id(self, token_id: str) -> Optional[TokenRecord]:
        """Get a token record by ID.

        Args:
            token_id: UUID string

        Returns:
            TokenRecord if found, None otherwise
        """
        self.reload()
        if self._store.exists(token_id):
            return self._store.get(token_id)
        return None

    def get_by_name(self, name: str) -> Optional[TokenRecord]:
        """Get a token record by name (lower-level convenience)."""
        normalized_name = self._normalize_and_validate_token_name(name)
        self.reload()
        return self._store.get_by_name(normalized_name)

    def decode_without_verification(self, token: str) -> Dict[str, Any]:
        """Decode a token without verifying signature or expiry.

        Useful for extracting token ID for revocation or inspection.

        Args:
            token: JWT token string

        Returns:
            Token payload dictionary

        Raises:
            TokenValidationError: If token format is invalid
        """
        try:
            return jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_signature": False,
                },
            )
        except jwt.InvalidTokenError as e:
            raise TokenValidationError(f"Invalid token format: {e}")

    def _normalize_and_validate_token_name(self, name: str) -> str:
        """Normalize and validate a token name for TokenService usage."""
        normalized = name.strip().lower()
        if not normalized:
            raise TokenValidationError("Token name cannot be empty")

        if not self._token_name_pattern.match(normalized):
            raise TokenValidationError(
                "Invalid token name. Use 3-64 chars, lowercase letters/numbers, hyphens allowed between characters."
            )

        return normalized
