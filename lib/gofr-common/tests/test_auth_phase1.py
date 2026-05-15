"""Phase 1 Tests: Group validation at verification time.

These tests verify the validate_groups parameter functionality added to
AuthService.verify_token() and AuthProvider.verify_token_strict().
"""

import os
from uuid import uuid4

import pytest

from gofr_common.auth import (
    AuthService,
    GroupRegistry,
    InvalidGroupError,
    JwtSecretProvider,
)
from gofr_common.auth.backends import VaultClient, VaultConfig, VaultGroupStore, VaultTokenStore


def create_memory_auth(secret_key: str = "test-secret") -> AuthService:
    """Create an AuthService with Vault-backed stores for testing."""
    vault_url = os.environ.get("GOFR_VAULT_URL")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN")
    if not vault_url or not vault_token:
        raise RuntimeError(
            "Vault test configuration missing. Set GOFR_VAULT_URL and GOFR_VAULT_TOKEN."
        )

    vault_client = VaultClient(VaultConfig(url=vault_url, token=vault_token))
    path_prefix = f"gofr/tests/{uuid4()}"
    token_store = VaultTokenStore(vault_client, path_prefix=path_prefix)
    group_store = VaultGroupStore(vault_client, path_prefix=path_prefix)
    group_registry = GroupRegistry(store=group_store)

    from unittest.mock import MagicMock

    mock_vault = MagicMock(spec=VaultClient)
    mock_vault.read_secret.return_value = {"value": secret_key}
    secret_provider = JwtSecretProvider(vault_client=mock_vault)
    return AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_provider=secret_provider,
    )


class TestGroupValidationOnVerify:
    """Phase 1: Group validation at verification time."""

    def test_verify_passes_without_validation_after_group_defunct(self):
        """Token still works when validate_groups=False (default)."""
        auth = create_memory_auth()
        group = auth.groups.create_group("temp-group")
        token = auth.create_token(groups=["temp-group"])

        # Make group defunct
        auth.groups.make_defunct(group.id)

        # Should still verify with default settings
        info = auth.verify_token(token, validate_groups=False)
        assert "temp-group" in info.groups

    def test_verify_fails_with_validation_after_group_defunct(self):
        """Token fails verification when validate_groups=True and group defunct."""
        auth = create_memory_auth()
        group = auth.groups.create_group("temp-group")
        token = auth.create_token(groups=["temp-group"])

        auth.groups.make_defunct(group.id)

        with pytest.raises(InvalidGroupError, match="defunct"):
            auth.verify_token(token, validate_groups=True)

    def test_verify_fails_with_validation_when_group_missing(self):
        """Token fails if group no longer exists in registry."""
        auth = create_memory_auth()
        auth.groups.create_group("ephemeral")
        token = auth.create_token(groups=["ephemeral"])

        # Simulate group disappearing by clearing and re-bootstrapping
        auth.groups._store.clear()
        auth.groups.ensure_reserved_groups()  # Re-add reserved only

        with pytest.raises(InvalidGroupError, match="does not exist"):
            auth.verify_token(token, validate_groups=True)

    def test_reserved_groups_always_valid(self):
        """Reserved groups (admin, public) always pass validation."""
        auth = create_memory_auth()
        token = auth.create_token(groups=["admin"])

        # Should always work - admin is reserved and can't be defunct
        info = auth.verify_token(token, validate_groups=True)
        assert "admin" in info.groups

    def test_validate_groups_default_is_false(self):
        """Default behavior doesn't validate groups (backward compatible)."""
        auth = create_memory_auth()
        group = auth.groups.create_group("deletable")
        token = auth.create_token(groups=["deletable"])

        # Make defunct
        auth.groups.make_defunct(group.id)

        # Default call should still work
        info = auth.verify_token(token)
        assert "deletable" in info.groups

    def test_multiple_groups_all_validated(self):
        """All groups in token are checked when validate_groups=True."""
        auth = create_memory_auth()
        group1 = auth.groups.create_group("group1")
        auth.groups.create_group("group2")
        token = auth.create_token(groups=["group1", "group2"])

        # Make only one defunct
        auth.groups.make_defunct(group1.id)

        # Should fail because group1 is defunct
        with pytest.raises(InvalidGroupError, match="group1"):
            auth.verify_token(token, validate_groups=True)

    def test_mixed_reserved_and_custom_groups(self):
        """Tokens with both reserved and custom groups validate correctly."""
        auth = create_memory_auth()
        group = auth.groups.create_group("custom")
        token = auth.create_token(groups=["admin", "custom"])

        # Custom group is still active - should pass
        info = auth.verify_token(token, validate_groups=True)
        assert "admin" in info.groups
        assert "custom" in info.groups

        # Make custom defunct
        auth.groups.make_defunct(group.id)

        # Now should fail
        with pytest.raises(InvalidGroupError, match="custom"):
            auth.verify_token(token, validate_groups=True)

    def test_validate_groups_with_fingerprint(self):
        """validate_groups works alongside fingerprint validation."""
        auth = create_memory_auth()
        group = auth.groups.create_group("secure-group")

        fingerprint = "abc123fingerprint"
        token = auth.create_token(groups=["secure-group"], fingerprint=fingerprint)

        # Valid fingerprint, valid group
        info = auth.verify_token(token, fingerprint=fingerprint, validate_groups=True)
        assert "secure-group" in info.groups

        # Make group defunct
        auth.groups.make_defunct(group.id)

        # Should fail on group validation even with correct fingerprint
        with pytest.raises(InvalidGroupError):
            auth.verify_token(token, fingerprint=fingerprint, validate_groups=True)
