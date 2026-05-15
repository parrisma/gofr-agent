"""CLI token manager for GOFR projects.

Provides create, list, verify, and revoke commands for JWT tokens.
Used by project-specific token_manager.sh wrappers.

Usage:
    python -m gofr_common.auth.token_manager --token-store /path/to/tokens.json create --group admin
    python -m gofr_common.auth.token_manager --token-store /path/to/tokens.json list
    python -m gofr_common.auth.token_manager --token-store /path/to/tokens.json verify --token <JWT>
    python -m gofr_common.auth.token_manager --token-store /path/to/tokens.json revoke --token <JWT>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

from gofr_common.auth.service import AuthService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gofr-token-manager",
        description="Manage JWT tokens for GOFR projects",
    )

    # Global options
    parser.add_argument(
        "--token-store",
        required=True,
        help="Path to the token store JSON file",
    )
    parser.add_argument(
        "--env-prefix",
        default=None,
        help="Environment variable prefix (e.g. GOFR_DIG). "
        "JWT secret is always read from GOFR_JWT_SECRET (system-wide).",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- create ---
    create_p = subparsers.add_parser("create", help="Create a new JWT token")
    create_p.add_argument("--group", required=True, help="Group name for the token")
    create_p.add_argument(
        "--expires",
        type=int,
        default=86400,
        help="Token expiry in seconds (default: 86400 = 24h)",
    )
    create_p.add_argument("--name", default=None, help="Optional human-readable name/label")

    # --- list ---
    subparsers.add_parser("list", help="List all tokens in the store")

    # --- verify ---
    verify_p = subparsers.add_parser("verify", help="Verify a token")
    verify_p.add_argument("--token", required=True, help="JWT token string")

    # --- revoke ---
    revoke_p = subparsers.add_parser("revoke", help="Revoke a token")
    revoke_p.add_argument("--token", required=True, help="JWT token string")

    return parser


def _get_auth_service(
    token_store: str,
    env_prefix: Optional[str] = None,
) -> AuthService:
    """Create an AuthService from CLI arguments."""
    import os

    # Resolve JWT secret from environment — always system-wide
    secret = os.environ.get("GOFR_JWT_SECRET")
    if not secret:
        print("ERROR: GOFR_JWT_SECRET environment variable is not set", file=sys.stderr)
        print("Set it with: export GOFR_JWT_SECRET=<your-secret>", file=sys.stderr)
        sys.exit(1)

    return AuthService(
        secret_key=secret,
        token_store_path=token_store,
    )


def _cmd_create(auth: AuthService, args: argparse.Namespace) -> None:
    """Create a new token."""
    token = auth.create_token(
        group=args.group,
        expires_in_seconds=args.expires,
    )

    info = auth.verify_token(token)

    print("Token created successfully")
    print(f"  Group:      {info.group}")
    print(f"  Issued:     {info.issued_at.isoformat()}")
    print(f"  Expires:    {info.expires_at.isoformat()}")
    if args.name:
        print(f"  Name:       {args.name}")
    print(f"  Token:      {token}")


def _cmd_list(auth: AuthService, _args: argparse.Namespace) -> None:
    """List all tokens in the store."""
    tokens = auth.list_tokens()

    if not tokens:
        print("No tokens in store.")
        return

    print(f"{'Group':<20} {'Issued':<22} {'Expires':<22} {'Token (first 20)':<24}")
    print("-" * 88)

    for token_str, meta in tokens.items():
        group = meta.get("group", "?")
        issued = meta.get("issued_at", "?")
        expires = meta.get("expires_at", "?")

        # Truncate ISO timestamps for display
        if isinstance(issued, str) and len(issued) > 19:
            issued = issued[:19]
        if isinstance(expires, str) and len(expires) > 19:
            expires = expires[:19]

        token_preview = token_str[:20] + "..."
        print(f"{group:<20} {issued:<22} {expires:<22} {token_preview:<24}")

    print(f"\nTotal: {len(tokens)} token(s)")


def _cmd_verify(auth: AuthService, args: argparse.Namespace) -> None:
    """Verify a token."""
    try:
        info = auth.verify_token(args.token, require_store=False)
        print("Token is VALID")
        print(f"  Group:      {info.group}")
        print(f"  Issued:     {info.issued_at.isoformat()}")
        print(f"  Expires:    {info.expires_at.isoformat()}")

        now = datetime.utcnow()
        remaining = info.expires_at - now
        if remaining.total_seconds() > 0:
            days = remaining.days
            hours = remaining.seconds // 3600
            print(f"  Remaining:  {days}d {hours}h")
        else:
            print("  Status:     EXPIRED")

        # Check if token is in store
        if args.token in auth.token_store:
            print("  In store:   yes")
        else:
            print("  In store:   no (external/bootstrap token)")

    except ValueError as e:
        print(f"Token is INVALID: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_revoke(auth: AuthService, args: argparse.Namespace) -> None:
    """Revoke a token."""
    revoked = auth.revoke_token(args.token)
    if revoked:
        print("Token revoked successfully")
    else:
        print("Token not found in store (may already be revoked or is an external token)")


def main(argv: list[str] | None = None) -> None:
    """Entry point for the CLI."""
    parser = _build_parser()

    # Strip project-specific --*-env flags injected by the common shell wrapper
    # (e.g. --gofr-dig-env TEST). These are not needed by the Python module
    # since we read the env from the prefix-based env var.
    raw = argv if argv is not None else sys.argv[1:]
    filtered: list[str] = []
    skip_next = False
    for i, arg in enumerate(raw):
        if skip_next:
            skip_next = False
            continue
        if arg.endswith("-env") and arg.startswith("--") and arg != "--env-prefix":
            # Skip this flag and its value
            skip_next = True
            continue
        filtered.append(arg)

    args = parser.parse_args(filtered)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    auth = _get_auth_service(
        token_store=args.token_store,
        env_prefix=args.env_prefix,
    )

    commands = {
        "create": _cmd_create,
        "list": _cmd_list,
        "verify": _cmd_verify,
        "revoke": _cmd_revoke,
    }

    handler = commands.get(args.command)
    if handler:
        handler(auth, args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
