"""Integration tests for Vault-backed storage.

These tests require a running Vault container and are skipped if unavailable.
Run with: ./scripts/run_tests.sh -m vault_integration

Vault setup (dev mode):
    ./docker/infra/vault/run.sh --test
"""

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from gofr_common.auth import (
    AuthService,
    GroupRegistry,
    JwtSecretProvider,
    TokenRevokedError,
    VaultClient,
    VaultConfig,
    VaultGroupStore,
    VaultTokenStore,
)
from gofr_common.auth.groups import Group

# Default Vault dev configuration
VAULT_URL = os.environ.get("GOFR_VAULT_URL", "http://gofr-vault:8200")
VAULT_TOKEN = os.environ.get("GOFR_VAULT_TOKEN", "gofr-dev-root-token")


def vault_available() -> bool:
    """Check if Vault is available and healthy.

    This function is called at test execution time, not module import time,
    so it can properly detect Vault started by the test runner.
    """
    try:
        # Re-read environment variables in case they were set after module import
        vault_url = os.environ.get("GOFR_VAULT_URL", "http://gofr-vault:8200")
        vault_token = os.environ.get("GOFR_VAULT_TOKEN", "gofr-dev-root-token")
        config = VaultConfig(url=vault_url, token=vault_token)
        client = VaultClient(config)
        return client.health_check()
    except Exception:
        return False


# Mark all tests as vault_integration but check availability at runtime
pytestmark = pytest.mark.vault_integration


@pytest.fixture
def vault_available_fixture() -> bool:
    """Check Vault availability at test execution time and skip if not available."""
    if not vault_available():
        pytest.skip("Vault not available")
    return True


@pytest.fixture
def vault_config(vault_available_fixture) -> VaultConfig:
    """Create a VaultConfig for testing."""
    vault_url = os.environ.get("GOFR_VAULT_URL", "http://gofr-vault:8200")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN", "gofr-dev-root-token")
    return VaultConfig(url=vault_url, token=vault_token)


@pytest.fixture
def vault_client(vault_config: VaultConfig) -> VaultClient:
    """Create a VaultClient for testing."""
    return VaultClient(vault_config)


@pytest.fixture
def unique_prefix() -> str:
    """Generate a unique path prefix for test isolation."""
    return f"test/{uuid4().hex[:8]}"


@pytest.fixture
def token_store(vault_client: VaultClient, unique_prefix: str):
    """Create a VaultTokenStore with unique prefix."""
    store = VaultTokenStore(vault_client, path_prefix=unique_prefix)
    yield store
    # Cleanup after test
    try:
        store.clear()
    except Exception:
        pass


@pytest.fixture
def group_store(vault_client: VaultClient, unique_prefix: str):
    """Create a VaultGroupStore with unique prefix."""
    store = VaultGroupStore(vault_client, path_prefix=unique_prefix)
    yield store
    # Cleanup after test
    try:
        store.clear()
    except Exception:
        pass


@pytest.fixture
def group_registry(group_store: VaultGroupStore) -> GroupRegistry:
    """Create a GroupRegistry with Vault backend."""
    return GroupRegistry(store=group_store)


@pytest.fixture
def auth_service(token_store: VaultTokenStore, group_registry: GroupRegistry) -> AuthService:
    """Create an AuthService with Vault backends."""
    from unittest.mock import MagicMock

    mock_vault = MagicMock(spec=VaultClient)
    mock_vault.read_secret.return_value = {"value": "integration-test-secret"}
    secret_provider = JwtSecretProvider(vault_client=mock_vault)
    return AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_provider=secret_provider,
    )


# ============================================================================
# VaultClient Integration Tests
# ============================================================================


