"""JWT Authentication Service.

Handles JWT token creation, validation, and group mapping.
Parameterized to work with any GOFR project via env_prefix.
Now supports multi-group tokens with a central group registry.
Supports pluggable storage backends via TokenStore protocol.

This is the high-level authentication service that combines token
operations with group validation. For pure JWT operations without
group validation, see TokenService.
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
    InvalidGroupError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenRevokedError,
    TokenServiceError,
    TokenValidationError,
)
from .groups import Group, GroupRegistry
from .token_service import TokenService
from .tokens import TokenInfo, TokenRecord

if TYPE_CHECKING:
    from .jwt_secret_provider import JwtSecretProvider

# Re-export for backward compatibility
__all__ = [
    "AuthService",
    "InvalidGroupError",
    "TokenNotFoundError",
    "TokenRevokedError",
    "TokenValidationError",
    "TokenServiceError",
    "TokenExpiredError",
    "FingerprintMismatchError",
]


class AuthService:
    """Service for JWT authentication and multi-group management.

    This is the high-level authentication service that combines JWT
    token operations with group validation. It delegates JWT operations
    to TokenService internally.

    Features:
    - JWT token creation with configurable expiry
    - Multi-group tokens with group validation
    - Token verification with group extraction
    - Soft-delete token revocation (tokens never deleted)
    - Central group registry with reserved groups
    - Pluggable storage backends (vault)
    - Optional device fingerprinting for token binding
    - Enhanced JWT claims (nbf, aud, jti)

    For pure JWT operations without group validation, use TokenService directly.

    Example:
        from gofr_common.auth.backends import VaultConfig, VaultClient, VaultGroupStore, VaultTokenStore

        # Create Vault-backed stores
        vault_config = VaultConfig.from_env("GOFR_DIG")
        vault_client = VaultClient(vault_config)
        token_store = VaultTokenStore(vault_client)
        group_store = VaultGroupStore(vault_client)
        group_registry = GroupRegistry(store=group_store)

        # Create service
        auth = AuthService(
            secret_provider=provider,
            token_store=token_store,
            group_registry=group_registry,
        )
        token = auth.create_token(groups=["admin", "users"])
        info = auth.verify_token(token)
        print(info.groups)  # ["admin", "users"]

        # With environment variable fallback for secret
        auth = AuthService(
            token_store=token_store,
            group_registry=group_registry,
            secret_provider=provider,
            env_prefix="GOFR_DIG",
        )
    """

    def __init__(
        self,
        token_store: TokenStore,
        group_registry: GroupRegistry,
        secret_provider: "JwtSecretProvider",
        env_prefix: str = "GOFR",
        logger: Optional[Logger] = None,
        audience: Optional[str] = None,
    ):
        """Initialize the authentication service.

        Args:
            token_store: TokenStore instance for token storage (vault)
            group_registry: GroupRegistry instance for group management
            secret_provider: JwtSecretProvider that supplies the JWT signing secret
            env_prefix: Prefix for environment variables (e.g., "GOFR_DIG")
            logger: Optional logger instance. Creates one if not provided.
            audience: Optional JWT audience claim for token validation.
        """
        self.env_prefix = env_prefix.upper().replace("-", "_")

        # Setup logger - derive name from env_prefix (e.g., "GOFR_DIG" -> "gofr-dig-auth")
        if logger is not None:
            self.logger = logger
        else:
            # Convert prefix to logger name format
            logger_name = self.env_prefix.lower().replace("_", "-") + "-auth"
            self.logger = create_logger(name=logger_name)

        # Create internal TokenService for JWT operations
        self._token_service = TokenService(
            store=token_store,
            secret_provider=secret_provider,
            env_prefix=env_prefix,
            audience=audience,
        )

        # Expose key properties from token service
        self._secret_provider = secret_provider
        self.audience = self._token_service.audience

        # Store references
        self._token_store = token_store
        self._group_registry = group_registry

        self.logger.info(
            "AuthService initialized",
            token_store_type=type(token_store).__name__,
            group_store_type=type(group_registry._store).__name__,
            secret_fingerprint=self._secret_fingerprint(),
        )

        # Precompile token name validator (DNS-like names, 3-64 chars)
        self._token_name_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$")

    @property
    def tokens(self) -> TokenService:
        """Access the underlying TokenService.

        Use this for direct JWT operations without group validation.

        Returns:
            The TokenService instance
        """
        return self._token_service

    @property
    def secret_key(self) -> str:
        """Get the current JWT signing secret from the provider."""
        return self._secret_provider.get()

    @property
    def groups(self) -> GroupRegistry:
        """Access the group registry.

        Returns:
            The GroupRegistry instance for this AuthService
        """
        return self._group_registry

    def _secret_fingerprint(self) -> str:
        """Return a stable fingerprint for the current secret without exposing it."""
        return self._secret_provider.fingerprint

    def get_secret_fingerprint(self) -> str:
        """Public accessor for the JWT secret fingerprint."""
        return self._secret_fingerprint()

    def _reload_store(self) -> None:
        """Reload token store from backend (for file/vault backends)."""
        self._token_store.reload()

    def create_token(
        self,
        groups: List[str],
        expires_in_seconds: int = 2592000,
        fingerprint: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """Create a new JWT token for one or more groups.

        Args:
            groups: List of group names to associate with this token.
                   All groups must exist and be active in the registry.
            expires_in_seconds: Seconds until token expires (default: 30 days)
            fingerprint: Optional device/client fingerprint for binding

        Returns:
            JWT token string

        Raises:
            InvalidGroupError: If any group doesn't exist or is defunct
            TokenValidationError: If token name is invalid or already taken
        """
        # Reload store to ensure latest view for name uniqueness checks
        self._reload_store()

        normalized_name: Optional[str] = None
        if name is not None:
            normalized_name = self._normalize_and_validate_token_name(name)
            if self._token_store.exists_name(normalized_name):
                raise TokenValidationError(f"Token name '{normalized_name}' already exists")
        # Validate all groups exist and are active
        for group_name in groups:
            group = self._group_registry.get_group_by_name(group_name)
            if group is None:
                raise InvalidGroupError(f"Group '{group_name}' does not exist")
            if not group.is_active:
                raise InvalidGroupError(f"Group '{group_name}' is defunct")

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=expires_in_seconds)
        not_before = now

        # Create token record
        token_record = TokenRecord.create(
            groups=groups,
            expires_at=expires_at,
            fingerprint=fingerprint,
            name=normalized_name,
        )

        # Build JWT payload with UUID reference
        payload: Dict[str, Any] = {
            "jti": str(token_record.id),  # Token ID is the UUID
            "groups": groups,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "nbf": int(not_before.timestamp()),
            "aud": self.audience,
        }

        if fingerprint:
            payload["fp"] = fingerprint

        jwt_token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # Store token record keyed by UUID
        self._token_store.put(str(token_record.id), token_record)

        self.logger.info(
            "Token created",
            token_id=str(token_record.id),
            groups=groups,
            expires_at=expires_at.isoformat(),
            expires_in_seconds=expires_in_seconds,
            name=normalized_name,
        )

        return jwt_token

    def verify_token(
        self,
        token: str,
        fingerprint: Optional[str] = None,
        require_store: bool = True,
        validate_groups: bool = False,
    ) -> TokenInfo:
        """Verify a JWT token and extract information.

        Args:
            token: JWT token string
            fingerprint: Optional device/client fingerprint to verify against token binding
            require_store: If True, token must exist in store (default). Set False for
                          stateless verification.
            validate_groups: If True, verify all groups in token are active in registry.
                           Use this when you need real-time group validation at the cost
                           of additional lookups. Default False for backward compatibility.

        Returns:
            TokenInfo with groups and expiry information

        Raises:
            ValueError: If token is invalid, expired, revoked, or security checks fail
            InvalidGroupError: If validate_groups=True and any group is defunct or missing
        """
        try:
            # Reload token store to get latest tokens
            self._reload_store()

            # Decode and verify token with enhanced options
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": False,  # Don't require audience (backward compat)
                },
            )

            # Extract token ID (UUID)
            token_id = payload.get("jti")
            if not token_id:
                self.logger.error("Token missing jti claim")
                raise TokenValidationError("Token missing jti claim")

            # Get groups from payload
            groups = payload.get("groups")
            if not groups:
                self.logger.error("Token missing groups claim")
                raise TokenValidationError("Token missing groups claim")

            # Validate audience if present (optional for backward compatibility)
            if "aud" in payload and payload["aud"] != self.audience:
                self.logger.error("Token audience mismatch", aud=payload["aud"])
                raise TokenValidationError("Token audience mismatch")

            # Validate fingerprint if token has one and fingerprint provided
            if "fp" in payload:
                stored_fp = payload["fp"]
                if fingerprint and stored_fp != fingerprint:
                    self.logger.warning(
                        "Token fingerprint mismatch",
                        token_id=token_id,
                        expected=stored_fp[:12] if stored_fp else None,
                        actual=fingerprint[:12] if fingerprint else None,
                    )
                    raise FingerprintMismatchError()

            # Check if token is in our store (if required)
            if require_store:
                if not self._token_store.exists(token_id):
                    self.logger.warning("Token not found in store", token_id=token_id)
                    raise TokenNotFoundError(f"Token {token_id} not found in token store")

                token_record = self._token_store.get(token_id)
                if token_record is None:
                    self.logger.warning("Token not found in store", token_id=token_id)
                    raise TokenNotFoundError(f"Token {token_id} not found in token store")

                # Check if token is revoked
                if token_record.status == "revoked":
                    self.logger.warning("Token has been revoked", token_id=token_id)
                    raise TokenRevokedError(f"Token {token_id} has been revoked")

                # Verify groups match store
                if set(token_record.groups) != set(groups):
                    self.logger.error(
                        "Token groups mismatch",
                        stored_groups=token_record.groups,
                        token_groups=groups,
                    )
                    raise TokenValidationError("Token groups mismatch in store")

            # Validate groups are active in registry (if requested)
            if validate_groups:
                for group_name in groups:
                    # Skip reserved groups - they're always valid
                    if group_name in ("public", "admin"):
                        continue
                    group = self._group_registry.get_group_by_name(group_name)
                    if group is None:
                        self.logger.warning(
                            "Token references non-existent group",
                            token_id=token_id,
                            group=group_name,
                        )
                        raise InvalidGroupError(f"Group '{group_name}' does not exist")
                    if not group.is_active:
                        self.logger.warning(
                            "Token references defunct group",
                            token_id=token_id,
                            group=group_name,
                        )
                        raise InvalidGroupError(f"Group '{group_name}' is defunct")

            issued_at = datetime.fromtimestamp(payload["iat"])
            expires_at = datetime.fromtimestamp(payload["exp"])

            self.logger.debug(
                "Token verified",
                token_id=token_id,
                groups=groups,
                expires_at=expires_at.isoformat(),
            )

            return TokenInfo(
                token=token,
                groups=groups,
                expires_at=expires_at,
                issued_at=issued_at,
            )

        except jwt.ExpiredSignatureError:
            self.logger.warning("Token expired")
            raise TokenExpiredError()
        except jwt.ImmatureSignatureError:
            self.logger.warning("Token not yet valid (nbf)")
            raise TokenValidationError("Token not yet valid")
        except jwt.InvalidTokenError as e:
            self.logger.error("Invalid token", error=str(e))
            raise TokenValidationError(f"Invalid token: {str(e)}")

    def revoke_token(self, token: str) -> bool:
        """Revoke a token by setting its status to "revoked".

        Tokens are soft-deleted - they remain in the store but are
        marked as revoked with a timestamp.

        Args:
            token: JWT token string to revoke

        Returns:
            True if token was found and revoked, False if not found
        """
        self._reload_store()

        try:
            # Decode token to get UUID (don't verify expiry for revocation)
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
                self.logger.warning("Token missing jti claim for revocation")
                return False
        except jwt.InvalidTokenError as e:
            self.logger.warning("Invalid token for revocation", error=str(e))
            return False

        if self._token_store.exists(token_id):
            token_record = self._token_store.get(token_id)
            if token_record is None:
                self.logger.warning("Token not found for revocation", token_id=token_id)
                return False

            # Check if already revoked
            if token_record.status == "revoked":
                self.logger.info("Token already revoked", token_id=token_id)
                return True

            # Soft-delete: set status and timestamp
            token_record.status = "revoked"
            token_record.revoked_at = datetime.utcnow()

            # Update in store
            self._token_store.put(token_id, token_record)
            self.logger.info("Token revoked", token_id=token_id, groups=token_record.groups)
            return True
        else:
            self.logger.warning("Token not found for revocation", token_id=token_id)
            return False

    def revoke_token_by_name(self, name: str) -> bool:
        """Revoke a token by its human-readable name.

        Args:
            name: Token name to revoke

        Returns:
            True if found (or already revoked), False otherwise
        """
        normalized_name = self._normalize_and_validate_token_name(name)
        self._reload_store()

        record = self._token_store.get_by_name(normalized_name)
        if record is None:
            self.logger.warning("Token name not found for revocation", token_name=normalized_name)
            return False

        if record.status == "revoked":
            self.logger.info(
                "Token already revoked", token_name=normalized_name, token_id=str(record.id)
            )
            return True

        record.status = "revoked"
        record.revoked_at = datetime.utcnow()
        self._token_store.put(str(record.id), record)

        self.logger.info("Token revoked", token_name=normalized_name, token_id=str(record.id))
        return True

    def list_tokens(
        self,
        status: Optional[Literal["active", "revoked"]] = None,
    ) -> List[TokenRecord]:
        """List all tokens in the store.

        Args:
            status: Optional filter by status ("active" or "revoked").
                   If None, returns all tokens.

        Returns:
            List of TokenRecord objects
        """
        self._reload_store()

        records = list(self._token_store.list_all().values())

        if status is not None:
            records = [r for r in records if r.status == status]

        return records

    def get_token_by_id(self, token_id: str) -> Optional[TokenRecord]:
        """Get a token record by its UUID.

        Args:
            token_id: UUID string of the token

        Returns:
            TokenRecord if found, None otherwise
        """
        self._reload_store()
        if self._token_store.exists(token_id):
            return self._token_store.get(token_id)
        return None

    def get_token_by_name(self, name: str) -> Optional[TokenRecord]:
        """Get a token record by its human-readable name."""
        normalized_name = self._normalize_and_validate_token_name(name)
        self._reload_store()
        return self._token_store.get_by_name(normalized_name)

    def resolve_token_groups(
        self,
        token: str,
        include_defunct: bool = False,
    ) -> List[Group]:
        """Resolve a token to its list of Group objects.

        The `public` group is always included in the result, even if
        not explicitly in the token.

        Args:
            token: JWT token string
            include_defunct: If True, include defunct groups (default False)

        Returns:
            List of Group objects the token grants access to

        Raises:
            ValueError: If token is invalid
        """
        token_info = self.verify_token(token)

        resolved_groups: List[Group] = []
        seen_names: set = set()

        # Get all groups from token
        for group_name in token_info.groups:
            if group_name in seen_names:
                continue
            group = self._group_registry.get_group_by_name(group_name)
            if group is not None:
                if include_defunct or group.is_active:
                    resolved_groups.append(group)
                    seen_names.add(group_name)

        # Always include public group
        if "public" not in seen_names:
            public_group = self._group_registry.get_group_by_name("public")
            if public_group is not None:
                resolved_groups.append(public_group)

        return resolved_groups

    def _normalize_and_validate_token_name(self, name: str) -> str:
        """Normalize and validate a token name.

        Enforces lowercase, trims surrounding whitespace, and validates DNS-like
        pattern (3-64 chars, alphanumeric with internal hyphens).
        """

        normalized = name.strip().lower()
        if not normalized:
            raise TokenValidationError("Token name cannot be empty")

        if not self._token_name_pattern.match(normalized):
            raise TokenValidationError(
                "Invalid token name. Use 3-64 chars, lowercase letters/numbers, hyphens allowed between characters."
            )

        return normalized
