"""Group model and registry for multi-group authentication.

Provides a central registry of groups with support for:
- Reserved groups (public, admin) that cannot be made defunct
- Pluggable storage backends (vault)
- Soft-delete (defunct) rather than hard delete
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Optional
from uuid import UUID, uuid4

from gofr_common.logger import Logger, create_logger

from .backends import GroupStore

# Reserved group names that always exist and cannot be made defunct
RESERVED_GROUPS: FrozenSet[str] = frozenset({"public", "admin"})


@dataclass
class Group:
    """A group for access control.

    Attributes:
        id: Unique identifier for the group (UUID)
        name: Human-readable group name (unique)
        description: Optional description of the group's purpose
        is_active: Whether the group is currently active (not defunct)
        created_at: When the group was created
        defunct_at: When the group was made defunct (None if active)
        is_reserved: Whether this is a reserved system group
    """

    id: UUID
    name: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    defunct_at: Optional[datetime] = None
    is_reserved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize group to dictionary for JSON storage."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "defunct_at": self.defunct_at.isoformat() if self.defunct_at else None,
            "is_reserved": self.is_reserved,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Group:
        """Deserialize group from dictionary.

        Args:
            data: Dictionary containing group data

        Returns:
            Group instance
        """
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            description=data.get("description"),
            is_active=data.get("is_active", True),
            created_at=datetime.fromisoformat(data["created_at"]),
            defunct_at=datetime.fromisoformat(data["defunct_at"]) if data.get("defunct_at") else None,
            is_reserved=data.get("is_reserved", False),
        )


class GroupRegistryError(Exception):
    """Base exception for group registry errors."""

    pass


class ReservedGroupError(GroupRegistryError):
    """Raised when attempting invalid operations on reserved groups."""

    pass


class DuplicateGroupError(GroupRegistryError):
    """Raised when attempting to create a group with a name that already exists."""

    pass


class GroupNotFoundError(GroupRegistryError):
    """Raised when a group is not found."""

    pass


class GroupRegistry:
    """Central registry for managing groups.

    Supports pluggable storage backends via the GroupStore protocol.
    Reserved groups (public, admin) are automatically created and
    protected from being made defunct.

    Example:
        # Vault-backed storage
        registry = GroupRegistry(store=VaultGroupStore(client, path_prefix="gofr/auth"))

        # Create a group
        group = registry.create_group("users", "Regular users")

        # Get groups
        group = registry.get_group_by_name("admin")
        groups = registry.list_groups()

        # Make a group defunct (not allowed for reserved groups)
        registry.make_defunct(group.id)
    """

    def __init__(
        self,
        store: GroupStore,
        logger: Optional[Logger] = None,
        auto_bootstrap: bool = True,
    ):
        """Initialize the group registry.

        Args:
            store: GroupStore instance for storage backend (vault)
            logger: Optional logger instance
            auto_bootstrap: If True, automatically ensure reserved groups exist
        """
        if logger is not None:
            self.logger = logger
        else:
            self.logger = create_logger(name="group-registry")

        self._store = store
        self.logger.debug(
            "GroupRegistry initialized",
            store_type=type(store).__name__,
        )

        # Bootstrap reserved groups if requested
        if auto_bootstrap:
            self.ensure_reserved_groups()

    def ensure_reserved_groups(self) -> None:
        """Ensure reserved groups exist.

        Creates the public and admin groups if they don't already exist.
        This is called automatically on init with auto_bootstrap=True.
        """
        reserved_descriptions = {
            "public": "Universal access group - automatically included for all tokens",
            "admin": "Administrative access - required for group and token management",
        }

        for name in RESERVED_GROUPS:
            existing = self.get_group_by_name(name)
            if existing is None:
                group = Group(
                    id=uuid4(),
                    name=name,
                    description=reserved_descriptions.get(name),
                    is_active=True,
                    created_at=datetime.utcnow(),
                    is_reserved=True,
                )
                self._store.put(str(group.id), group)
                self.logger.info(f"Created reserved group: {name}", group_id=str(group.id))

    def create_group(self, name: str, description: Optional[str] = None) -> Group:
        """Create a new group.

        Args:
            name: Name for the group (must be unique, cannot be reserved name)
            description: Optional description

        Returns:
            The created Group

        Raises:
            ReservedGroupError: If name is a reserved group name
            DuplicateGroupError: If a group with this name already exists
        """
        # Check for reserved names
        if name.lower() in RESERVED_GROUPS:
            raise ReservedGroupError(f"Cannot create group with reserved name: {name}")

        # Check for duplicates
        existing = self.get_group_by_name(name)
        if existing is not None:
            raise DuplicateGroupError(f"Group already exists: {name}")

        group = Group(
            id=uuid4(),
            name=name,
            description=description,
            is_active=True,
            created_at=datetime.utcnow(),
            is_reserved=False,
        )

        self._store.put(str(group.id), group)

        self.logger.info(
            "Group created",
            group_id=str(group.id),
            _name=name,  # Use _name to avoid conflict with logger's name param
        )

        return group

    def get_group(self, group_id: UUID) -> Optional[Group]:
        """Get a group by its UUID.

        Args:
            group_id: The UUID of the group

        Returns:
            The Group if found, None otherwise
        """
        if self._store.exists(str(group_id)):
            return self._store.get(str(group_id))
        return None

    def get_group_by_name(self, name: str) -> Optional[Group]:
        """Get a group by its name.

        Args:
            name: The name of the group

        Returns:
            The Group if found, None otherwise
        """
        return self._store.get_by_name(name)

    def list_groups(self, include_defunct: bool = False) -> List[Group]:
        """List all groups.

        Args:
            include_defunct: If True, include defunct groups

        Returns:
            List of groups
        """
        all_groups = list(self._store.list_all().values())
        if include_defunct:
            return all_groups
        return [g for g in all_groups if g.is_active]

    def make_defunct(self, group_id: UUID) -> bool:
        """Mark a group as defunct (soft delete).

        Args:
            group_id: The UUID of the group to make defunct

        Returns:
            True if the group was made defunct

        Raises:
            GroupNotFoundError: If the group doesn't exist
            ReservedGroupError: If attempting to make a reserved group defunct
        """
        group = self.get_group(group_id)
        if group is None:
            raise GroupNotFoundError(f"Group not found: {group_id}")

        if group.is_reserved:
            raise ReservedGroupError(f"Cannot make reserved group defunct: {group.name}")

        if not group.is_active:
            self.logger.debug("Group already defunct", group_id=str(group_id))
            return False

        group.is_active = False
        group.defunct_at = datetime.utcnow()
        # Update in store
        self._store.put(str(group_id), group)

        self.logger.info(
            "Group made defunct",
            group_id=str(group_id),
            name=group.name,
        )

        return True

    def get_reserved_group(self, name: str) -> Group:
        """Get a reserved group by name.

        Convenience method that asserts the group exists.

        Args:
            name: Reserved group name ('public' or 'admin')

        Returns:
            The Group

        Raises:
            ValueError: If name is not a reserved group name
            RuntimeError: If reserved group doesn't exist (shouldn't happen)
        """
        if name not in RESERVED_GROUPS:
            raise ValueError(f"Not a reserved group: {name}")

        group = self.get_group_by_name(name)
        if group is None:
            raise RuntimeError(f"Reserved group missing: {name}")

        return group
