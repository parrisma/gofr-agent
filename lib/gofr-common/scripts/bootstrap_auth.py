#!/usr/bin/env python3
"""Bootstrap authentication for GOFR projects.

Creates the reserved groups (public, admin) and bootstrap tokens in the
configured backend. This script is idempotent - safe to run multiple times.

The script:
1. Ensures reserved groups (public, admin) exist
2. Creates bootstrap tokens for each group (if requested)
3. Outputs tokens to stdout for capture by shell scripts

Usage:
    # Bootstrap with defaults (uses GOFR_ env vars)
    python scripts/bootstrap_auth.py

    # Bootstrap for specific project
    GOFR_VAULT_URL=http://vault:8200 python scripts/bootstrap_auth.py --prefix GOFR

    # Bootstrap groups only (no tokens)
    python scripts/bootstrap_auth.py --groups-only

    # Force new tokens even if groups already exist
    python scripts/bootstrap_auth.py --force-tokens

Environment Variables (with prefix, e.g., GOFR_ or GOFR_):
    {PREFIX}AUTH_BACKEND       Backend type: vault, file, memory (default: vault)
    {PREFIX}VAULT_URL          Vault server URL
    {PREFIX}VAULT_TOKEN        Vault authentication token
    {PREFIX}VAULT_ROLE_ID      Vault AppRole role ID (alternative to token)
    {PREFIX}VAULT_SECRET_ID    Vault AppRole secret ID (alternative to token)
    {PREFIX}VAULT_PATH_PREFIX  Path prefix in Vault (default: {prefix}/auth)
    {PREFIX}VAULT_MOUNT_POINT  KV mount point (default: secret)
    {PREFIX}JWT_SECRET         JWT signing secret (auto-generated if not set; system-wide: GOFR_JWT_SECRET)
    {PREFIX}DATA_DIR           Data directory for file backend

Output (to stdout, for shell capture):
    {PREFIX}PUBLIC_TOKEN=<jwt-token>
    {PREFIX}ADMIN_TOKEN=<jwt-token>
"""

import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Optional, Tuple

# Add src to path for imports
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root / "src"))

from gofr_common.auth import AuthService, GroupRegistry  # noqa: E402
from gofr_common.auth.admin import VaultAdmin  # noqa: E402
from gofr_common.auth.backends import create_stores_from_env  # noqa: E402
from gofr_common.auth.backends.vault_client import VaultClient  # noqa: E402
from gofr_common.auth.backends.vault_config import VaultConfig  # noqa: E402
from gofr_common.auth.groups import RESERVED_GROUPS  # noqa: E402
from gofr_common.logger import create_logger  # noqa: E402

# Token expiry: 10 years in seconds (effectively permanent for bootstrap tokens)
BOOTSTRAP_TOKEN_EXPIRY = 10 * 365 * 24 * 60 * 60

logger = create_logger(name="bootstrap-auth")


def log_info(message: str, quiet: bool = False) -> None:
    """Log info message to stderr."""
    if not quiet:
        print(f"[INFO] {message}", file=sys.stderr)


def log_success(message: str, quiet: bool = False) -> None:
    """Log success message to stderr."""
    if not quiet:
        print(f"[OK] {message}", file=sys.stderr)


def log_error(message: str) -> None:
    """Log error message to stderr."""
    print(f"[ERROR] {message}", file=sys.stderr)


def log_warn(message: str, quiet: bool = False) -> None:
    """Log warning message to stderr."""
    if not quiet:
        print(f"[WARN] {message}", file=sys.stderr)


def _env_flag(prefix: str, suffix: str, default: bool = True) -> bool:
    """Read a boolean flag from environment.

    Accepts true/false variants: 1/0, true/false, yes/no, on/off.
    """
    raw_value = os.environ.get(f"{prefix}_{suffix}")
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def install_vault_policies(prefix: str, quiet: bool = False) -> bool:
    """Install Vault policies if using Vault backend.

    Args:
        prefix: Environment variable prefix
        quiet: Suppress output messages

    Returns:
        True if policies were installed or not needed, False on error
    """
    backend = os.environ.get(f"{prefix}_AUTH_BACKEND", "vault")

    if not _env_flag(prefix, "BOOTSTRAP_INSTALL_POLICIES", default=True):
        log_info("Skipping Vault policy installation (disabled by environment)", quiet)
        return True

    # Only install policies for Vault backend
    if backend != "vault":
        return True

    log_info("Installing Vault policies...", quiet)

    try:
        # Create Vault client
        vault_url = os.environ.get(f"{prefix}_VAULT_URL")
        vault_token = os.environ.get(f"{prefix}_VAULT_TOKEN")

        if not vault_url or not vault_token:
            log_warn("Vault URL or token not set, skipping policy installation", quiet)
            return True

        config = VaultConfig(url=vault_url, token=vault_token)
        client = VaultClient(config)
        admin = VaultAdmin(client)

        # Install all policies
        admin.update_policies()
        log_success("Vault policies installed", quiet)
        return True

    except Exception as e:
        log_error(f"Failed to install Vault policies: {e}")
        return False


