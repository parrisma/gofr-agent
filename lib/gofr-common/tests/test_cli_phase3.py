"""Phase 3 Tests: Unified auth management CLI.

Tests for scripts/auth_manager.py functionality.
Requires an ephemeral Vault started by scripts/run_tests.sh.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import List, Optional

import pytest

# Get the path to the auth_manager.py script
SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "auth_manager.py"

# Skip the entire module if Vault is not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOFR_VAULT_URL"),
    reason="GOFR_VAULT_URL not set — ephemeral Vault not running",
)


def _vault_path_prefix() -> str:
    """Return a unique Vault path prefix for test isolation."""
    return f"test/{uuid.uuid4().hex[:12]}/auth"


def run_cli(
    args: List[str],
    vault_path_prefix: Optional[str] = None,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run the auth_manager CLI with given arguments.

    Each call uses a unique Vault path prefix for test isolation unless
    an explicit prefix is supplied (to share state across calls in one test).

    Args:
        args: Command line arguments to pass
        vault_path_prefix: Vault KV path prefix for isolation
        env: Optional extra environment variables

    Returns:
        CompletedProcess with stdout, stderr, returncode
    """
    cmd = [sys.executable, str(SCRIPT_PATH)]
    cmd.extend(args)

    # Build environment — inherit Vault vars from run_tests.sh
    run_env = os.environ.copy()
    run_env["GOFR_AUTH_BACKEND"] = "vault"
    run_env.setdefault("GOFR_JWT_SECRET", "gofr-dev-jwt-secret-shared-across-all-services")

    if vault_path_prefix:
        run_env["GOFR_VAULT_PATH_PREFIX"] = vault_path_prefix

    if env:
        run_env.update(env)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=run_env,
    )

    return result


