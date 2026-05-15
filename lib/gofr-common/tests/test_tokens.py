"""Tests for gofr_common.auth.tokens module."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from gofr_common.auth.tokens import TokenInfo, TokenRecord

# ============================================================================
# Test TokenRecord dataclass
# ============================================================================


class TestTokenRecord:
    """Tests for the TokenRecord dataclass."""

    def test_token_record_creation_minimal(self):
        """Test creating a TokenRecord with minimal fields."""
        token_id = uuid4()
        record = TokenRecord(id=token_id, groups=["admin"])

        assert record.id == token_id
        assert record.name is None
        assert record.groups == ["admin"]
        assert record.status == "active"
        assert record.expires_at is None
        assert record.revoked_at is None
        assert record.fingerprint is None
        assert isinstance(record.created_at, datetime)

    def test_token_record_creation_with_name(self):
        """TokenRecord accepts optional name."""
        token_id = uuid4()
        record = TokenRecord(id=token_id, name="ci", groups=["admin"])

        assert record.name == "ci"
        assert record.id == token_id

    def test_token_record_creation_full(self):
        """Test creating a TokenRecord with all fields."""
        token_id = uuid4()
        created = datetime(2024, 1, 1, 12, 0, 0)
        expires = datetime(2024, 12, 31, 23, 59, 59)
        revoked = datetime(2024, 6, 1, 12, 0, 0)

        record = TokenRecord(
            id=token_id,
            groups=["admin", "users"],
            status="revoked",
            created_at=created,
            expires_at=expires,
            revoked_at=revoked,
            fingerprint="abc123",
        )

        assert record.id == token_id
        assert record.groups == ["admin", "users"]
        assert record.status == "revoked"
        assert record.created_at == created
        assert record.expires_at == expires
        assert record.revoked_at == revoked
        assert record.fingerprint == "abc123"

    def test_token_record_is_expired_no_expiry(self):
        """Test is_expired when no expiry is set."""
        record = TokenRecord(id=uuid4(), groups=["admin"])
        assert record.is_expired is False

    def test_token_record_is_expired_future(self):
        """Test is_expired when expiry is in the future."""
        future = datetime.utcnow() + timedelta(days=30)
        record = TokenRecord(id=uuid4(), groups=["admin"], expires_at=future)
        assert record.is_expired is False

    def test_token_record_is_expired_past(self):
        """Test is_expired when expiry is in the past."""
        past = datetime.utcnow() - timedelta(days=1)
        record = TokenRecord(id=uuid4(), groups=["admin"], expires_at=past)
        assert record.is_expired is True

    def test_token_record_is_valid_active_no_expiry(self):
        """Test is_valid for active token without expiry."""
        record = TokenRecord(id=uuid4(), groups=["admin"], status="active")
        assert record.is_valid is True

    def test_token_record_is_valid_active_future_expiry(self):
        """Test is_valid for active token with future expiry."""
        future = datetime.utcnow() + timedelta(days=30)
        record = TokenRecord(id=uuid4(), groups=["admin"], status="active", expires_at=future)
        assert record.is_valid is True

    def test_token_record_is_valid_active_expired(self):
        """Test is_valid for active but expired token."""
        past = datetime.utcnow() - timedelta(days=1)
        record = TokenRecord(id=uuid4(), groups=["admin"], status="active", expires_at=past)
        assert record.is_valid is False

    def test_token_record_is_valid_revoked(self):
        """Test is_valid for revoked token."""
        record = TokenRecord(id=uuid4(), groups=["admin"], status="revoked")
        assert record.is_valid is False

    def test_token_record_is_valid_revoked_not_expired(self):
        """Test is_valid for revoked token that hasn't expired."""
        future = datetime.utcnow() + timedelta(days=30)
        record = TokenRecord(id=uuid4(), groups=["admin"], status="revoked", expires_at=future)
        assert record.is_valid is False

    def test_token_record_to_dict(self):
        """Test serializing TokenRecord to dictionary."""
        token_id = uuid4()
        created = datetime(2024, 1, 1, 12, 0, 0)
        expires = datetime(2024, 12, 31, 23, 59, 59)

        record = TokenRecord(
            id=token_id,
            name="deploy",
            groups=["admin", "users"],
            status="active",
            created_at=created,
            expires_at=expires,
            fingerprint="fp123",
        )

        data = record.to_dict()

        assert data["id"] == str(token_id)
        assert data["name"] == "deploy"
        assert data["groups"] == ["admin", "users"]
        assert data["status"] == "active"
        assert data["created_at"] == "2024-01-01T12:00:00"
        assert data["expires_at"] == "2024-12-31T23:59:59"
        assert data["revoked_at"] is None
        assert data["fingerprint"] == "fp123"

    def test_token_record_to_dict_revoked(self):
        """Test serializing revoked TokenRecord."""
        token_id = uuid4()
        revoked = datetime(2024, 6, 15, 10, 30, 0)

        record = TokenRecord(
            id=token_id,
            groups=["users"],
            status="revoked",
            revoked_at=revoked,
        )

        data = record.to_dict()

        assert data["status"] == "revoked"
        assert data["revoked_at"] == "2024-06-15T10:30:00"

    def test_token_record_from_dict(self):
        """Test deserializing TokenRecord from dictionary."""
        token_id = uuid4()
        data = {
            "id": str(token_id),
            "name": "api",
            "groups": ["admin", "users"],
            "status": "active",
            "created_at": "2024-01-01T00:00:00",
            "expires_at": "2024-12-31T23:59:59",
            "revoked_at": None,
            "fingerprint": "fp456",
        }

        record = TokenRecord.from_dict(data)

        assert record.id == token_id
        assert record.name == "api"
        assert record.groups == ["admin", "users"]
        assert record.status == "active"
        assert record.created_at == datetime(2024, 1, 1, 0, 0, 0)
        assert record.expires_at == datetime(2024, 12, 31, 23, 59, 59)
        assert record.revoked_at is None
        assert record.fingerprint == "fp456"

    def test_token_record_from_dict_revoked(self):
        """Test deserializing revoked TokenRecord."""
        token_id = uuid4()
        data = {
            "id": str(token_id),
            "groups": ["users"],
            "status": "revoked",
            "created_at": "2024-01-01T00:00:00",
            "revoked_at": "2024-06-01T12:00:00",
        }

        record = TokenRecord.from_dict(data)

        assert record.status == "revoked"
        assert record.revoked_at == datetime(2024, 6, 1, 12, 0, 0)

    def test_token_record_roundtrip(self):
        """Test that to_dict/from_dict is a perfect roundtrip."""
        original = TokenRecord(
            id=uuid4(),
            groups=["admin", "users", "special"],
            status="active",
            created_at=datetime(2024, 3, 15, 8, 30, 45),
            expires_at=datetime(2025, 3, 15, 8, 30, 45),
            fingerprint="device-abc",
        )

        data = original.to_dict()
        restored = TokenRecord.from_dict(data)

        assert restored.id == original.id
        assert restored.groups == original.groups
        assert restored.status == original.status
        assert restored.created_at == original.created_at
        assert restored.expires_at == original.expires_at
        assert restored.revoked_at == original.revoked_at
        assert restored.fingerprint == original.fingerprint

    def test_token_record_create_factory(self):
        """Test TokenRecord.create factory method."""
        expires = datetime(2025, 1, 1)
        record = TokenRecord.create(
            groups=["admin", "users"],
            expires_at=expires,
            fingerprint="fp789",
        )

        assert isinstance(record.id, UUID)
        assert record.groups == ["admin", "users"]
        assert record.status == "active"
        assert record.expires_at == expires
        assert record.fingerprint == "fp789"
        assert record.revoked_at is None

    def test_token_record_create_minimal(self):
        """Test TokenRecord.create with minimal args."""
        record = TokenRecord.create(groups=["public"])

        assert isinstance(record.id, UUID)
        assert record.groups == ["public"]
        assert record.status == "active"
        assert record.expires_at is None
        assert record.fingerprint is None

    def test_token_record_multiple_groups(self):
        """Test TokenRecord with many groups."""
        groups = [f"group-{i}" for i in range(20)]
        record = TokenRecord(id=uuid4(), groups=groups)

        assert len(record.groups) == 20
        assert "group-0" in record.groups
        assert "group-19" in record.groups


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
            groups=["admin", "users"],
            expires_at=expires,
            issued_at=now,
        )

        assert info.token == "test-token"
        assert info.groups == ["admin", "users"]
        assert info.expires_at == expires
        assert info.issued_at == now

    def test_token_info_no_expiry(self):
        """Test TokenInfo without expiry."""
        now = datetime.utcnow()

        info = TokenInfo(
            token="test-token",
            groups=["admin"],
            expires_at=None,
            issued_at=now,
        )

        assert info.expires_at is None

    def test_token_info_has_group_true(self):
        """Test has_group returns True for included group."""
        info = TokenInfo(
            token="test",
            groups=["admin", "users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_group("admin") is True
        assert info.has_group("users") is True

    def test_token_info_has_group_false(self):
        """Test has_group returns False for missing group."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_group("admin") is False
        assert info.has_group("nonexistent") is False

    def test_token_info_has_any_group_true(self):
        """Test has_any_group returns True when any group matches."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_any_group(["admin", "users"]) is True
        assert info.has_any_group(["users", "special"]) is True

    def test_token_info_has_any_group_false(self):
        """Test has_any_group returns False when no groups match."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_any_group(["admin", "special"]) is False

    def test_token_info_has_any_group_empty(self):
        """Test has_any_group with empty list."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_any_group([]) is False

    def test_token_info_has_all_groups_true(self):
        """Test has_all_groups returns True when all groups present."""
        info = TokenInfo(
            token="test",
            groups=["admin", "users", "special"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_all_groups(["admin"]) is True
        assert info.has_all_groups(["admin", "users"]) is True
        assert info.has_all_groups(["admin", "users", "special"]) is True

    def test_token_info_has_all_groups_false(self):
        """Test has_all_groups returns False when groups missing."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert info.has_all_groups(["admin"]) is False
        assert info.has_all_groups(["users", "admin"]) is False

    def test_token_info_has_all_groups_empty(self):
        """Test has_all_groups with empty list returns True."""
        info = TokenInfo(
            token="test",
            groups=["users"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        # Empty set is subset of any set
        assert info.has_all_groups([]) is True

    def test_token_info_single_group(self):
        """Test TokenInfo with single group."""
        info = TokenInfo(
            token="test",
            groups=["admin"],
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert len(info.groups) == 1
        assert info.has_group("admin")

    def test_token_info_many_groups(self):
        """Test TokenInfo with many groups."""
        groups = [f"group-{i}" for i in range(50)]
        info = TokenInfo(
            token="test",
            groups=groups,
            expires_at=None,
            issued_at=datetime.utcnow(),
        )

        assert len(info.groups) == 50
        assert info.has_group("group-0")
        assert info.has_group("group-49")
        assert info.has_all_groups(["group-10", "group-20", "group-30"])
