"""Tests for gofr_common.auth.groups module."""

import os
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from gofr_common.auth.backends import VaultClient, VaultConfig, VaultGroupStore
from gofr_common.auth.groups import (
    RESERVED_GROUPS,
    DuplicateGroupError,
    Group,
    GroupNotFoundError,
    GroupRegistry,
    ReservedGroupError,
)


def _create_vault_registry() -> GroupRegistry:
    vault_url = os.environ.get("GOFR_VAULT_URL")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN")
    if not vault_url or not vault_token:
        raise RuntimeError(
            "Vault test configuration missing. Set GOFR_VAULT_URL and GOFR_VAULT_TOKEN."
        )

    client = VaultClient(VaultConfig(url=vault_url, token=vault_token))
    path_prefix = f"gofr/tests/{uuid4()}"
    store = VaultGroupStore(client, path_prefix=path_prefix)
    return GroupRegistry(store=store)

# ============================================================================
# Test Group dataclass
# ============================================================================


class TestGroup:
    """Tests for the Group dataclass."""

    def test_group_creation_minimal(self):
        """Test creating a Group with minimal fields."""
        group_id = uuid4()
        group = Group(id=group_id, name="test-group")

        assert group.id == group_id
        assert group.name == "test-group"
        assert group.description is None
        assert group.is_active is True
        assert group.defunct_at is None
        assert group.is_reserved is False
        assert isinstance(group.created_at, datetime)

    def test_group_creation_full(self):
        """Test creating a Group with all fields."""
        group_id = uuid4()
        created = datetime(2024, 1, 1, 12, 0, 0)
        defunct = datetime(2024, 6, 1, 12, 0, 0)

        group = Group(
            id=group_id,
            name="users",
            description="Regular users",
            is_active=False,
            created_at=created,
            defunct_at=defunct,
            is_reserved=False,
        )

        assert group.id == group_id
        assert group.name == "users"
        assert group.description == "Regular users"
        assert group.is_active is False
        assert group.created_at == created
        assert group.defunct_at == defunct
        assert group.is_reserved is False

    def test_group_to_dict(self):
        """Test serializing a Group to dictionary."""
        group_id = uuid4()
        created = datetime(2024, 1, 1, 12, 0, 0)

        group = Group(
            id=group_id,
            name="admin",
            description="Admins",
            is_active=True,
            created_at=created,
            defunct_at=None,
            is_reserved=True,
        )

        data = group.to_dict()

        assert data["id"] == str(group_id)
        assert data["name"] == "admin"
        assert data["description"] == "Admins"
        assert data["is_active"] is True
        assert data["created_at"] == "2024-01-01T12:00:00"
        assert data["defunct_at"] is None
        assert data["is_reserved"] is True

    def test_group_to_dict_with_defunct(self):
        """Test serializing a defunct Group."""
        group_id = uuid4()
        defunct = datetime(2024, 6, 15, 10, 30, 0)

        group = Group(
            id=group_id,
            name="old-group",
            is_active=False,
            defunct_at=defunct,
        )

        data = group.to_dict()

        assert data["defunct_at"] == "2024-06-15T10:30:00"
        assert data["is_active"] is False

    def test_group_from_dict(self):
        """Test deserializing a Group from dictionary."""
        group_id = uuid4()
        data = {
            "id": str(group_id),
            "name": "users",
            "description": "User group",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00",
            "defunct_at": None,
            "is_reserved": False,
        }

        group = Group.from_dict(data)

        assert group.id == group_id
        assert group.name == "users"
        assert group.description == "User group"
        assert group.is_active is True
        assert group.created_at == datetime(2024, 1, 1, 0, 0, 0)
        assert group.defunct_at is None
        assert group.is_reserved is False

    def test_group_from_dict_with_defunct(self):
        """Test deserializing a defunct Group."""
        group_id = uuid4()
        data = {
            "id": str(group_id),
            "name": "old",
            "created_at": "2024-01-01T00:00:00",
            "defunct_at": "2024-06-01T12:00:00",
            "is_active": False,
        }

        group = Group.from_dict(data)

        assert group.is_active is False
        assert group.defunct_at == datetime(2024, 6, 1, 12, 0, 0)

    def test_group_roundtrip(self):
        """Test that to_dict/from_dict is a perfect roundtrip."""
        original = Group(
            id=uuid4(),
            name="roundtrip",
            description="Test roundtrip",
            is_active=True,
            created_at=datetime(2024, 3, 15, 8, 30, 45),
            defunct_at=None,
            is_reserved=False,
        )

        data = original.to_dict()
        restored = Group.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.is_active == original.is_active
        assert restored.created_at == original.created_at
        assert restored.defunct_at == original.defunct_at
        assert restored.is_reserved == original.is_reserved