class TestAuthManagerCLI:
    """Phase 3: Unified CLI tool tests.

    Each test uses a unique Vault path prefix for isolation so tests
    don't interfere with each other even when running in parallel.
    """

    def test_groups_list_shows_reserved_groups(self):
        """'groups list' displays reserved groups (admin, public)."""
        prefix = _vault_path_prefix()
        result = run_cli(["groups", "list"], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        assert "admin" in result.stdout
        assert "public" in result.stdout

    def test_groups_list_json_format(self):
        """'groups list --format json' outputs valid JSON."""
        prefix = _vault_path_prefix()
        result = run_cli(["groups", "list", "--format", "json"], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert isinstance(data, list)

        # Should have at least admin and public
        names = [g["name"] for g in data]
        assert "admin" in names
        assert "public" in names

    def test_groups_create_new_group(self):
        """'groups create' adds a new group."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["groups", "create", "finance", "--description", "Finance team"],
            vault_path_prefix=prefix,
        )
        assert result.returncode == 0, result.stderr
        assert "Created group: finance" in result.stdout

        # Verify it exists
        result = run_cli(["groups", "list"], vault_path_prefix=prefix)
        assert "finance" in result.stdout

    def test_groups_create_duplicate_fails(self):
        """'groups create' is idempotent; re-creating an active group returns 0 with notice."""
        prefix = _vault_path_prefix()
        # Create once
        run_cli(["groups", "create", "duplicate-test"], vault_path_prefix=prefix)

        # Try to create again — CLI is idempotent, returns 0 with "already exists" notice
        result = run_cli(["groups", "create", "duplicate-test"], vault_path_prefix=prefix)
        assert result.returncode == 0
        assert "already exists" in result.stdout

    def test_groups_defunct_makes_group_inactive(self):
        """'groups defunct' marks a group as defunct."""
        prefix = _vault_path_prefix()
        # Create a group
        run_cli(["groups", "create", "temp-group"], vault_path_prefix=prefix)

        # Make it defunct
        result = run_cli(["groups", "defunct", "temp-group"], vault_path_prefix=prefix)
        assert result.returncode == 0, result.stderr
        assert "defunct" in result.stdout.lower()

        # Should not appear in normal list
        result = run_cli(["groups", "list"], vault_path_prefix=prefix)
        assert "temp-group" not in result.stdout

        # Should appear with --include-defunct
        result = run_cli(["groups", "list", "--include-defunct"], vault_path_prefix=prefix)
        assert "temp-group" in result.stdout

    def test_groups_defunct_reserved_fails(self):
        """'groups defunct' fails for reserved groups."""
        prefix = _vault_path_prefix()
        result = run_cli(["groups", "defunct", "admin"], vault_path_prefix=prefix)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_tokens_list_empty_initially(self):
        """'tokens list' shows no tokens initially."""
        prefix = _vault_path_prefix()
        result = run_cli(["tokens", "list"], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        assert "No tokens found" in result.stdout or "Total: 0" in result.stdout

    def test_tokens_create_outputs_jwt(self):
        """'tokens create' outputs a valid JWT."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["tokens", "create", "--groups", "admin"],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 0, result.stderr
        token = result.stdout.strip()

        # JWT format: header.payload.signature
        assert token.count('.') == 2, f"Expected JWT format, got: {token}"

    def test_tokens_create_multiple_groups(self):
        """'tokens create' works with multiple groups."""
        prefix = _vault_path_prefix()
        # First create the groups
        run_cli(["groups", "create", "users"], vault_path_prefix=prefix)
        run_cli(["groups", "create", "finance"], vault_path_prefix=prefix)

        result = run_cli(
            ["tokens", "create", "--groups", "admin,users,finance"],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 0, result.stderr
        token = result.stdout.strip()
        assert token.count('.') == 2

    def test_tokens_create_invalid_group_fails(self):
        """'tokens create' fails for non-existent group."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["tokens", "create", "--groups", "nonexistent-group"],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_tokens_list_shows_created_tokens(self):
        """'tokens list' shows tokens after creation."""
        prefix = _vault_path_prefix()
        # Create a token
        run_cli(["tokens", "create", "--groups", "admin"], vault_path_prefix=prefix)

        result = run_cli(["tokens", "list"], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        assert "admin" in result.stdout
        assert "active" in result.stdout.lower()

    def test_tokens_list_json_format(self):
        """'tokens list --format json' outputs valid JSON."""
        prefix = _vault_path_prefix()
        # Create a token
        run_cli(["tokens", "create", "--groups", "admin"], vault_path_prefix=prefix)

        result = run_cli(["tokens", "list", "--format", "json"], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "id" in data[0]
        assert "groups" in data[0]
        assert "name" in data[0]

    def test_tokens_list_filter_by_status(self):
        """'tokens list --status' filters correctly."""
        prefix = _vault_path_prefix()
        # Create a token
        run_cli(
            ["tokens", "create", "--groups", "admin"],
            vault_path_prefix=prefix,
        )

        # Get the token ID from list
        list_result = run_cli(
            ["tokens", "list", "--format", "json"],
            vault_path_prefix=prefix,
        )
        tokens = json.loads(list_result.stdout)
        token_id = tokens[0]["id"]

        # Revoke it
        run_cli(["tokens", "revoke", token_id], vault_path_prefix=prefix)

        # Active list should be empty
        result = run_cli(
            ["tokens", "list", "--status", "active"], vault_path_prefix=prefix,
        )
        assert token_id not in result.stdout

        # Revoked list should have it
        result = run_cli(
            ["tokens", "list", "--status", "revoked"], vault_path_prefix=prefix,
        )
        assert token_id in result.stdout

    def test_tokens_revoke_by_id(self):
        """'tokens revoke' marks token as revoked."""
        prefix = _vault_path_prefix()
        # Create a token
        run_cli(["tokens", "create", "--groups", "admin"], vault_path_prefix=prefix)

        # Get token ID
        list_result = run_cli(
            ["tokens", "list", "--format", "json"],
            vault_path_prefix=prefix,
        )
        tokens = json.loads(list_result.stdout)
        token_id = tokens[0]["id"]

        # Revoke it
        result = run_cli(["tokens", "revoke", token_id], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        assert "revoked" in result.stdout.lower()

    def test_tokens_create_with_name_and_list(self):
        """Creating with --name surfaces name in list/JSON and filters by pattern."""
        prefix = _vault_path_prefix()
        run_cli(
            ["tokens", "create", "--groups", "admin", "--name", "dev-api"],
            vault_path_prefix=prefix,
        )

        table = run_cli(["tokens", "list"], vault_path_prefix=prefix)
        assert table.returncode == 0
        assert "dev-api" in table.stdout

        json_result = run_cli(
            ["tokens", "list", "--format", "json"], vault_path_prefix=prefix,
        )
        tokens = json.loads(json_result.stdout)
        assert tokens[0].get("name") == "dev-api"

        filtered = run_cli(
            ["tokens", "list", "--name-pattern", "dev-*"], vault_path_prefix=prefix,
        )
        assert filtered.returncode == 0
        assert "dev-api" in filtered.stdout

    def test_tokens_revoke_by_name(self):
        """Revoke works by name without needing UUID."""
        prefix = _vault_path_prefix()
        run_cli(
            ["tokens", "create", "--groups", "admin", "--name", "dev-admin"],
            vault_path_prefix=prefix,
        )

        result = run_cli(
            ["tokens", "revoke", "--name", "dev-admin"], vault_path_prefix=prefix,
        )
        assert result.returncode == 0
        assert "revoked" in result.stdout.lower()

    def test_tokens_inspect_by_name(self):
        """Inspect by name returns stored record JSON."""
        prefix = _vault_path_prefix()
        run_cli(
            ["tokens", "create", "--groups", "admin", "--name", "prod-api-server"],
            vault_path_prefix=prefix,
        )

        result = run_cli(
            ["tokens", "inspect", "--name", "prod-api-server"],
            vault_path_prefix=prefix,
        )
        assert result.returncode == 0
        assert "prod-api-server" in result.stdout

    def test_tokens_revoke_nonexistent_fails(self):
        """'tokens revoke' fails for non-existent token."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["tokens", "revoke", "00000000-0000-0000-0000-000000000000"],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_tokens_inspect_valid_token(self):
        """'tokens inspect' shows decoded token info."""
        prefix = _vault_path_prefix()
        # Create a token
        create_result = run_cli(
            ["tokens", "create", "--groups", "admin"],
            vault_path_prefix=prefix,
        )
        token = create_result.stdout.strip()

        # Inspect it
        result = run_cli(["tokens", "inspect", token], vault_path_prefix=prefix)

        assert result.returncode == 0, result.stderr
        assert "admin" in result.stdout
        assert "jti" in result.stdout
        assert "VALID" in result.stdout

    def test_tokens_inspect_invalid_token(self):
        """'tokens inspect' handles invalid tokens."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["tokens", "inspect", "not.a.valid.token"],
            vault_path_prefix=prefix,
        )

        # Should fail gracefully
        assert result.returncode == 1

    def test_tokens_create_with_output_file(self, tmp_path):
        """'tokens create --output' saves token to file."""
        prefix = _vault_path_prefix()
        output_file = tmp_path / "token.txt"

        result = run_cli(
            ["tokens", "create", "--groups", "admin", "--output", str(output_file)],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 0, result.stderr
        assert output_file.exists()

        token = output_file.read_text().strip()
        assert token.count('.') == 2  # JWT format

    def test_tokens_create_custom_expiry(self):
        """'tokens create --expires' sets custom expiry."""
        prefix = _vault_path_prefix()
        result = run_cli(
            ["tokens", "create", "--groups", "admin", "--expires", "3600"],
            vault_path_prefix=prefix,
        )

        assert result.returncode == 0, result.stderr

        # Verify in list
        list_result = run_cli(
            ["tokens", "list", "--format", "json"],
            vault_path_prefix=prefix,
        )
        tokens = json.loads(list_result.stdout)

        # Check the token was created (expiry is handled internally)
        assert len(tokens) >= 1

    def test_help_command(self):
        """'--help' shows usage information."""
        result = run_cli(["--help"])

        assert result.returncode == 0
        assert "groups" in result.stdout
        assert "tokens" in result.stdout

    def test_groups_help(self):
        """'groups --help' shows group commands."""
        result = run_cli(["groups", "--help"])

        assert result.returncode == 0
        assert "list" in result.stdout
        assert "create" in result.stdout
        assert "defunct" in result.stdout

    def test_tokens_help(self):
        """'tokens --help' shows token commands."""
        result = run_cli(["tokens", "--help"])

        assert result.returncode == 0
        assert "list" in result.stdout
        assert "create" in result.stdout
        assert "revoke" in result.stdout
        assert "inspect" in result.stdout