def store_jwt_secret_in_vault(prefix: str, jwt_secret: str, quiet: bool = False) -> bool:
    """Store JWT signing secret in Vault for services to read.

    Args:
        prefix: Environment variable prefix
        jwt_secret: The JWT secret to store
        quiet: Suppress output messages

    Returns:
        True if stored successfully, False on error
    """
    backend = os.environ.get(f"{prefix}_AUTH_BACKEND", "vault")

    if not _env_flag(prefix, "BOOTSTRAP_STORE_JWT_SECRET", default=True):
        log_info("Skipping JWT secret storage (disabled by environment)", quiet)
        return True

    # Only store in Vault backend
    if backend != "vault":
        return True

    log_info("Checking JWT signing secret in Vault...", quiet)

    try:
        vault_url = os.environ.get(f"{prefix}_VAULT_URL")
        vault_token = os.environ.get(f"{prefix}_VAULT_TOKEN")

        if not vault_url or not vault_token:
            log_warn("Vault URL or token not set, skipping JWT secret storage", quiet)
            return True

        config = VaultConfig(url=vault_url, token=vault_token)
        client = VaultClient(config)

        # Idempotent: only write if secret does not already exist in Vault
        existing = client.read_secret("gofr/config/jwt-signing-secret")
        if existing and existing.get("value"):
            log_success("JWT signing secret already exists in Vault (unchanged)", quiet)
        else:
            client.write_secret("gofr/config/jwt-signing-secret", {"value": jwt_secret})
            log_success("JWT signing secret stored in Vault", quiet)
        return True

    except Exception as e:
        log_error(f"Failed to store JWT secret in Vault: {e}")
        return False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Bootstrap GOFR authentication with reserved groups and tokens",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--prefix",
        type=str,
        default=os.environ.get("GOFR_AUTH_PREFIX", "GOFR"),
        help="Environment variable prefix (default: GOFR or GOFR_AUTH_PREFIX env)",
    )

    parser.add_argument(
        "--groups-only",
        action="store_true",
        help="Only ensure groups exist, don't create tokens",
    )

    parser.add_argument(
        "--force-tokens",
        action="store_true",
        help="Force creation of new tokens even if groups already exist",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress informational output (only output tokens)",
    )

    # Allow overriding individual settings
    parser.add_argument(
        "--backend",
        type=str,
        choices=["memory", "file", "vault"],
        help="Override storage backend",
    )

    parser.add_argument(
        "--vault-url",
        type=str,
        help="Override Vault URL",
    )

    parser.add_argument(
        "--vault-token",
        type=str,
        help="Override Vault token",
    )

    parser.add_argument(
        "--jwt-secret",
        type=str,
        help="Override JWT secret",
    )

    return parser.parse_args()


def setup_env_defaults(prefix: str, args: argparse.Namespace) -> str:
    """Set up default environment variables if not already set.

    Args:
        prefix: Environment variable prefix (e.g., "GOFR")
        args: Parsed command line arguments

    Returns:
        Normalized prefix string
    """
    # Normalize prefix
    prefix = prefix.upper().rstrip("_")

    # Set defaults for common variables
    # NOTE: The shell wrapper should set these, but we provide fallbacks
    defaults = {
        f"{prefix}_AUTH_BACKEND": "vault",
        f"{prefix}_VAULT_URL": "http://gofr-vault:8201",  # Default port from gofr_ports.sh
        f"{prefix}_VAULT_TOKEN": "gofr-dev-root-token",
        f"{prefix}_VAULT_PATH_PREFIX": f"{prefix.lower().replace('_', '-')}/auth",
        f"{prefix}_VAULT_MOUNT_POINT": "secret",
    }

    for key, default_value in defaults.items():
        os.environ.setdefault(key, default_value)

    # Apply command line overrides to environment
    if args.backend:
        os.environ[f"{prefix}_AUTH_BACKEND"] = args.backend
    if args.vault_url:
        os.environ[f"{prefix}_VAULT_URL"] = args.vault_url
    if args.vault_token:
        os.environ[f"{prefix}_VAULT_TOKEN"] = args.vault_token

    # Handle JWT secret - generate if not provided (system-wide, not per-app)
    jwt_key = "GOFR_JWT_SECRET"
    if args.jwt_secret:
        os.environ[jwt_key] = args.jwt_secret
    elif not os.environ.get(jwt_key):
        # Generate a secure random secret
        generated_secret = secrets.token_hex(32)
        os.environ[jwt_key] = generated_secret
        logger.debug("Generated JWT secret", prefix=prefix)

    return prefix