# ============================================================================
# Test GroupRegistry - Vault Mode
# ============================================================================


class TestGroupRegistryVault:
    """Tests for GroupRegistry with Vault storage."""

    def test_registry_init_memory(self):
        """Test initializing registry in memory mode."""
        registry = _create_vault_registry()

        # Should have reserved groups
        assert registry.get_group_by_name("public") is not None
        assert registry.get_group_by_name("admin") is not None

    def test_reserved_groups_created(self):
        """Test that reserved groups are automatically created."""
        registry = _create_vault_registry()

        public = registry.get_group_by_name("public")
        admin = registry.get_group_by_name("admin")

        assert public is not None
        assert public.is_reserved is True
        assert public.is_active is True

        assert admin is not None
        assert admin.is_reserved is True
        assert admin.is_active is True

    def test_reserved_groups_constant(self):
        """Test RESERVED_GROUPS constant contains expected values."""
        assert "public" in RESERVED_GROUPS
        assert "admin" in RESERVED_GROUPS
        assert len(RESERVED_GROUPS) == 2

    def test_create_group(self):
        """Test creating a new group."""
        registry = _create_vault_registry()

        group = registry.create_group("users", "Regular users")

        assert group.name == "users"
        assert group.description == "Regular users"
        assert group.is_active is True
        assert group.is_reserved is False
        assert isinstance(group.id, UUID)

    def test_create_group_without_description(self):
        """Test creating a group without description."""
        registry = _create_vault_registry()

        group = registry.create_group("minimal")

        assert group.name == "minimal"
        assert group.description is None

    def test_create_group_reserved_name_raises(self):
        """Test that creating a group with reserved name raises error."""
        registry = _create_vault_registry()

        with pytest.raises(ReservedGroupError) as exc_info:
            registry.create_group("public")

        assert "reserved name" in str(exc_info.value).lower()

    def test_create_group_reserved_name_admin_raises(self):
        """Test that creating 'admin' group raises error."""
        registry = _create_vault_registry()

        with pytest.raises(ReservedGroupError):
            registry.create_group("admin")

    def test_create_group_duplicate_raises(self):
        """Test that creating duplicate group raises error."""
        registry = _create_vault_registry()
        registry.create_group("users")

        with pytest.raises(DuplicateGroupError) as exc_info:
            registry.create_group("users")

        assert "already exists" in str(exc_info.value).lower()

    def test_get_group_by_id(self):
        """Test getting a group by UUID."""
        registry = _create_vault_registry()
        created = registry.create_group("test-group")

        found = registry.get_group(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.name == "test-group"

    def test_get_group_by_id_not_found(self):
        """Test getting non-existent group by UUID returns None."""
        registry = _create_vault_registry()

        found = registry.get_group(uuid4())

        assert found is None

    def test_get_group_by_name(self):
        """Test getting a group by name."""
        registry = _create_vault_registry()
        registry.create_group("my-group")

        found = registry.get_group_by_name("my-group")

        assert found is not None
        assert found.name == "my-group"

    def test_get_group_by_name_not_found(self):
        """Test getting non-existent group by name returns None."""
        registry = _create_vault_registry()

        found = registry.get_group_by_name("nonexistent")

        assert found is None

    def test_list_groups(self):
        """Test listing active groups."""
        registry = _create_vault_registry()
        registry.create_group("group1")
        registry.create_group("group2")

        groups = registry.list_groups()

        # Should include reserved groups + created groups
        names = {g.name for g in groups}
        assert "public" in names
        assert "admin" in names
        assert "group1" in names
        assert "group2" in names
        assert len(groups) == 4

    def test_list_groups_excludes_defunct(self):
        """Test that list_groups excludes defunct groups by default."""
        registry = _create_vault_registry()
        group = registry.create_group("to-defunct")
        registry.make_defunct(group.id)

        groups = registry.list_groups()

        names = {g.name for g in groups}
        assert "to-defunct" not in names

    def test_list_groups_include_defunct(self):
        """Test listing all groups including defunct."""
        registry = _create_vault_registry()
        group = registry.create_group("to-defunct")
        registry.make_defunct(group.id)

        groups = registry.list_groups(include_defunct=True)

        names = {g.name for g in groups}
        assert "to-defunct" in names

    def test_make_defunct(self):
        """Test making a group defunct."""
        registry = _create_vault_registry()
        group = registry.create_group("temp-group")

        result = registry.make_defunct(group.id)

        assert result is True
        updated = registry.get_group(group.id)
        assert updated is not None
        assert updated.is_active is False
        assert updated.defunct_at is not None

    def test_make_defunct_not_found(self):
        """Test making non-existent group defunct raises error."""
        registry = _create_vault_registry()

        with pytest.raises(GroupNotFoundError):
            registry.make_defunct(uuid4())

    def test_make_defunct_reserved_raises(self):
        """Test that making reserved group defunct raises error."""
        registry = _create_vault_registry()
        public = registry.get_group_by_name("public")
        assert public is not None

        with pytest.raises(ReservedGroupError) as exc_info:
            registry.make_defunct(public.id)

        assert "reserved" in str(exc_info.value).lower()

    def test_make_defunct_admin_reserved_raises(self):
        """Test that making admin group defunct raises error."""
        registry = _create_vault_registry()
        admin = registry.get_group_by_name("admin")
        assert admin is not None

        with pytest.raises(ReservedGroupError):
            registry.make_defunct(admin.id)

    def test_make_defunct_already_defunct(self):
        """Test making already defunct group returns False."""
        registry = _create_vault_registry()
        group = registry.create_group("already-defunct")
        registry.make_defunct(group.id)

        result = registry.make_defunct(group.id)

        assert result is False

    def test_get_reserved_group(self):
        """Test getting reserved group by name."""
        registry = _create_vault_registry()

        public = registry.get_reserved_group("public")
        admin = registry.get_reserved_group("admin")

        assert public.name == "public"
        assert public.is_reserved is True
        assert admin.name == "admin"
        assert admin.is_reserved is True

    def test_get_reserved_group_invalid_name(self):
        """Test getting non-reserved group raises ValueError."""
        registry = _create_vault_registry()

        with pytest.raises(ValueError) as exc_info:
            registry.get_reserved_group("users")

        assert "not a reserved group" in str(exc_info.value).lower()


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestGroupRegistryEdgeCases:
    """Edge case tests for GroupRegistry."""

    def test_group_name_case_sensitivity(self):
        """Test that group names are case-sensitive."""
        registry = _create_vault_registry()

        # These should be different groups
        group1 = registry.create_group("Users")
        group2 = registry.create_group("users")

        assert group1.id != group2.id

    def test_reserved_group_case_insensitive_check(self):
        """Test that reserved name check is case-insensitive."""
        registry = _create_vault_registry()

        # Should reject variations of reserved names
        with pytest.raises(ReservedGroupError):
            registry.create_group("PUBLIC")

        with pytest.raises(ReservedGroupError):
            registry.create_group("Admin")

    def test_many_groups(self):
        """Test registry handles many groups."""
        registry = _create_vault_registry()

        # Create 100 groups
        for i in range(100):
            registry.create_group(f"group-{i}")

        groups = registry.list_groups()
        assert len(groups) == 102  # 100 + public + admin

    def test_defunct_group_still_retrievable(self):
        """Test that defunct groups can still be retrieved by ID."""
        registry = _create_vault_registry()
        group = registry.create_group("defunct-test")
        registry.make_defunct(group.id)

        # Should still be retrievable
        found = registry.get_group(group.id)
        assert found is not None
        assert found.is_active is False

    def test_defunct_group_retrievable_by_name(self):
        """Test that defunct groups can be retrieved by name."""
        registry = _create_vault_registry()
        group = registry.create_group("defunct-by-name")
        registry.make_defunct(group.id)

        found = registry.get_group_by_name("defunct-by-name")
        assert found is not None
        assert found.is_active is False