class TestVaultClientIntegration:
    """Integration tests for VaultClient."""

    def test_health_check(self, vault_client: VaultClient):
        """Test health check against real Vault."""
        assert vault_client.health_check() is True

    def test_is_authenticated(self, vault_client: VaultClient):
        """Test authentication status."""
        assert vault_client.is_authenticated() is True

    def test_write_read_delete_cycle(self, vault_client: VaultClient, unique_prefix: str):
        """Test full write/read/delete cycle."""
        path = f"{unique_prefix}/test-secret"
        data = {"key": "value", "number": 42}

        # Write
        vault_client.write_secret(path, data)

        # Read
        result = vault_client.read_secret(path)
        assert result == data

        # Delete
        vault_client.delete_secret(path)

        # Verify deleted
        result = vault_client.read_secret(path)
        assert result is None

    def test_list_secrets(self, vault_client: VaultClient, unique_prefix: str):
        """Test listing secrets."""
        # Write some secrets
        vault_client.write_secret(f"{unique_prefix}/a", {"val": 1})
        vault_client.write_secret(f"{unique_prefix}/b", {"val": 2})
        vault_client.write_secret(f"{unique_prefix}/c", {"val": 3})

        # List
        keys = vault_client.list_secrets(unique_prefix)
        assert set(keys) == {"a", "b", "c"}

        # Cleanup
        vault_client.delete_secret(f"{unique_prefix}/a")
        vault_client.delete_secret(f"{unique_prefix}/b")
        vault_client.delete_secret(f"{unique_prefix}/c")

    def test_secret_exists(self, vault_client: VaultClient, unique_prefix: str):
        """Test secret existence check."""
        path = f"{unique_prefix}/exists-test"

        assert vault_client.secret_exists(path) is False

        vault_client.write_secret(path, {"test": True})
        assert vault_client.secret_exists(path) is True

        vault_client.delete_secret(path)
        assert vault_client.secret_exists(path) is False


# ============================================================================
# VaultTokenStore Integration Tests
# ============================================================================