def get_auth_service(prefix: str) -> Tuple[AuthService, str]:
    """Create an AuthService from environment configuration.

    Args:
        prefix: Environment variable prefix

    Returns:
        Tuple of (AuthService instance, JWT secret used)

    Raises:
        SystemExit: If configuration is invalid
    """
    jwt_secret = os.environ.get("GOFR_JWT_SECRET")
    if not jwt_secret:
        log_error("GOFR_JWT_SECRET is required")
        sys.exit(1)

    try:
        token_store, group_store = create_stores_from_env(prefix=prefix)
    except Exception as e:
        log_error(f"Failed to create auth stores: {e}")
        log_error(f"Check {prefix}_AUTH_BACKEND and related environment variables")
        sys.exit(1)

    # Create group registry with auto_bootstrap=True to ensure reserved groups
    group_registry = GroupRegistry(store=group_store, auto_bootstrap=True)

    # Create auth service
    auth_service = AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_key=jwt_secret,
        env_prefix=prefix,
    )

    return auth_service, jwt_secret


def ensure_groups(auth_service: AuthService, quiet: bool = False) -> bool:
    """Ensure reserved groups exist.

    Args:
        auth_service: AuthService instance
        quiet: Suppress output

    Returns:
        True if all groups exist (created or already existed)
    """
    all_ok = True

    for group_name in RESERVED_GROUPS:
        group = auth_service.groups.get_group_by_name(group_name)

        if group is None:
            # Force ensure reserved groups
            log_warn(f"Reserved group '{group_name}' missing, creating...", quiet)
            auth_service.groups.ensure_reserved_groups()
            group = auth_service.groups.get_group_by_name(group_name)

        if group:
            log_success(f"Group '{group_name}' (id: {group.id})", quiet)
        else:
            log_error(f"Failed to ensure group '{group_name}'")
            all_ok = False

    return all_ok


def has_existing_bootstrap_token(
    auth_service: AuthService, group_name: str, quiet: bool = False
) -> bool:
    """Check if bootstrap token already exists for a group.

    Args:
        auth_service: AuthService instance
        group_name: Name of the group
        quiet: Suppress output

    Returns:
        True if an active long-lived token exists for this group
    """
    try:
        # List all active tokens
        active_tokens = auth_service.list_tokens(status="active")

        # Find tokens that have only this group (bootstrap tokens are single-group)
        # and have a long expiry (>1 year, indicating they're bootstrap tokens)
        from datetime import datetime, timedelta

        now = datetime.utcnow()  # Use utcnow() to match TokenRecord timestamps
        one_year = timedelta(days=365)

        for token_record in active_tokens:
            if token_record.groups == [group_name]:
                if token_record.expires_at:
                    remaining = token_record.expires_at - now
                    if remaining > one_year:
                        # This is a long-lived bootstrap token
                        remaining_days = remaining.days
                        log_warn(
                            f"Bootstrap token for '{group_name}' already exists "
                            f"(expires: {remaining_days} days remaining). "
                            f"Use --force-tokens to create new token.",
                            quiet,
                        )
                        return True

        return False
    except Exception as e:
        log_warn(f"Could not check for existing token for '{group_name}': {e}", quiet)
        return False


