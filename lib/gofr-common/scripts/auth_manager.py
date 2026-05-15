#!/usr/bin/env python3
"""Unified auth management CLI for GOFR projects.

IMPORTANT:
    Human operators should run the wrapper script:
        ./lib/gofr-common/scripts/auth_manager.sh [--docker] <command>

    It is self-contained: it loads SSOT config, performs Vault AppRole login,
    and sets the required GOFR_* environment for this Python CLI.

    Running this Python script directly is supported for automation, but it
    requires you to provide the environment variables documented below.

This script provides a single entry point for all authentication management
operations including group and token management.

QUICK START:
    # Use the wrapper script (recommended - handles SSOT automatically):
    cd /path/to/gofr-project
    ./lib/gofr-common/scripts/auth_manager.sh --docker groups list

    # Or run Python directly (advanced - you must set env vars yourself):
    export GOFR_AUTH_BACKEND=vault
    export GOFR_VAULT_URL=http://gofr-vault:8201
    export GOFR_VAULT_TOKEN=...  # minted operator token or root token

    # List groups:
    python auth_manager.py --backend vault groups list

    # Create token for admin group (30 day expiry):
    python auth_manager.py --backend vault tokens create --groups admin

    # Create token with human-friendly name:
    python auth_manager.py --backend vault tokens create --groups admin --name prod-api-server

    # Inspect a token:
    python auth_manager.py --backend vault tokens inspect <jwt-string>

USAGE:
    Groups:
      auth_manager.py groups list [--include-defunct] [--format table|json]
      auth_manager.py groups create <name> [--description DESC]
      auth_manager.py groups defunct <name>

        Tokens:
            auth_manager.py tokens list [--status active|revoked] [--name-pattern PATTERN] [--format table|json]
            auth_manager.py tokens create --groups group1,group2 [--name NAME] [--expires SECONDS] [--output FILE]
            auth_manager.py tokens revoke <token-id> [--name NAME]
            auth_manager.py tokens inspect <token-string> [--name NAME]

ENVIRONMENT VARIABLES (REQUIRED):
    GOFR_AUTH_BACKEND      Must be "vault"

    For Vault backend:
    GOFR_VAULT_URL         Vault server URL (e.g., http://gofr-vault:8201)
    GOFR_VAULT_TOKEN       Vault token (operator or root)
    GOFR_VAULT_PATH_PREFIX Vault KV path prefix (default: gofr/auth)

EXAMPLES:
    # List all groups with JSON output:
    auth_manager.py --backend vault groups list --format json

    # Create multi-group token valid for 7 days:
    auth_manager.py --backend vault tokens create \
        --groups admin,finance,reporting --expires 604800

    # Create named token for production API:
    auth_manager.py --backend vault tokens create \
        --groups admin --name prod-api-server

    # Save token to file for use in scripts:
    auth_manager.py --backend vault tokens create \\
        --groups public --output /tmp/public-token.jwt

    # Revoke a specific token:
    auth_manager.py --backend vault tokens revoke ec425f14-5db5-414e-9c6b-8f88ed44895e

    # Revoke by name:
    auth_manager.py --backend vault tokens revoke --name prod-api-server

    # Check token validity and claims:
    auth_manager.py --backend vault tokens inspect eyJhbGc...

BACKEND SELECTION:
    - vault: HashiCorp Vault (required)

    Specify via --backend flag or GOFR_AUTH_BACKEND environment variable.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
import fnmatch

# Try to import from installed package, fall back to local path
try:
    from gofr_common.auth import (
        AuthService,
        GroupRegistry,
        JwtSecretProvider,
        VaultClient,
        VaultConfig,
        VaultGroupStore,
        VaultTokenStore,
    )
except ImportError:
    # Add potential paths for development
    script_dir = Path(__file__).parent.parent
    src_path = script_dir / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))
    from gofr_common.auth import (
        AuthService,
        GroupRegistry,
        JwtSecretProvider,
        VaultClient,
        VaultConfig,
        VaultGroupStore,
        VaultTokenStore,
    )

import jwt


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds // 3600}h"
    else:
        return f"{seconds // 86400}d"


def format_time_remaining(expires_at: Optional[datetime]) -> str:
    """Format time remaining until expiry."""
    if expires_at is None:
        return "never"

    now = datetime.utcnow()
    if expires_at < now:
        return "EXPIRED"

    delta = expires_at - now
    days = delta.days
    hours = delta.seconds // 3600

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h"
    else:
        minutes = delta.seconds // 60
        return f"{minutes}m"


def create_auth_service(backend: str = "vault", quiet: bool = True) -> AuthService:
    """Create AuthService with the appropriate backend.

    Args:
        backend: Storage backend type (vault only)
        quiet: If True, suppress logging output (for CLI use)
    """
    # Suppress logging if quiet mode - must be done BEFORE any imports/inits
    if quiet:
        import logging

        logging.disable(logging.CRITICAL)

    if backend != "vault":
        print(
            "ERROR: Unsupported backend. Set GOFR_AUTH_BACKEND=vault or pass --backend vault",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Get Vault configuration from environment.
        # Preferred variables are GOFR_* (used across GOFR services).
        # For operator convenience, also accept Vault-standard VAULT_*.
        vault_url = os.environ.get("GOFR_VAULT_URL") or os.environ.get("VAULT_ADDR")
        vault_token = os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN")
        vault_path_prefix = os.environ.get("GOFR_VAULT_PATH_PREFIX", "gofr/auth")

        if not vault_url:
            print(
                "ERROR: Vault URL is required. Set GOFR_VAULT_URL (preferred) or VAULT_ADDR.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not vault_token:
            print(
                "ERROR: Vault token is required. Set GOFR_VAULT_TOKEN (preferred) or VAULT_TOKEN.",
                file=sys.stderr,
            )
            sys.exit(1)

        config = VaultConfig(url=vault_url, token=vault_token)
        client = VaultClient(config)

        if not client.health_check():
            print(f"ERROR: Cannot connect to Vault at {vault_url}", file=sys.stderr)
            sys.exit(1)

        token_store = VaultTokenStore(client, path_prefix=vault_path_prefix)
        group_store = VaultGroupStore(client, path_prefix=vault_path_prefix)

    group_registry = GroupRegistry(store=group_store, auto_bootstrap=True)

    # JWT secret is read from Vault by JwtSecretProvider -- no env var needed
    secret_provider = JwtSecretProvider(vault_client=client)

    return AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_provider=secret_provider,
    )


# ============================================================================
# GROUP COMMANDS
# ============================================================================


def cmd_groups_list(auth: AuthService, include_defunct: bool = False, format: str = "table") -> int:
    """List all groups."""
    groups = auth.groups.list_groups(include_defunct=include_defunct)

    if format == "json":
        output = [g.to_dict() for g in groups]
        print(json.dumps(output, indent=2, default=str))
        return 0

    # Table format
    if not groups:
        print("No groups found")
        return 0

    print(f"\n{'Name':<25} {'Status':<12} {'Reserved':<10} {'Created':<20}")
    print("-" * 70)

    for group in sorted(groups, key=lambda g: g.name):
        status = "active" if group.is_active else "defunct"
        reserved = "yes" if group.is_reserved else "no"
        created = group.created_at.strftime("%Y-%m-%d %H:%M")
        print(f"{group.name:<25} {status:<12} {reserved:<10} {created:<20}")

    print(f"\nTotal: {len(groups)} groups")
    return 0


def cmd_groups_create(auth: AuthService, name: str, description: Optional[str] = None) -> int:
    """Create a new group, or restore if defunct."""
    try:
        # Check if group already exists
        existing = auth.groups.get_group_by_name(name)

        if existing:
            # Group exists - check if it's defunct
            if existing.defunct_at is not None:
                # Restore the defunct group
                existing.is_active = True
                existing.defunct_at = None
                # Prefer public API when available; fall back to store for older versions.
                if hasattr(auth.groups, "update_group"):
                    auth.groups.update_group(existing)
                else:
                    auth.groups._store.put(str(existing.id), existing)
                print(f"Restored defunct group: {name}")
                print(f"  ID: {existing.id}")
                if description and description != existing.description:
                    existing.description = description
                    if hasattr(auth.groups, "update_group"):
                        auth.groups.update_group(existing)
                    else:
                        auth.groups._store.put(str(existing.id), existing)
                    print(f"  Updated description: {description}")
                elif existing.description:
                    print(f"  Description: {existing.description}")
                return 0
            else:
                # Group exists and is active
                print(f"Group '{name}' already exists (active)")
                return 0

        # Group doesn't exist - create it
        group = auth.groups.create_group(name, description=description)
        print(f"Created group: {name}")
        print(f"  ID: {group.id}")
        if description:
            print(f"  Description: {description}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_groups_defunct(auth: AuthService, name: str) -> int:
    """Make a group defunct (soft delete)."""
    group = auth.groups.get_group_by_name(name)
    if group is None:
        print(f"ERROR: Group '{name}' not found", file=sys.stderr)
        return 1

    try:
        auth.groups.make_defunct(group.id)
        print(f"Group '{name}' is now defunct")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


# ============================================================================
# TOKEN COMMANDS
# ============================================================================


def cmd_tokens_list(
    auth: AuthService,
    status: Optional[Literal["active", "revoked"]] = None,
    name_pattern: Optional[str] = None,
    format: str = "table",
) -> int:
    """List all tokens."""
    tokens = auth.list_tokens(status=status)

    if name_pattern:
        tokens = [t for t in tokens if t.name and fnmatch.fnmatch(t.name, name_pattern)]

    # Sort newest first for deterministic JSON/table ordering
    tokens = sorted(tokens, key=lambda t: t.created_at, reverse=True)

    if format == "json":
        output = [t.to_dict() for t in tokens]
        print(json.dumps(output, indent=2, default=str))
        return 0

    # Table format
    if not tokens:
        print("No tokens found")
        return 0

    print(f"\n{'Name':<22} {'ID':<38} {'Status':<10} {'Groups':<22} {'Expires':<15}")
    print("-" * 115)

    for token in tokens:
        token_id = str(token.id)
        name_str = token.name or ""
        if len(name_str) > 20:
            name_str = name_str[:19] + "..."
        status_str = token.status
        if token.is_expired and token.status == "active":
            status_str = "expired"
        groups_str = ",".join(token.groups)
        if len(groups_str) > 21:
            groups_str = groups_str[:18] + "..."
        expires_str = format_time_remaining(token.expires_at)

        print(f"{name_str:<22} {token_id:<38} {status_str:<10} {groups_str:<22} {expires_str:<15}")

    print(f"\nTotal: {len(tokens)} tokens")
    return 0


def cmd_tokens_create(
    auth: AuthService,
    groups: str,
    expires: int = 2592000,
    output: Optional[str] = None,
    name: Optional[str] = None,
) -> int:
    """Create a new token."""
    group_list = [g.strip() for g in groups.split(",") if g.strip()]

    if not group_list:
        print("ERROR: At least one group is required", file=sys.stderr)
        return 1

    try:
        token = auth.create_token(groups=group_list, expires_in_seconds=expires, name=name)

        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(token)
            print(f"Token saved to: {output}")
        else:
            # Print just the token for easy piping
            print(token)

        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_tokens_revoke(auth: AuthService, token_id: Optional[str], name: Optional[str]) -> int:
    """Revoke a token by its ID or name."""
    # Name takes precedence when provided
    if name:
        if auth.revoke_token_by_name(name):
            print(f"Token '{name}' has been revoked")
            return 0
        print(f"ERROR: Token '{name}' not found", file=sys.stderr)
        return 1

    if not token_id:
        print("ERROR: token_id or --name is required", file=sys.stderr)
        return 1

    # First, find the token record to get its JWT
    token_record = auth.get_token_by_id(token_id)

    if token_record is None:
        print(f"ERROR: Token '{token_id}' not found", file=sys.stderr)
        return 1

    if token_record.status == "revoked":
        print(f"Token '{token_id}' is already revoked")
        return 0

    # Create a minimal JWT just to call revoke_token
    # We need to forge a token with the correct jti for revocation
    payload = {
        "jti": token_id,
        "groups": token_record.groups,
        "iat": int(token_record.created_at.timestamp()),
        "exp": int(token_record.expires_at.timestamp()) if token_record.expires_at else 0,
    }
    minimal_token = jwt.encode(payload, auth.secret_key, algorithm="HS256")

    if auth.revoke_token(minimal_token):
        print(f"Token '{token_id}' has been revoked")
        return 0
    else:
        print(f"ERROR: Failed to revoke token '{token_id}'", file=sys.stderr)
        return 1


def cmd_tokens_inspect(auth: AuthService, token_string: Optional[str], name: Optional[str]) -> int:
    """Inspect a token by string or by stored name."""
    if name:
        record = auth.get_token_by_name(name)
        if record is None:
            print(f"ERROR: Token '{name}' not found", file=sys.stderr)
            return 1

        print("=== Token Record (by name) ===")
        print(json.dumps(record.to_dict(), indent=2, default=str))
        return 0

    if not token_string:
        print("ERROR: token string or --name is required", file=sys.stderr)
        return 1

    try:
        # First try to decode without verification to show claims
        unverified = jwt.decode(
            token_string,
            options={"verify_signature": False},
        )

        print("=== Token Claims (unverified) ===")
        print(json.dumps(unverified, indent=2, default=str))

        # Now try to verify
        print("\n=== Verification ===")
        try:
            info = auth.verify_token(token_string, require_store=True)
            print("Status: VALID")
            print(f"Groups: {', '.join(info.groups)}")
            print(f"Issued: {info.issued_at.isoformat()}")
            print(f"Expires: {info.expires_at.isoformat() if info.expires_at else 'never'}")

            # Check token record
            token_id = unverified.get("jti")
            if token_id:
                record = auth.get_token_by_id(token_id)
                if record:
                    print("\n=== Token Record ===")
                    print(f"ID: {record.id}")
                    print(f"Status: {record.status}")
                    print(f"Name: {record.name or ''}")
                    print(f"Created: {record.created_at.isoformat()}")
                    if record.expires_at:
                        print(f"Expires: {record.expires_at.isoformat()}")
                    if record.fingerprint:
                        print(f"Fingerprint: {record.fingerprint[:20]}...")
        except Exception as e:
            print(f"Status: INVALID - {e}")
            return 1

        return 0
    except jwt.DecodeError as e:
        print(f"ERROR: Invalid token format - {e}", file=sys.stderr)
        return 1


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified auth management CLI for GOFR projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
    List all groups:
        %(prog)s --backend vault groups list

  Create a finance group:
    %(prog)s --backend vault groups create finance --description "Finance team"

    Create named admin token (30d):
        %(prog)s --backend vault tokens create --groups admin --name prod-api-server --expires 2592000

    List tokens filtered by name pattern:
        %(prog)s --backend vault tokens list --name-pattern "prod-*"

    Revoke by name:
        %(prog)s --backend vault tokens revoke --name prod-api-server

    Inspect by name:
        %(prog)s --backend vault tokens inspect --name prod-api-server

ENVIRONMENT:
    Required: GOFR_AUTH_BACKEND (or --backend)
    Vault:    GOFR_VAULT_URL, GOFR_VAULT_TOKEN

For full documentation, see script header or run with --help.
        """,
    )

    # Global options
    # Backend selection - no silent fallback to file
    backend_from_env = os.environ.get("GOFR_AUTH_BACKEND")
    parser.add_argument(
        "--backend",
        default=backend_from_env or "vault",
        choices=["vault"],
        help="Storage backend (vault only). Set via GOFR_AUTH_BACKEND or this flag.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging output for debugging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command category", required=False)

    # -------------------------------------------------------------------------
    # GROUPS subcommand
    # -------------------------------------------------------------------------
    groups_parser = subparsers.add_parser(
        "groups",
        help="Manage authentication groups",
        description="Create, list, and manage authentication groups",
    )
    groups_sub = groups_parser.add_subparsers(
        dest="subcommand", help="Group operation", required=False
    )

    # groups list
    groups_list = groups_sub.add_parser(
        "list",
        help="List all groups",
        description="Display all authentication groups with status and metadata",
    )
    groups_list.add_argument(
        "--include-defunct",
        action="store_true",
        help="Include defunct (soft-deleted) groups in output",
    )
    groups_list.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format. Table for humans, JSON for scripts. Default: %(default)s",
    )

    # groups create
    groups_create = groups_sub.add_parser(
        "create",
        help="Create a new group",
        description="Create a new authentication group for access control",
    )
    groups_create.add_argument("name", help="Unique group name (e.g., 'finance', 'admin')")
    groups_create.add_argument(
        "--description",
        "-d",
        help="Human-readable group description",
    )

    # groups defunct
    groups_defunct = groups_sub.add_parser(
        "defunct",
        help="Make a group defunct (soft delete)",
        description="Mark group as defunct. Preserves audit trail, prevents new tokens.",
    )
    groups_defunct.add_argument("name", help="Group name to make defunct")

    # -------------------------------------------------------------------------
    # TOKENS subcommand
    # -------------------------------------------------------------------------
    tokens_parser = subparsers.add_parser(
        "tokens",
        help="Manage JWT authentication tokens",
        description="Create, list, revoke, and inspect JWT tokens",
    )
    tokens_sub = tokens_parser.add_subparsers(
        dest="subcommand", help="Token operation", required=False
    )

    # tokens list
    tokens_list = tokens_sub.add_parser(
        "list",
        help="List all tokens",
        description="Display all JWT tokens with status, groups, and expiry",
    )
    tokens_list.add_argument(
        "--status",
        choices=["active", "revoked"],
        help="Filter by token status (omit to show all)",
    )
    tokens_list.add_argument(
        "--name-pattern",
        help="Filter by token name glob pattern (e.g., 'prod-*')",
    )
    tokens_list.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format. Table for humans, JSON for scripts. Default: %(default)s",
    )

    # tokens create
    tokens_create = tokens_sub.add_parser(
        "create",
        help="Create a new token",
        description="Generate a new JWT token for specified groups",
    )
    tokens_create.add_argument(
        "--groups",
        "-g",
        required=True,
        help="Comma-separated list of groups (e.g., 'admin,users,reporting')",
    )
    tokens_create.add_argument(
        "--name",
        help="Optional human-friendly token name (unique, lowercase, 3-64 chars)",
    )
    tokens_create.add_argument(
        "--expires",
        "-e",
        type=int,
        default=2592000,  # 30 days
        help="Token expiry in seconds. Default: %(default)s (30 days)",
    )
    tokens_create.add_argument(
        "--output",
        "-o",
        help="Save token to file (useful for scripts). If omitted, prints to stdout.",
    )

    # tokens revoke
    tokens_revoke = tokens_sub.add_parser(
        "revoke",
        help="Revoke a token",
        description="Immediately revoke a token by its UUID. Token becomes invalid.",
    )
    tokens_revoke.add_argument(
        "token_id",
        nargs="?",
        help="Token UUID to revoke (from 'tokens list')",
    )
    tokens_revoke.add_argument(
        "--name",
        help="Revoke by token name (takes precedence over token_id)",
    )

    # tokens inspect
    tokens_inspect = tokens_sub.add_parser(
        "inspect",
        help="Inspect a token string",
        description="Decode and verify a JWT token, showing claims and validation status",
    )
    tokens_inspect.add_argument(
        "token",
        nargs="?",
        help="Full JWT string (eyJhbG...)",
    )
    tokens_inspect.add_argument(
        "--name",
        help="Inspect by token name (shows stored record)",
    )

    args = parser.parse_args()

    # Handle no command
    if not args.command:
        parser.print_help()
        return 1

    # Handle no subcommand
    if args.command in ("groups", "tokens") and not args.subcommand:
        if args.command == "groups":
            groups_parser.print_help()
        else:
            tokens_parser.print_help()
        return 1

    # Validate backend is set - no silent fallback
    if args.backend is None:
        print("ERROR: Backend not specified.", file=sys.stderr)
        print("Set GOFR_AUTH_BACKEND environment variable or use --backend flag.", file=sys.stderr)
        print("Valid backends: vault", file=sys.stderr)
        return 1

    # Create auth service (quiet mode unless verbose)
    auth = create_auth_service(args.backend, quiet=not args.verbose)

    # Dispatch to appropriate command
    if args.command == "groups":
        if args.subcommand == "list":
            return cmd_groups_list(auth, args.include_defunct, args.format)
        elif args.subcommand == "create":
            return cmd_groups_create(auth, args.name, args.description)
        elif args.subcommand == "defunct":
            return cmd_groups_defunct(auth, args.name)

    elif args.command == "tokens":
        if args.subcommand == "list":
            return cmd_tokens_list(auth, args.status, args.name_pattern, args.format)
        elif args.subcommand == "create":
            return cmd_tokens_create(auth, args.groups, args.expires, args.output, args.name)
        elif args.subcommand == "revoke":
            return cmd_tokens_revoke(auth, args.token_id, args.name)
        elif args.subcommand == "inspect":
            return cmd_tokens_inspect(auth, args.token, args.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