class TestVaultTokenStoreIntegration:
    """Integration tests for VaultTokenStore."""

    def test_put_and_get_token(self, token_store: VaultTokenStore):
        """Test storing and retrieving a token."""
        from gofr_common.auth.tokens import TokenRecord

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin", "users"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )

        token_store.put(token_id, record)

        retrieved = token_store.get(token_id)
        assert retrieved is not None
        assert retrieved.groups == ["admin", "users"]
        assert retrieved.status == "active"

    def test_get_nonexistent_token(self, token_store: VaultTokenStore):
        """Test getting a nonexistent token returns None."""
        result = token_store.get(str(uuid4()))
        assert result is None

    def test_exists(self, token_store: VaultTokenStore):
        """Test token existence check."""
        from gofr_common.auth.tokens import TokenRecord

        token_id = str(uuid4())
        assert token_store.exists(token_id) is False

        record = TokenRecord.create(
            groups=["public"], expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        token_store.put(token_id, record)

        assert token_store.exists(token_id) is True

    def test_list_all(self, token_store: VaultTokenStore):
        """Test listing all tokens."""
        from gofr_common.auth.tokens import TokenRecord

        # Store multiple tokens
        ids = []
        for i in range(3):
            token_id = str(uuid4())
            ids.append(token_id)
            record = TokenRecord.create(
                groups=["public"],
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
            token_store.put(token_id, record)

        all_tokens = token_store.list_all()
        assert len(all_tokens) >= 3
        for token_id in ids:
            assert token_id in all_tokens

    def test_delete_token(self, token_store: VaultTokenStore):
        """Test deleting a token."""
        from gofr_common.auth.tokens import TokenRecord

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["public"], expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        token_store.put(token_id, record)

        assert token_store.exists(token_id) is True
        token_store.delete(token_id)
        assert token_store.exists(token_id) is False

    def test_clear(self, token_store: VaultTokenStore):
        """Test clearing all tokens."""
        from gofr_common.auth.tokens import TokenRecord

        # Store some tokens
        for _ in range(3):
            token_id = str(uuid4())
            record = TokenRecord.create(
                groups=["public"], expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            token_store.put(token_id, record)

        assert len(token_store) >= 3

        token_store.clear()

        assert len(token_store) == 0

    def test_len(self, token_store: VaultTokenStore):
        """Test counting tokens."""
        from gofr_common.auth.tokens import TokenRecord

        initial_count = len(token_store)

        for i in range(5):
            token_id = str(uuid4())
            record = TokenRecord.create(
                groups=["public"], expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            token_store.put(token_id, record)

        assert len(token_store) == initial_count + 5


# ============================================================================
# VaultGroupStore Integration Tests
# ============================================================================


class TestVaultGroupStoreIntegration:
    """Integration tests for VaultGroupStore."""

    def test_put_and_get_group(self, group_store: VaultGroupStore):
        """Test storing and retrieving a group."""
        group_id = str(uuid4())
        group = Group(
            id=uuid4(),
            name="test-group",
            description="Test group for integration",
        )

        group_store.put(group_id, group)

        retrieved = group_store.get(group_id)
        assert retrieved is not None
        assert retrieved.name == "test-group"
        assert retrieved.description == "Test group for integration"

    def test_get_by_name(self, group_store: VaultGroupStore):
        """Test getting a group by name using index."""
        group_id = str(uuid4())
        group = Group(
            id=uuid4(),
            name="indexed-group",
            description="Group with index lookup",
        )

        group_store.put(group_id, group)

        retrieved = group_store.get_by_name("indexed-group")
        assert retrieved is not None
        assert retrieved.name == "indexed-group"

    def test_get_by_name_after_rename(self, group_store: VaultGroupStore):
        """Test that name index updates on rename."""
        group_id = str(uuid4())
        group = Group(id=uuid4(), name="original-name")

        group_store.put(group_id, group)
        assert group_store.get_by_name("original-name") is not None

        # Rename
        group.name = "new-name"
        group_store.put(group_id, group)

        # Old name should not work
        assert group_store.get_by_name("original-name") is None
        # New name should work
        assert group_store.get_by_name("new-name") is not None

    def test_list_all_excludes_index(self, group_store: VaultGroupStore):
        """Test that list_all excludes the _index directory."""
        group_id = str(uuid4())
        group = Group(id=uuid4(), name="listed-group")
        group_store.put(group_id, group)

        all_groups = group_store.list_all()

        # Should not include any _index entries
        for key in all_groups.keys():
            assert "_index" not in key

    def test_delete_removes_from_index(self, group_store: VaultGroupStore):
        """Test that delete removes from name index."""
        group_id = str(uuid4())
        group = Group(id=uuid4(), name="to-delete")

        group_store.put(group_id, group)
        assert group_store.get_by_name("to-delete") is not None

        group_store.delete(group_id)
        assert group_store.get_by_name("to-delete") is None


# ============================================================================
# GroupRegistry Integration Tests
# ============================================================================


class TestGroupRegistryIntegration:
    """Integration tests for GroupRegistry with Vault backend."""

    def test_reserved_groups_created(self, group_registry: GroupRegistry):
        """Test that reserved groups are created in Vault."""
        public = group_registry.get_group_by_name("public")
        admin = group_registry.get_group_by_name("admin")

        assert public is not None
        assert public.is_reserved is True
        assert admin is not None
        assert admin.is_reserved is True

    def test_create_and_retrieve_group(self, group_registry: GroupRegistry):
        """Test creating and retrieving a group."""
        group_registry.create_group("vault-users", "Users in Vault")

        retrieved = group_registry.get_group_by_name("vault-users")
        assert retrieved is not None
        assert retrieved.name == "vault-users"
        assert retrieved.description == "Users in Vault"

    def test_make_defunct(self, group_registry: GroupRegistry):
        """Test making a group defunct."""
        group = group_registry.create_group("to-defunct")

        group_registry.make_defunct(group.id)

        updated = group_registry.get_group(group.id)
        assert updated is not None
        assert updated.is_active is False

    def test_list_groups(self, group_registry: GroupRegistry):
        """Test listing groups."""
        group_registry.create_group("list-test-1")
        group_registry.create_group("list-test-2")

        groups = group_registry.list_groups()
        names = {g.name for g in groups}

        assert "public" in names
        assert "admin" in names
        assert "list-test-1" in names
        assert "list-test-2" in names


# ============================================================================
# AuthService Integration Tests
# ============================================================================


class TestAuthServiceIntegration:
    """Integration tests for AuthService with Vault backends."""

    def test_create_and_verify_token(self, auth_service: AuthService):
        """Test creating and verifying a token."""
        token = auth_service.create_token(groups=["admin"])

        info = auth_service.verify_token(token)
        assert info.groups == ["admin"]

    def test_create_token_with_custom_group(self, auth_service: AuthService):
        """Test creating a token for a custom group."""
        auth_service.groups.create_group("custom-group")

        token = auth_service.create_token(groups=["custom-group"])
        info = auth_service.verify_token(token)

        assert "custom-group" in info.groups

    def test_revoke_token(self, auth_service: AuthService):
        """Test revoking a token."""
        token = auth_service.create_token(groups=["admin"])

        # Verify works before revocation
        auth_service.verify_token(token)

        # Revoke
        auth_service.revoke_token(token)

        # Verify fails after revocation
        with pytest.raises(TokenRevokedError):
            auth_service.verify_token(token)

    def test_list_tokens(self, auth_service: AuthService):
        """Test listing tokens."""
        auth_service.create_token(groups=["admin"])
        auth_service.create_token(groups=["public"])

        tokens = auth_service.list_tokens()
        assert len(tokens) >= 2

    def test_resolve_token_groups(self, auth_service: AuthService):
        """Test resolving token groups to Group objects."""
        auth_service.groups.create_group("resolve-test")
        token = auth_service.create_token(groups=["resolve-test"])

        groups = auth_service.resolve_token_groups(token)
        names = {g.name for g in groups}

        assert "resolve-test" in names
        assert "public" in names  # Auto-included


# ============================================================================
# Multi-Client Tests
# ============================================================================


class TestMultiClientIntegration:
    """Test multiple AuthService instances sharing the same Vault."""

    def test_token_created_on_a_visible_on_b(self, vault_client: VaultClient, unique_prefix: str):
        """Test that a token created on instance A is visible on instance B."""
        # Create two separate token stores pointing to same Vault prefix
        token_store_a = VaultTokenStore(vault_client, path_prefix=unique_prefix)
        token_store_b = VaultTokenStore(vault_client, path_prefix=unique_prefix)

        # Create two separate group stores pointing to same Vault prefix
        group_store_a = VaultGroupStore(vault_client, path_prefix=unique_prefix)
        group_store_b = VaultGroupStore(vault_client, path_prefix=unique_prefix)

        # Create registries and services
        registry_a = GroupRegistry(store=group_store_a)
        registry_b = GroupRegistry(store=group_store_b, auto_bootstrap=False)

        auth_a = AuthService(
            token_store=token_store_a,
            group_registry=registry_a,
            secret_provider=JwtSecretProvider(
                vault_client=vault_client, vault_path="gofr/config/jwt-signing-secret"
            ),
        )
        auth_b = AuthService(
            token_store=token_store_b,
            group_registry=registry_b,
            secret_provider=JwtSecretProvider(
                vault_client=vault_client, vault_path="gofr/config/jwt-signing-secret"
            ),
        )

        # Create token on A
        token = auth_a.create_token(groups=["admin"])

        # Verify on B
        info = auth_b.verify_token(token)
        assert info.groups == ["admin"]

        # Cleanup
        token_store_a.clear()
        group_store_a.clear()

    def test_token_revoked_on_a_rejected_on_b(self, vault_client: VaultClient, unique_prefix: str):
        """Test that a token revoked on instance A is rejected on instance B."""
        # Create two separate stores pointing to same Vault prefix
        token_store_a = VaultTokenStore(vault_client, path_prefix=unique_prefix)
        token_store_b = VaultTokenStore(vault_client, path_prefix=unique_prefix)

        group_store_a = VaultGroupStore(vault_client, path_prefix=unique_prefix)
        group_store_b = VaultGroupStore(vault_client, path_prefix=unique_prefix)

        registry_a = GroupRegistry(store=group_store_a)
        registry_b = GroupRegistry(store=group_store_b, auto_bootstrap=False)

        auth_a = AuthService(
            token_store=token_store_a,
            group_registry=registry_a,
            secret_provider=JwtSecretProvider(
                vault_client=vault_client, vault_path="gofr/config/jwt-signing-secret"
            ),
        )
        auth_b = AuthService(
            token_store=token_store_b,
            group_registry=registry_b,
            secret_provider=JwtSecretProvider(
                vault_client=vault_client, vault_path="gofr/config/jwt-signing-secret"
            ),
        )

        # Create token on A
        token = auth_a.create_token(groups=["admin"])

        # Verify works on B
        auth_b.verify_token(token)

        # Revoke on A
        auth_a.revoke_token(token)

        # Should be rejected on B
        with pytest.raises(TokenRevokedError):
            auth_b.verify_token(token)

        # Cleanup
        token_store_a.clear()
        group_store_a.clear()

    def test_group_created_on_a_visible_on_b(self, vault_client: VaultClient, unique_prefix: str):
        """Test that a group created on instance A is visible on instance B."""
        group_store_a = VaultGroupStore(vault_client, path_prefix=unique_prefix)
        group_store_b = VaultGroupStore(vault_client, path_prefix=unique_prefix)

        registry_a = GroupRegistry(store=group_store_a)
        registry_b = GroupRegistry(store=group_store_b, auto_bootstrap=False)

        # Create group on A
        registry_a.create_group("shared-group", "Created on A")

        # Should be visible on B
        found = registry_b.get_group_by_name("shared-group")
        assert found is not None
        assert found.description == "Created on A"

        # Cleanup
        group_store_a.clear()


# ============================================================================
# VaultTokenStore Cache Tests
# ============================================================================


class TestVaultTokenStoreCaching:
    """Tests for VaultTokenStore TTL caching and retry-on-miss functionality."""

    def test_cache_hit_returns_cached_value(self, vault_client: VaultClient, unique_prefix: str):
        """Test that repeated gets return cached value without hitting Vault."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)

        # First get populates cache
        result1 = store.get(token_id)
        assert result1 is not None

        # Second get should hit cache (we can't directly verify, but it should work)
        result2 = store.get(token_id)
        assert result2 is not None
        assert result2.groups == result1.groups

        # Cleanup
        store.clear()

    def test_cache_disabled_when_ttl_zero(self, vault_client: VaultClient, unique_prefix: str):
        """Test that caching is disabled when cache_ttl=0."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=0)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)

        # Cache should be empty since TTL=0
        assert store._get_from_cache(token_id) is None

        # Get should still work (directly from Vault)
        result = store.get(token_id)
        assert result is not None

        # Cleanup
        store.clear()

    def test_bypass_cache_fetches_from_vault(self, vault_client: VaultClient, unique_prefix: str):
        """Test that bypass_cache=True fetches directly from Vault."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)

        # Bypass cache should still return the record
        result = store.get(token_id, bypass_cache=True)
        assert result is not None
        assert result.groups == ["admin"]

        # Cleanup
        store.clear()

    def test_cache_invalidation_on_delete(self, vault_client: VaultClient, unique_prefix: str):
        """Test that delete invalidates the cache entry."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)

        # Populate cache
        store.get(token_id)
        assert store._get_from_cache(token_id) is not None

        # Delete should invalidate cache
        store.delete(token_id)
        assert store._get_from_cache(token_id) is None

        # Cleanup
        store.clear()

    def test_reload_clears_cache(self, vault_client: VaultClient, unique_prefix: str):
        """Test that reload() clears all cached entries."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        # Create and cache some tokens
        token_ids = []
        for i in range(3):
            token_id = str(uuid4())
            token_ids.append(token_id)
            record = TokenRecord.create(
                groups=["public"],
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
            store.put(token_id, record)
            store.get(token_id)  # Populate cache

        # Verify cache is populated
        for tid in token_ids:
            assert store._get_from_cache(tid) is not None

        # Reload should clear cache
        store.reload()

        for tid in token_ids:
            assert store._get_from_cache(tid) is None

        # Cleanup
        store.clear()

    def test_retry_on_miss_finds_externally_created_token(
        self, vault_client: VaultClient, unique_prefix: str
    ):
        """Test that retry_on_miss finds a token created by another store instance."""
        from gofr_common.auth.tokens import TokenRecord

        # Two store instances sharing the same Vault prefix (simulates two services)
        store_a = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)
        store_b = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        # Store A creates a token
        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store_a.put(token_id, record)

        # Store B hasn't seen this token yet (not in its cache)
        # exists() with retry_on_miss=True should find it
        assert store_b.exists(token_id, retry_on_miss=True) is True

        # Now get() should also work
        result = store_b.get(token_id)
        assert result is not None
        assert result.groups == ["admin"]

        # Cleanup
        store_a.clear()

    def test_exists_without_retry_may_miss_new_token(
        self, vault_client: VaultClient, unique_prefix: str
    ):
        """Test exists() behavior - with retry_on_miss=False, cache staleness matters."""
        from gofr_common.auth.tokens import TokenRecord

        # Two store instances
        store_a = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)
        store_b = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())

        # Store B checks for token first - caches the "not found" result
        # Note: With our implementation, we only cache found tokens, not misses
        # So this test verifies the retry_on_miss behavior

        # Store A creates the token
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store_a.put(token_id, record)

        # Store B with retry_on_miss=True should find it
        assert store_b.exists(token_id, retry_on_miss=True) is True

        # Cleanup
        store_a.clear()

    def test_cache_clear_on_store_clear(self, vault_client: VaultClient, unique_prefix: str):
        """Test that clear() also clears the cache."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)
        store.get(token_id)  # Populate cache

        assert store._get_from_cache(token_id) is not None

        store.clear()

        assert store._get_from_cache(token_id) is None
        assert len(store._cache) == 0

    def test_put_updates_cache(self, vault_client: VaultClient, unique_prefix: str):
        """Test that put() updates the cache with the new record."""
        from gofr_common.auth.tokens import TokenRecord

        store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        store.put(token_id, record)

        # Cache should be populated immediately after put
        cached = store._get_from_cache(token_id)
        assert cached is not None
        assert cached.record.groups == ["admin"]

        # Cleanup
        store.clear()

    def test_cross_instance_token_visibility(self, vault_client: VaultClient, unique_prefix: str):
        """Test that token created on one instance is visible on another (simulates auth_manager + MCP server)."""
        from gofr_common.auth.tokens import TokenRecord

        # Simulate auth_manager creating a token
        auth_manager_store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        # Simulate MCP server's token store (created at server startup, before the token exists)
        mcp_server_store = VaultTokenStore(vault_client, path_prefix=unique_prefix, cache_ttl=300)

        # auth_manager creates a new token
        token_id = str(uuid4())
        record = TokenRecord.create(
            groups=["us_sales"],
            expires_at=datetime.utcnow() + timedelta(days=30),
            name="test-api-token",
        )
        auth_manager_store.put(token_id, record)

        # MCP server should be able to find this token via retry-on-miss
        # This is the key scenario we fixed
        assert mcp_server_store.exists(token_id) is True

        retrieved = mcp_server_store.get(token_id)
        assert retrieved is not None
        assert retrieved.name == "test-api-token"
        assert retrieved.groups == ["us_sales"]

        # Cleanup
        auth_manager_store.clear()
