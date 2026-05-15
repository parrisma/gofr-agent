"""Tests for storage backend protocols and Vault implementations."""

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from gofr_common.auth.backends import (
    GroupStore,
    StorageError,
    StorageUnavailableError,
    TokenStore,
    VaultAuthenticationError,
    VaultClient,
    VaultConfig,
    VaultConfigError,
    VaultConnectionError,
    VaultError,
    VaultGroupStore,
    VaultNotFoundError,
    VaultPermissionError,
    VaultTokenStore,
)
from gofr_common.auth.groups import Group
from gofr_common.auth.tokens import TokenRecord


def _build_vault_client() -> VaultClient:
    vault_url = os.environ.get("GOFR_VAULT_URL")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN")
    if not vault_url or not vault_token:
        raise RuntimeError(
            "Vault test configuration missing. Set GOFR_VAULT_URL and GOFR_VAULT_TOKEN."
        )
    return VaultClient(VaultConfig(url=vault_url, token=vault_token))


def _new_prefix() -> str:
    return f"gofr/tests/{uuid4()}"


@pytest.fixture()
def vault_client() -> VaultClient:
    return _build_vault_client()


@pytest.fixture()
def token_store(vault_client: VaultClient) -> VaultTokenStore:
    store = VaultTokenStore(vault_client, path_prefix=_new_prefix())
    yield store
    store.clear()


@pytest.fixture()
def group_store(vault_client: VaultClient) -> VaultGroupStore:
    store = VaultGroupStore(vault_client, path_prefix=_new_prefix())
    yield store
    store.clear()


class TestTokenStoreProtocol:
    """Tests for TokenStore protocol definition."""

    def test_vault_store_is_token_store(self, token_store):
        """VaultTokenStore implements TokenStore protocol."""
        assert isinstance(token_store, TokenStore)

    def test_protocol_has_required_methods(self):
        """TokenStore protocol defines all required methods."""
        assert hasattr(TokenStore, "get")
        assert hasattr(TokenStore, "get_by_name")
        assert hasattr(TokenStore, "put")
        assert hasattr(TokenStore, "list_all")
        assert hasattr(TokenStore, "exists")
        assert hasattr(TokenStore, "exists_name")
        assert hasattr(TokenStore, "reload")


class TestGroupStoreProtocol:
    """Tests for GroupStore protocol definition."""

    def test_vault_store_is_group_store(self, group_store):
        """VaultGroupStore implements GroupStore protocol."""
        assert isinstance(group_store, GroupStore)

    def test_protocol_has_required_methods(self):
        """GroupStore protocol defines all required methods."""
        assert hasattr(GroupStore, "get")
        assert hasattr(GroupStore, "get_by_name")
        assert hasattr(GroupStore, "put")
        assert hasattr(GroupStore, "list_all")
        assert hasattr(GroupStore, "exists")
        assert hasattr(GroupStore, "reload")


class TestStorageExceptions:
    """Tests for storage exceptions."""

    def test_storage_error_is_exception(self):
        assert issubclass(StorageError, Exception)

    def test_storage_unavailable_is_storage_error(self):
        assert issubclass(StorageUnavailableError, StorageError)

    def test_vault_exception_hierarchy(self):
        assert issubclass(VaultConnectionError, VaultError)
        assert issubclass(VaultAuthenticationError, VaultError)
        assert issubclass(VaultPermissionError, VaultError)
        assert issubclass(VaultNotFoundError, VaultError)
        assert issubclass(VaultConfigError, Exception)


class TestVaultTokenStore:
    """Tests for VaultTokenStore implementation."""

    def test_put_and_get(self, token_store):
        record = TokenRecord.create(
            groups=["admin"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
            name="deploy-token",
        )
        token_id = str(record.id)

        token_store.put(token_id, record)

        retrieved = token_store.get(token_id)
        assert retrieved is not None
        assert retrieved.id == record.id
        assert retrieved.groups == record.groups

    def test_get_by_name(self, token_store):
        record = TokenRecord.create(groups=["admin"], name="ci")
        token_store.put(str(record.id), record)

        retrieved = token_store.get_by_name("ci")
        assert retrieved is not None
        assert retrieved.id == record.id

    def test_exists(self, token_store):
        record = TokenRecord.create(groups=["admin"], name="exists-test")
        token_store.put(str(record.id), record)
        assert token_store.exists(str(record.id)) is True

    def test_list_all(self, token_store):
        records = [
            TokenRecord.create(groups=["admin"]),
            TokenRecord.create(groups=["users"]),
        ]
        for record in records:
            token_store.put(str(record.id), record)

        result = token_store.list_all()
        assert len(result) == 2


class TestVaultGroupStore:
    """Tests for VaultGroupStore implementation."""

    def test_put_and_get(self, group_store):
        group = Group(id=uuid4(), name="users", description="Users", is_active=True)
        group_store.put(str(group.id), group)

        retrieved = group_store.get(str(group.id))
        assert retrieved is not None
        assert retrieved.id == group.id
        assert retrieved.name == group.name

    def test_get_by_name(self, group_store):
        group = Group(id=uuid4(), name="ops", description="Ops", is_active=True)
        group_store.put(str(group.id), group)

        retrieved = group_store.get_by_name("ops")
        assert retrieved is not None
        assert retrieved.id == group.id

    def test_list_all(self, group_store):
        group1 = Group(id=uuid4(), name="g1", description=None, is_active=True)
        group2 = Group(id=uuid4(), name="g2", description=None, is_active=True)
        group_store.put(str(group1.id), group1)
        group_store.put(str(group2.id), group2)

        result = group_store.list_all()
        assert len(result) == 2
