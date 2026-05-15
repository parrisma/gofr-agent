"""Tests for gofr_common.auth module."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from gofr_common.auth import (
    AuthService,
    FingerprintMismatchError,
    GroupRegistry,
    InvalidGroupError,
    JwtSecretProvider,
    TokenExpiredError,
    TokenInfo,
    TokenNotFoundError,
    TokenRevokedError,
    TokenValidationError,
)
from gofr_common.auth.backends import VaultClient, VaultConfig, VaultGroupStore, VaultTokenStore


def _build_vault_client() -> VaultClient:
    vault_url = os.environ.get("GOFR_VAULT_URL")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN")
    if not vault_url or not vault_token:
        raise RuntimeError(
            "Vault test configuration missing. Set GOFR_VAULT_URL and GOFR_VAULT_TOKEN."
        )
    return VaultClient(VaultConfig(url=vault_url, token=vault_token))


def _create_vault_stores() -> tuple[VaultTokenStore, VaultGroupStore]:
    vault_client = _build_vault_client()
    path_prefix = f"gofr/tests/{uuid4()}"
    return (
        VaultTokenStore(vault_client, path_prefix=path_prefix),
        VaultGroupStore(vault_client, path_prefix=path_prefix),
    )


def _make_test_secret_provider(secret: str = "test-secret") -> JwtSecretProvider:
    from unittest.mock import MagicMock

    mock_vault = MagicMock(spec=VaultClient)
    mock_vault.read_secret.return_value = {"value": secret}
    return JwtSecretProvider(vault_client=mock_vault)


def create_memory_auth(secret_key: str = "test-secret", **kwargs) -> AuthService:
    """Create an AuthService with Vault-backed stores for testing."""
    vault_client = _build_vault_client()
    path_prefix = f"gofr/tests/{uuid4()}"
    token_store = VaultTokenStore(vault_client, path_prefix=path_prefix)
    group_store = VaultGroupStore(vault_client, path_prefix=path_prefix)
    group_registry = GroupRegistry(store=group_store)
    return AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_provider=_make_test_secret_provider(secret_key),
        **kwargs,
    )


def create_file_auth(tmp_path: Path, secret_key: str = "test-secret", **kwargs) -> AuthService:
    """Create an AuthService with Vault-backed stores for testing."""
    _ = tmp_path
    return create_memory_auth(secret_key=secret_key, **kwargs)


# ============================================================================
# Test TokenInfo dataclass
# ============================================================================


class TestTokenInfo:
    """Tests for the TokenInfo dataclass."""

    def test_token_info_creation(self):
        """Test creating a TokenInfo."""
        now = datetime.utcnow()
        expires = now + timedelta(days=30)

        info = TokenInfo(
            token="test-token",
            groups=["admin"],
            expires_at=expires,
            issued_at=now,
        )

        assert info.token == "test-token"
        assert info.groups == ["admin"]
        assert info.expires_at == expires
        assert info.issued_at == now


# ============================================================================
# Test AuthService initialization
# ============================================================================


class TestAuthServiceInit:
    """Tests for AuthService initialization."""

    def test_init_with_secret(self, tmp_path: Path):
        """Test initialization with explicit secret."""
        auth = create_file_auth(tmp_path, secret_key="test-secret-key")

        assert auth.secret_key == "test-secret-key"

    def test_init_with_env_var(self, tmp_path: Path):
        """GOFR_JWT_SECRET env var is not used when JwtSecretProvider is provided."""
        _ = tmp_path
        with patch.dict(os.environ, {"GOFR_JWT_SECRET": "env-secret"}):
            auth = create_memory_auth(secret_key="test-secret")
            assert auth.secret_key == "test-secret"

    def test_init_auto_generates_secret(self, tmp_path: Path):
        """AuthService requires a secret_provider; it no longer auto-generates secrets."""
        _ = tmp_path
        token_store, group_store = _create_vault_stores()
        group_registry = GroupRegistry(store=group_store)
        with pytest.raises(TypeError):
            AuthService(
                token_store=token_store,
                group_registry=group_registry,
                env_prefix="GOFR_NONE",
            )

    def test_init_memory_mode(self):
        """Test initialization with in-memory token store."""
        auth = create_memory_auth()

        # Token store is a MemoryTokenStore, check it's empty
        assert len(auth._token_store.list_all()) == 0

    def test_init_creates_group_registry(self):
        """Test that AuthService has a GroupRegistry."""
        auth = create_memory_auth()

        # Should have group registry with reserved groups
        assert auth.groups is not None
        assert auth.groups.get_group_by_name("public") is not None
        assert auth.groups.get_group_by_name("admin") is not None

    def test_secret_fingerprint(self):
        """Test secret fingerprint generation."""
        auth = create_memory_auth()

        fingerprint = auth.get_secret_fingerprint()
        assert fingerprint.startswith("sha256:")
        assert len(fingerprint) == 19  # "sha256:" + 12 hex chars


# ============================================================================
# Test token creation
# ============================================================================


class TestTokenCreation:
    """Tests for token creation."""

    def test_create_token(self):
        """Test basic token creation."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"])

        assert token is not None
        assert len(token) > 0
        # Token store is now keyed by UUID, not JWT
        assert len(auth._token_store.list_all()) == 1
        record = list(auth._token_store.list_all().values())[0]
        assert record.groups == ["admin"]

    def test_create_token_multiple_groups(self):
        """Test token creation with multiple groups."""
        auth = create_memory_auth()

        # Create a non-reserved group first
        auth.groups.create_group("users", "Regular users")

        auth.create_token(groups=["admin", "users"])

        record = list(auth._token_store.list_all().values())[0]
        assert set(record.groups) == {"admin", "users"}

    def test_create_token_with_expiry(self):
        """Test token creation with custom expiry."""
        auth = create_memory_auth()

        auth.create_token(groups=["public"], expires_in_seconds=3600)

        # Verify token is stored
        assert len(auth._token_store.list_all()) == 1

        # Verify expiry is approximately 1 hour from now
        record = list(auth._token_store.list_all().values())[0]
        now = datetime.utcnow()
        assert record.expires_at is not None
        diff = (record.expires_at - now).total_seconds()
        assert 3590 < diff < 3610  # Within 10 seconds of expected

    def test_create_token_with_fingerprint(self):
        """Test token creation with fingerprint."""
        auth = create_memory_auth()

        auth.create_token(
            groups=["admin"],
            fingerprint="device-fingerprint-hash",
        )

        record = list(auth._token_store.list_all().values())[0]
        assert record.fingerprint == "device-fingerprint-hash"

    def test_create_token_with_name(self):
        """Token can be created with a human-readable name."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"], name="dev-api")

        assert token
        record = list(auth._token_store.list_all().values())[0]
        assert record.name == "dev-api"

        fetched = auth.get_token_by_name("dev-api")
        assert fetched is not None
        assert fetched.id == record.id
        assert fetched.name == "dev-api"

    def test_create_token_normalizes_name(self):
        """Names are lowercased and trimmed before storage."""
        auth = create_memory_auth()

        auth.create_token(groups=["admin"], name=" Dev-API ")

        record = list(auth._token_store.list_all().values())[0]
        assert record.name == "dev-api"

    def test_create_token_rejects_invalid_name(self):
        """Invalid name formats are rejected."""
        auth = create_memory_auth()

        with pytest.raises(TokenValidationError, match="Invalid token name"):
            auth.create_token(groups=["admin"], name="Bad Name")

    def test_create_token_name_must_be_unique(self):
        """Duplicate token names are not allowed."""
        auth = create_memory_auth()

        auth.create_token(groups=["admin"], name="ci-token")

        with pytest.raises(TokenValidationError, match="already exists"):
            auth.create_token(groups=["admin"], name="ci-token")

    def test_get_token_by_name_missing(self):
        """Lookup by name returns None when not found."""
        auth = create_memory_auth()

        assert auth.get_token_by_name("unknown-name") is None

    def test_create_token_invalid_group(self):
        """Test that token creation fails for non-existent groups."""
        auth = create_memory_auth()

        with pytest.raises(InvalidGroupError, match="does not exist"):
            auth.create_token(groups=["nonexistent"])

    def test_create_token_saves_to_file(self, tmp_path: Path):
        """Test that token creation saves to store."""
        auth = create_file_auth(tmp_path)

        auth.create_token(groups=["admin"])

        assert len(auth._token_store.list_all()) == 1


# ============================================================================
# Test token verification
# ============================================================================


class TestTokenVerification:
    """Tests for token verification."""

    def test_verify_valid_token(self):
        """Test verifying a valid token."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"])
        info = auth.verify_token(token)

        assert info.groups == ["admin"]
        assert info.token == token

    def test_verify_token_multiple_groups(self):
        """Test verifying a token with multiple groups."""
        auth = create_memory_auth()

        auth.groups.create_group("users")
        token = auth.create_token(groups=["admin", "users"])
        info = auth.verify_token(token)

        assert set(info.groups) == {"admin", "users"}

    def test_verify_expired_token(self):
        """Test that expired tokens are rejected."""
        auth = create_memory_auth()

        # Create token that expires in -1 seconds (already expired)
        token = auth.create_token(groups=["admin"], expires_in_seconds=-1)

        with pytest.raises(TokenExpiredError):
            auth.verify_token(token)

    def test_verify_token_not_in_store(self):
        """Test that tokens not in store are rejected."""
        auth = create_memory_auth()

        # Create a valid JWT but don't add to store
        from uuid import uuid4

        import jwt

        payload = {
            "jti": str(uuid4()),
            "groups": ["admin"],
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "test-secret", algorithm="HS256")

        with pytest.raises(TokenNotFoundError):
            auth.verify_token(token)

    def test_verify_token_wrong_secret(self):
        """Test that tokens signed with wrong secret are rejected."""
        auth = create_memory_auth()

        # Create token with different secret
        from uuid import uuid4

        import jwt

        payload = {
            "jti": str(uuid4()),
            "groups": ["admin"],
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

        with pytest.raises(TokenValidationError, match="Invalid token"):
            auth.verify_token(token)

    def test_verify_token_fingerprint_mismatch(self):
        """Test that fingerprint mismatch is detected."""
        auth = create_memory_auth()

        token = auth.create_token(
            groups=["admin"],
            fingerprint="original-fingerprint",
        )

        with pytest.raises(FingerprintMismatchError):
            auth.verify_token(token, fingerprint="different-fingerprint")

    def test_verify_token_stateless(self):
        """Test stateless verification (require_store=False)."""
        auth = create_memory_auth()

        # Create a valid JWT but don't add to store
        from uuid import uuid4

        import jwt

        payload = {
            "jti": str(uuid4()),
            "groups": ["admin"],
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "test-secret", algorithm="HS256")

        # Should work with require_store=False
        info = auth.verify_token(token, require_store=False)
        assert info.groups == ["admin"]


# ============================================================================
# Test token revocation
# ============================================================================


class TestTokenRevocation:
    """Tests for token revocation."""

    def test_revoke_token(self):
        """Test revoking a token."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"])
        assert len(auth._token_store.list_all()) == 1

        result = auth.revoke_token(token)

        assert result is True
        # Token is still in store but marked as revoked
        assert len(auth._token_store.list_all()) == 1
        record = list(auth._token_store.list_all().values())[0]
        assert record.status == "revoked"
        assert record.revoked_at is not None

    def test_revoke_token_prevents_verification(self):
        """Test that revoked tokens fail verification."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"])
        auth.revoke_token(token)

        with pytest.raises(TokenRevokedError):
            auth.verify_token(token)

    def test_revoke_nonexistent_token(self):
        """Test revoking a token that doesn't exist."""
        auth = create_memory_auth()

        # Create a valid JWT that's not in the store
        from uuid import uuid4

        import jwt

        payload = {
            "jti": str(uuid4()),
            "groups": ["admin"],
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "test-secret", algorithm="HS256")

        result = auth.revoke_token(token)

        assert result is False

    def test_revoke_token_by_name(self):
        """Token can be revoked using its name."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"], name="ci-token")

        result = auth.revoke_token_by_name("ci-token")

        assert result is True
        record = auth.get_token_by_name("ci-token")
        assert record is not None
        assert record.status == "revoked"
        assert record.revoked_at is not None

        with pytest.raises(TokenRevokedError):
            auth.verify_token(token)

    def test_revoke_token_by_name_not_found(self):
        """Revocation by name returns False when missing."""
        auth = create_memory_auth()

        assert auth.revoke_token_by_name("missing-name") is False


# ============================================================================
# Test token listing
# ============================================================================


class TestTokenListing:
    """Tests for listing tokens."""

    def test_list_tokens(self):
        """Test listing all tokens."""
        auth = create_memory_auth()

        auth.groups.create_group("users")
        auth.create_token(groups=["admin"])
        auth.create_token(groups=["users"])

        tokens = auth.list_tokens()

        assert len(tokens) == 2

    def test_list_tokens_empty(self):
        """Test listing tokens when store is empty."""
        auth = create_memory_auth()

        tokens = auth.list_tokens()

        assert tokens == []

    def test_list_tokens_status_filter(self):
        """Test listing tokens with status filter."""
        auth = create_memory_auth()

        token1 = auth.create_token(groups=["admin"])
        auth.create_token(groups=["admin"])
        auth.revoke_token(token1)

        active_tokens = auth.list_tokens(status="active")
        revoked_tokens = auth.list_tokens(status="revoked")

        assert len(active_tokens) == 1
        assert len(revoked_tokens) == 1


# ============================================================================
# Test resolve_token_groups
# ============================================================================


class TestResolveTokenGroups:
    """Tests for resolve_token_groups."""

    def test_resolve_token_groups(self):
        """Test resolving token to Group objects."""
        auth = create_memory_auth()

        token = auth.create_token(groups=["admin"])
        groups = auth.resolve_token_groups(token)

        # Should include admin and public (auto-included)
        group_names = {g.name for g in groups}
        assert "admin" in group_names
        assert "public" in group_names

    def test_resolve_token_always_includes_public(self):
        """Test that public group is always included."""
        auth = create_memory_auth()

        auth.groups.create_group("users")
        token = auth.create_token(groups=["users"])
        groups = auth.resolve_token_groups(token)

        group_names = {g.name for g in groups}
        assert "users" in group_names
        assert "public" in group_names

    def test_resolve_token_groups_for_invalid_token(self):
        """Test resolving groups for an invalid token."""
        auth = create_memory_auth()

        with pytest.raises(TokenValidationError):
            auth.resolve_token_groups("invalid-token")


# ============================================================================
# Test Authorization Middleware Helpers
# ============================================================================


class TestAuthorizationHelpers:
    """Tests for authorization middleware helpers."""

    def test_require_group_factory(self):
        """Test that require_group creates a callable."""
        from gofr_common.auth import require_group

        admin_check = require_group("admin")
        assert callable(admin_check)

    def test_require_any_group_factory(self):
        """Test that require_any_group creates a callable."""
        from gofr_common.auth import require_any_group

        check = require_any_group(["admin", "users"])
        assert callable(check)

    def test_require_all_groups_factory(self):
        """Test that require_all_groups creates a callable."""
        from gofr_common.auth import require_all_groups

        check = require_all_groups(["admin", "users"])
        assert callable(check)

    def test_require_admin_is_callable(self):
        """Test that require_admin is a callable dependency."""
        from gofr_common.auth import require_admin

        assert callable(require_admin)

    def test_token_info_has_group(self):
        """Test TokenInfo.has_group helper."""
        from datetime import datetime

        from gofr_common.auth import TokenInfo

        info = TokenInfo(
            token="test",
            groups=["admin", "users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_group("admin") is True
        assert info.has_group("users") is True
        assert info.has_group("other") is False

    def test_token_info_has_any_group(self):
        """Test TokenInfo.has_any_group helper."""
        from datetime import datetime

        from gofr_common.auth import TokenInfo

        info = TokenInfo(
            token="test",
            groups=["admin"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_any_group(["admin", "users"]) is True
        assert info.has_any_group(["users", "other"]) is False

    def test_token_info_has_all_groups(self):
        """Test TokenInfo.has_all_groups helper."""
        from datetime import datetime

        from gofr_common.auth import TokenInfo

        info = TokenInfo(
            token="test",
            groups=["admin", "users", "auditor"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_all_groups(["admin", "users"]) is True
        assert info.has_all_groups(["admin", "other"]) is False
        assert info.has_all_groups([]) is True  # Empty list = all satisfied


# ============================================================================
# Test Module Exports
# ============================================================================


class TestModuleExports:
    """Test that all expected items are exported from the module."""

    def test_service_exports(self):
        """Test AuthService and related exports."""
        from gofr_common.auth import (
            AuthService,
            InvalidGroupError,
            TokenNotFoundError,
            TokenRevokedError,
        )

        assert AuthService is not None
        assert InvalidGroupError is not None
        assert TokenNotFoundError is not None
        assert TokenRevokedError is not None

    def test_token_exports(self):
        """Test token-related exports."""
        from gofr_common.auth import TokenInfo, TokenRecord

        assert TokenInfo is not None
        assert TokenRecord is not None

    def test_group_exports(self):
        """Test group-related exports."""
        from gofr_common.auth import (
            RESERVED_GROUPS,
            DuplicateGroupError,
            Group,
            GroupNotFoundError,
            GroupRegistry,
            GroupRegistryError,
            ReservedGroupError,
        )

        assert Group is not None
        assert GroupRegistry is not None
        assert GroupRegistryError is not None
        assert ReservedGroupError is not None
        assert DuplicateGroupError is not None
        assert GroupNotFoundError is not None
        assert RESERVED_GROUPS == frozenset({"public", "admin"})

    def test_middleware_exports(self):
        """Test middleware-related exports."""
        from gofr_common.auth import (
            get_auth_service,
            get_security_auditor,
            init_auth_service,
            optional_verify_token,
            set_security_auditor,
            verify_token,
            verify_token_simple,
        )

        assert callable(get_auth_service)
        assert callable(verify_token)
        assert callable(verify_token_simple)
        assert callable(optional_verify_token)
        assert callable(init_auth_service)
        assert callable(set_security_auditor)
        assert callable(get_security_auditor)

    def test_authorization_helper_exports(self):
        """Test authorization helper exports."""
        from gofr_common.auth import (
            require_admin,
            require_all_groups,
            require_any_group,
            require_group,
        )

        assert callable(require_group)
        assert callable(require_any_group)
        assert callable(require_all_groups)
        assert callable(require_admin)

    def test_auth_provider_exports(self):
        """Test AuthProvider exports."""
        from gofr_common.auth import (
            AuthProvider,
            SecurityAuditorProtocol,
            create_auth_provider,
        )

        assert AuthProvider is not None
        assert SecurityAuditorProtocol is not None
        assert callable(create_auth_provider)

    def test_exception_hierarchy_exports(self):
        """Test exception hierarchy exports."""
        from gofr_common.auth import (
            AuthenticationError,
            AuthError,
            FingerprintMismatchError,
            GroupAccessDeniedError,
            GroupError,
            InvalidGroupError,
            TokenError,
            TokenExpiredError,
            TokenNotFoundError,
            TokenRevokedError,
            TokenServiceError,
            TokenValidationError,
        )

        # All exceptions should be exported
        assert AuthError is not None
        assert TokenError is not None
        assert TokenNotFoundError is not None
        assert TokenRevokedError is not None
        assert TokenExpiredError is not None
        assert TokenValidationError is not None
        assert TokenServiceError is not None
        assert GroupError is not None
        assert InvalidGroupError is not None
        assert GroupAccessDeniedError is not None
        assert AuthenticationError is not None
        assert FingerprintMismatchError is not None


# ============================================================================
# Test Exception Hierarchy
# ============================================================================


class TestExceptionHierarchy:
    """Tests for the auth exception hierarchy."""

    def test_auth_error_is_base(self):
        """Test that AuthError is the base exception."""
        from gofr_common.auth import (
            AuthenticationError,
            AuthError,
            GroupError,
            TokenError,
        )

        # All main exception types should inherit from AuthError
        assert issubclass(TokenError, AuthError)
        assert issubclass(GroupError, AuthError)
        assert issubclass(AuthenticationError, AuthError)

    def test_token_errors_inherit_from_token_error(self):
        """Test that token exceptions inherit from TokenError."""
        from gofr_common.auth import (
            TokenError,
            TokenExpiredError,
            TokenNotFoundError,
            TokenRevokedError,
            TokenServiceError,
            TokenValidationError,
        )

        assert issubclass(TokenNotFoundError, TokenError)
        assert issubclass(TokenRevokedError, TokenError)
        assert issubclass(TokenExpiredError, TokenError)
        assert issubclass(TokenValidationError, TokenError)
        assert issubclass(TokenServiceError, TokenError)

    def test_group_errors_inherit_from_group_error(self):
        """Test that group exceptions inherit from GroupError."""
        from gofr_common.auth import (
            GroupAccessDeniedError,
            GroupError,
            InvalidGroupError,
        )

        assert issubclass(InvalidGroupError, GroupError)
        assert issubclass(GroupAccessDeniedError, GroupError)

    def test_fingerprint_error_inherits_from_auth_error(self):
        """Test that FingerprintMismatchError inherits from AuthenticationError."""
        from gofr_common.auth import (
            AuthenticationError,
            FingerprintMismatchError,
        )

        assert issubclass(FingerprintMismatchError, AuthenticationError)

    def test_exception_status_codes(self):
        """Test that exceptions have correct HTTP status codes."""
        from gofr_common.auth import (
            AuthError,
            FingerprintMismatchError,
            GroupAccessDeniedError,
            GroupError,
            InvalidGroupError,
            TokenError,
            TokenExpiredError,
            TokenNotFoundError,
            TokenRevokedError,
            TokenValidationError,
        )

        # Token errors should be 401
        assert TokenError.status_code == 401
        assert TokenNotFoundError.status_code == 401
        assert TokenRevokedError.status_code == 401
        assert TokenExpiredError.status_code == 401
        assert TokenValidationError.status_code == 401

        # Group errors should be 403
        assert GroupError.status_code == 403
        assert InvalidGroupError.status_code == 403
        assert GroupAccessDeniedError.status_code == 403

        # Auth error base is 401
        assert AuthError.status_code == 401
        assert FingerprintMismatchError.status_code == 401

    def test_exception_default_messages(self):
        """Test that exceptions have default messages."""
        from gofr_common.auth import (
            FingerprintMismatchError,
            GroupAccessDeniedError,
            InvalidGroupError,
            TokenExpiredError,
            TokenNotFoundError,
            TokenRevokedError,
            TokenValidationError,
        )

        # Test default messages
        assert str(TokenNotFoundError()) == "Token not found in store"
        assert str(TokenRevokedError()) == "Token has been revoked"
        assert str(TokenExpiredError()) == "Token has expired"
        assert str(TokenValidationError()) == "Token validation failed"
        assert str(InvalidGroupError()) == "Invalid or defunct group"
        assert str(GroupAccessDeniedError()) == "Group access denied"
        assert (
            str(FingerprintMismatchError()) == "Token fingerprint mismatch - possible token theft"
        )

    def test_exception_custom_messages(self):
        """Test that exceptions can have custom messages."""
        from gofr_common.auth import (
            GroupAccessDeniedError,
            TokenNotFoundError,
        )

        # Test custom messages
        error = TokenNotFoundError("Custom message")
        assert str(error) == "Custom message"

        error = GroupAccessDeniedError("Access denied to admin group")
        assert str(error) == "Access denied to admin group"

    def test_all_token_exceptions_caught_by_auth_error(self):
        """Test that all token exceptions can be caught by AuthError."""
        from gofr_common.auth import (
            AuthError,
            TokenExpiredError,
            TokenNotFoundError,
            TokenRevokedError,
            TokenValidationError,
        )

        def raise_token_expired():
            raise TokenExpiredError()

        def raise_token_not_found():
            raise TokenNotFoundError()

        def raise_token_revoked():
            raise TokenRevokedError()

        def raise_token_validation():
            raise TokenValidationError()

        # All should be catchable with AuthError
        for func in [
            raise_token_expired,
            raise_token_not_found,
            raise_token_revoked,
            raise_token_validation,
        ]:
            with pytest.raises(AuthError):
                func()


# ============================================================================
# Test AuthProvider (Dependency Injection)
# ============================================================================


class TestAuthProvider:
    """Tests for the AuthProvider dependency injection class."""

    def test_provider_creation(self):
        """Test creating an AuthProvider."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        assert provider.service is auth_service
        assert provider.auditor is None

    def test_provider_with_auditor(self):
        """Test creating an AuthProvider with an auditor."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()

        class MockAuditor:
            def log_auth_failure(self, client_id, reason, endpoint=None, **details):
                pass

        auditor = MockAuditor()
        provider = AuthProvider(auth_service, auditor=auditor)

        assert provider.auditor is auditor

    def test_provider_set_auditor(self):
        """Test setting auditor after creation."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        class MockAuditor:
            def log_auth_failure(self, client_id, reason, endpoint=None, **details):
                pass

        auditor = MockAuditor()
        provider.set_auditor(auditor)
        assert provider.auditor is auditor

        provider.set_auditor(None)
        assert provider.auditor is None

    def test_provider_get_service(self):
        """Test get_service dependency."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        # get_service returns the service
        assert provider.get_service() is auth_service

    def test_provider_require_group_returns_callable(self):
        """Test require_group returns a callable."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        dependency = provider.require_group("admin")
        assert callable(dependency)

    def test_provider_require_any_group_returns_callable(self):
        """Test require_any_group returns a callable."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        dependency = provider.require_any_group(["admin", "users"])
        assert callable(dependency)

    def test_provider_require_all_groups_returns_callable(self):
        """Test require_all_groups returns a callable."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        dependency = provider.require_all_groups(["admin", "users"])
        assert callable(dependency)

    def test_provider_require_admin_returns_callable(self):
        """Test require_admin returns a callable."""
        from gofr_common.auth import AuthProvider

        auth_service = create_memory_auth()
        provider = AuthProvider(auth_service)

        dependency = provider.require_admin
        assert callable(dependency)

    def test_create_auth_provider_with_service(self):
        """Test create_auth_provider factory with existing service."""
        from gofr_common.auth import create_auth_provider

        auth_service = create_memory_auth()
        provider = create_auth_provider(auth_service=auth_service)

        assert provider.service is auth_service

    def test_create_auth_provider_from_env(self):
        """Test create_auth_provider factory from environment."""
        from gofr_common.auth import create_auth_provider

        with patch.dict(
            os.environ,
            {
                "GOFR_AUTH_BACKEND": "vault",
                "GOFR_VAULT_URL": os.environ.get("GOFR_VAULT_URL", ""),
                "GOFR_VAULT_TOKEN": os.environ.get("GOFR_VAULT_TOKEN", ""),
            },
        ):
            provider = create_auth_provider(
                secret_provider=_make_test_secret_provider("test-secret")
            )

            assert provider.service is not None
            assert provider.service.secret_key == "test-secret"


