"""Token models for multi-group authentication.

Provides data structures for token records and token information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4


@dataclass
class TokenRecord:
    """Persistent record of a token in the token store.

    This represents the server-side state of a token, including its
    status and revocation information. Tokens are never deleted,
    only revoked.

    Attributes:
        id: Unique identifier for the token (UUID)
        name: Optional human-friendly label for the token
        groups: List of group names this token grants access to
        status: Current status - "active" or "revoked"
        created_at: When the token was created
        expires_at: When the token expires (None = never expires)
        revoked_at: When the token was revoked (None if active)
        fingerprint: Optional device fingerprint for token binding
    """

    id: UUID
    groups: List[str]
    name: Optional[str] = None
    status: Literal["active", "revoked"] = "active"
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    fingerprint: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired.

        Returns:
            True if expires_at is set and in the past
        """
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if the token is currently valid.

        A token is valid if it's active and not expired.

        Returns:
            True if status is "active" and not expired
        """
        return self.status == "active" and not self.is_expired

    def to_dict(self) -> Dict[str, Any]:
        """Serialize token record to dictionary for JSON storage."""
        return {
            "id": str(self.id),
            "name": self.name,
            "groups": self.groups,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TokenRecord:
        """Deserialize token record from dictionary.

        Args:
            data: Dictionary containing token record data

        Returns:
            TokenRecord instance
        """
        return cls(
            id=UUID(data["id"]),
            name=data.get("name"),
            groups=data["groups"],
            status=data.get("status", "active"),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            revoked_at=datetime.fromisoformat(data["revoked_at"]) if data.get("revoked_at") else None,
            fingerprint=data.get("fingerprint"),
        )

    @classmethod
    def create(
        cls,
        groups: List[str],
        name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        fingerprint: Optional[str] = None,
    ) -> TokenRecord:
        """Factory method to create a new token record.

        Args:
            groups: List of group names
            expires_at: Optional expiration time
            fingerprint: Optional device fingerprint

        Returns:
            New TokenRecord with generated UUID
        """
        return cls(
            id=uuid4(),
            name=name,
            groups=groups,
            status="active",
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            fingerprint=fingerprint,
        )


@dataclass
class TokenInfo:
    """Information extracted from a verified JWT token.

    This is the public-facing token information returned when
    verifying a token. It contains the token string and its
    associated metadata.

    Attributes:
        token: The JWT token string
        groups: List of group names this token grants access to
        expires_at: When the token expires (None = never expires)
        issued_at: When the token was issued
    """

    token: str
    groups: List[str]
    expires_at: Optional[datetime]
    issued_at: datetime

    def has_group(self, group_name: str) -> bool:
        """Check if token has access to a specific group.

        Args:
            group_name: Name of the group to check

        Returns:
            True if the group is in this token's groups list
        """
        return group_name in self.groups

    def has_any_group(self, group_names: List[str]) -> bool:
        """Check if token has access to any of the specified groups.

        Args:
            group_names: List of group names to check

        Returns:
            True if any group is in this token's groups list
        """
        return bool(set(self.groups) & set(group_names))

    def has_all_groups(self, group_names: List[str]) -> bool:
        """Check if token has access to all of the specified groups.

        Args:
            group_names: List of group names to check

        Returns:
            True if all groups are in this token's groups list
        """
        return set(group_names).issubset(set(self.groups))