def create_bootstrap_token(
    auth_service: AuthService, group_name: str, quiet: bool = False, force: bool = False
) -> Optional[str]:
    """Create a bootstrap token for a group.

    Args:
        auth_service: AuthService instance
        group_name: Name of the group
        quiet: Suppress output
        force: Force creation even if token exists

    Returns:
        JWT token string, or None if skipped due to existing token
    """
    # Check for existing token unless forced
    if not force:
        if has_existing_bootstrap_token(auth_service, group_name, quiet):
            return None

    try:
        token = auth_service.create_token(
            groups=[group_name],
            expires_in_seconds=BOOTSTRAP_TOKEN_EXPIRY,
        )

        expires_days = BOOTSTRAP_TOKEN_EXPIRY // (24 * 60 * 60)
        log_success(f"Created new token for '{group_name}' (expires: {expires_days} days)", quiet)

        return token
    except Exception as e:
        log_error(f"Failed to create token for '{group_name}': {e}")
        return None


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args()
    quiet = args.quiet

    # Set up environment with defaults
    prefix = setup_env_defaults(args.prefix, args)

    # Display configuration
    backend = os.environ.get(f"{prefix}_AUTH_BACKEND", "vault")
    vault_url = os.environ.get(f"{prefix}_VAULT_URL", "not set")

    log_info(f"=== GOFR Auth Bootstrap ({prefix}) ===", quiet)
    log_info(f"Backend: {backend}", quiet)
    if backend == "vault":
        log_info(f"Vault URL: {vault_url}", quiet)
        vault_token = os.environ.get(f"{prefix}_VAULT_TOKEN", "")
        if vault_token:
            log_info(f"Vault Token: {vault_token[:16]}...", quiet)
    log_info("", quiet)

    # Create auth service
    try:
        auth_service, jwt_secret = get_auth_service(prefix)
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Failed to initialize auth service: {e}")
        return 1

    # Ensure groups exist
    log_info("Ensuring reserved groups...", quiet)
    if not ensure_groups(auth_service, quiet):
        log_error("Failed to ensure all reserved groups exist")
        return 1

    # Install Vault policies (for Vault backend only)
    if not install_vault_policies(prefix, quiet):
        log_warn("Policy installation failed, continuing anyway")

    # Store JWT secret in Vault (for services to read)
    if not store_jwt_secret_in_vault(prefix, jwt_secret, quiet):
        log_warn("JWT secret storage failed, continuing anyway")

    # Create bootstrap tokens if requested
    if not args.groups_only:
        log_info("", quiet)
        log_info("Creating bootstrap tokens...", quiet)

        tokens = {}
        tokens_skipped = []

        for group_name in ["public", "admin"]:
            token = create_bootstrap_token(auth_service, group_name, quiet, force=args.force_tokens)
            if token:
                tokens[group_name] = token
            else:
                # Token was skipped (already exists)
                tokens_skipped.append(group_name)

        # Output tokens to stdout (for shell capture) only if we have new tokens
        if tokens:
            log_info("", quiet)
            log_info("=== Bootstrap Tokens ===", quiet)

            for group_name, token in tokens.items():
                var_name = f"{prefix}_{group_name.upper()}_TOKEN"
                print(f"{var_name}={token}")

            # Save tokens to SSOT file (secrets/bootstrap_tokens.json)
            secrets_dir = Path(__file__).parent.parent / "secrets"
            secrets_dir.mkdir(parents=True, exist_ok=True)
            tokens_file = secrets_dir / "bootstrap_tokens.json"
            tokens_data = {
                "admin_token": tokens.get("admin", ""),
                "public_token": tokens.get("public", ""),
            }
            # Merge with existing tokens if file exists (preserve tokens we didn't regenerate)
            if tokens_file.exists():
                try:
                    import json

                    existing = json.loads(tokens_file.read_text())
                    for key in ["admin_token", "public_token"]:
                        if not tokens_data.get(key) and existing.get(key):
                            tokens_data[key] = existing[key]
                except Exception:
                    pass
            import json

            tokens_file.write_text(json.dumps(tokens_data, indent=2))
            tokens_file.chmod(0o600)
            log_success(f"Tokens saved to {tokens_file}", quiet)

            log_info("", quiet)
            log_info("To use these tokens:", quiet)
            log_info(f'  eval "$(python {Path(__file__).name} --prefix {prefix})"', quiet)

        if tokens_skipped:
            log_info("", quiet)
            log_info(f"Skipped groups (already have tokens): {', '.join(tokens_skipped)}", quiet)
            log_info("Use --force-tokens to create new tokens", quiet)
    else:
        log_info("", quiet)
        log_info("Groups only mode - no tokens created", quiet)

    log_info("", quiet)
    log_info("Bootstrap complete!", quiet)

    return 0


if __name__ == "__main__":
    sys.exit(main())