# ============================================================================
# Test TokenService (Low-level JWT Operations)
# ============================================================================


class TestTokenService:
    """Tests for the TokenService class."""

    def test_token_service_creation(self):
        """Test creating a TokenService."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        assert service.secret_key == "test-secret"
        assert service.store is store

    def test_token_service_create_token(self):
        """Test creating a token with TokenService."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token = service.create(groups=["admin", "users"])
        assert token is not None
        assert isinstance(token, str)

    def test_token_service_verify_token(self):
        """Test verifying a token with TokenService."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token = service.create(groups=["admin"])
        info = service.verify(token)

        assert info.groups == ["admin"]

    def test_token_service_revoke_token(self):
        """Test revoking a token with TokenService."""
        from gofr_common.auth import TokenRevokedError, TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token = service.create(groups=["admin"])
        assert service.revoke(token) is True

        with pytest.raises(TokenRevokedError):
            service.verify(token)

    def test_token_service_list_all(self):
        """Test listing all tokens with TokenService."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        service.create(groups=["admin"])
        service.create(groups=["users"])

        tokens = service.list_all()
        assert len(tokens) == 2

    def test_token_service_list_by_status(self):
        """Test listing tokens by status with TokenService."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token1 = service.create(groups=["admin"])
        service.create(groups=["users"])
        service.revoke(token1)

        active = service.list_all(status="active")
        revoked = service.list_all(status="revoked")

        assert len(active) == 1
        assert len(revoked) == 1

    def test_token_service_fingerprint(self):
        """Test token with fingerprint."""
        from gofr_common.auth import FingerprintMismatchError, TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token = service.create(groups=["admin"], fingerprint="device123")

        # Verify with matching fingerprint
        info = service.verify(token, fingerprint="device123")
        assert info.groups == ["admin"]

        # Verify with mismatched fingerprint
        with pytest.raises(FingerprintMismatchError):
            service.verify(token, fingerprint="wrong-device")

    def test_token_service_extra_claims(self):
        """Test token with extra claims."""
        from gofr_common.auth import TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        token = service.create(
            groups=["admin"],
            extra_claims={"custom_field": "custom_value"},
        )

        # Decode without verification to check claim
        payload = service.decode_without_verification(token)
        assert payload.get("custom_field") == "custom_value"

    def test_token_service_validation_errors(self):
        """Test TokenService validation errors."""
        from gofr_common.auth import TokenService, TokenValidationError

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        # Invalid token
        with pytest.raises(TokenValidationError):
            service.verify("invalid-token")

    def test_token_service_not_found_error(self):
        """Test TokenService not found error."""
        import jwt

        from gofr_common.auth import TokenNotFoundError, TokenService

        store, _group_store = _create_vault_stores()
        service = TokenService(
            store=store, secret_provider=_make_test_secret_provider("test-secret")
        )

        # Create a valid JWT but don't store it
        fake_token = jwt.encode(
            {"jti": "fake-id", "groups": ["admin"], "iat": 0, "exp": 9999999999, "nbf": 0},
            "test-secret",
            algorithm="HS256",
        )

        with pytest.raises(TokenNotFoundError):
            service.verify(fake_token)

    def test_token_service_exports(self):
        """Test TokenService exports."""
        from gofr_common.auth import (
            TokenService,
            TokenServiceError,
            TokenValidationError,
        )

        assert TokenService is not None
        assert TokenServiceError is not None
        assert TokenValidationError is not None

    def test_auth_service_has_tokens_property(self):
        """Test that AuthService exposes TokenService via tokens property."""
        from gofr_common.auth import TokenService

        auth = create_memory_auth()

        assert hasattr(auth, "tokens")
        assert isinstance(auth.tokens, TokenService)
        assert auth.tokens.secret_key == auth.secret_key
