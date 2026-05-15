#!/usr/bin/env python3
"""
SINGLE SOURCE OF TRUTH (SSOT) Environment Module
=================================================

This module is the ONLY place scripts should load tokens and environment config.
Created by bootstrap.py, consumed by ALL simulation/test/app scripts.

Usage:
    from gofr_common.gofr_env import get_admin_token, get_public_token, get_token_for_group
    from gofr_common.gofr_env import get_vault_client  # For AppRole auth

SSOT Files (managed by bootstrap.py):
    - secrets/bootstrap_tokens.json           → JWT tokens (admin/public)
    - lib/gofr-common/config/gofr_ports.env   → Port configuration
    - docker/.env                             → Docker config (JWT_SECRET, etc)
    - secrets/vault_root_token                → Vault root token (Zero-Trust Bootstrap)
    - /run/secrets/vault_creds                → AppRole credentials (container)

Token Keys:
    - admin_token  → Full admin access (source management, group management)
    - public_token → Public/read-only access

Group Mappings:
    - "admin" / "group-simulation" → admin_token
    - "public"                     → public_token

Vault Authentication Priority:
    1. AppRole (if /run/secrets/vault_creds exists) - Container runtime
    2. Root Token from secrets/vault_root_token     - Dev/Bootstrap
    3. Environment VAULT_TOKEN                      - Legacy fallback
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from gofr_common.auth.backends.vault_client import VaultClient
    from gofr_common.auth.identity import VaultIdentity

# Resolve workspace root (handles imports from any depth)
# lib/gofr-common/src/gofr_common/gofr_env.py → workspace
_THIS_FILE = Path(__file__).resolve()
WORKSPACE_ROOT = _THIS_FILE.parent.parent.parent.parent.parent

# SSOT file locations
BOOTSTRAP_TOKENS_FILE = WORKSPACE_ROOT / "secrets" / "bootstrap_tokens.json"
SIMULATION_TOKENS_FILE = WORKSPACE_ROOT / "simulation" / "tokens.json"
PORTS_ENV_FILE = WORKSPACE_ROOT / "lib" / "gofr-common" / "config" / "gofr_ports.env"
SECRETS_DIR = WORKSPACE_ROOT / "secrets"
ROOT_TOKEN_FILE = SECRETS_DIR / "vault_root_token"

# Standard AppRole credentials path (container runtime)
APPROLE_CREDS_PATH = "/run/secrets/vault_creds"

# Cache loaded tokens
_tokens_cache: Optional[Dict[str, str]] = None
_simulation_tokens_cache: Optional[Dict[str, str]] = None
# Singleton for VaultIdentity
_vault_identity: Optional["VaultIdentity"] = None


class GofrEnvError(Exception):
    """Raised when SSOT files are missing or invalid."""

    pass


def _load_tokens() -> Dict[str, str]:
    """Load tokens from SSOT file (cached)."""
    global _tokens_cache
    if _tokens_cache is not None:
        return _tokens_cache

    if not BOOTSTRAP_TOKENS_FILE.exists():
        raise GofrEnvError(
            f"SSOT token file not found: {BOOTSTRAP_TOKENS_FILE}\n"
            f"Run: uv run python scripts/bootstrap.py"
        )

    try:
        with open(BOOTSTRAP_TOKENS_FILE) as f:
            data = json.load(f)
        _tokens_cache = data
        return data
    except json.JSONDecodeError as e:
        raise GofrEnvError(f"Invalid JSON in {BOOTSTRAP_TOKENS_FILE}: {e}")


def _load_simulation_tokens() -> Dict[str, str]:
    """Load simulation group tokens from simulation/tokens.json (cached, optional)."""
    global _simulation_tokens_cache
    if _simulation_tokens_cache is not None:
        return _simulation_tokens_cache

    if not SIMULATION_TOKENS_FILE.exists():
        _simulation_tokens_cache = {}
        return {}

    try:
        with open(SIMULATION_TOKENS_FILE) as f:
            data = json.load(f)
        _simulation_tokens_cache = data
        return data
    except json.JSONDecodeError:
        _simulation_tokens_cache = {}
        return {}


def get_admin_token() -> str:
    """Get the admin JWT token. Use for source/group management."""
    tokens = _load_tokens()
    token = tokens.get("admin_token")
    if not token:
        raise GofrEnvError("admin_token not found in bootstrap_tokens.json")
    return token


def get_public_token() -> str:
    """Get the public JWT token. Use for read-only operations."""
    tokens = _load_tokens()
    token = tokens.get("public_token")
    if not token:
        raise GofrEnvError("public_token not found in bootstrap_tokens.json")
    return token


def get_token_for_group(group: str) -> str:
    """
    Get the appropriate token for a group name.

    Token Resolution Priority:
    1. Simulation tokens (simulation/tokens.json) - group-specific tokens
    2. Bootstrap tokens (secrets/bootstrap_tokens.json) - admin/public
    3. Hardcoded mappings (fallback for backwards compatibility)

    Standard Mappings:
        - "admin"            → admin_token (bootstrap)
        - "group-simulation" → group token if available, else admin_token
        - "public"           → public_token (bootstrap)

    Raises GofrEnvError if group is unknown.
    """
    # Check simulation tokens first (principle of least privilege)
    sim_tokens = _load_simulation_tokens()
    if group in sim_tokens:
        return sim_tokens[group]

    # Check bootstrap tokens
    bootstrap_tokens = _load_tokens()
    if group in bootstrap_tokens:
        return bootstrap_tokens[group]

    # Fallback mappings for backwards compatibility
    ADMIN_GROUPS = {"admin"}
    PUBLIC_GROUPS = {"public"}
    SIMULATION_GROUPS = {"group-simulation"}

    if group in ADMIN_GROUPS:
        return get_admin_token()
    elif group in PUBLIC_GROUPS:
        return get_public_token()
    elif group in SIMULATION_GROUPS:
        # Fallback to admin if no group token exists (backwards compatibility)
        return get_admin_token()
    else:
        raise GofrEnvError(
            f"Unknown group '{group}'. Known groups: admin, group-simulation, public"
        )


def get_all_tokens() -> Dict[str, str]:
    """Get raw token dict. Prefer specific accessors above."""
    return _load_tokens().copy()


def get_workspace_root() -> Path:
    """Get the workspace root path."""
    return WORKSPACE_ROOT


def load_env_file(filepath: Path) -> Dict[str, str]:
    """Parse a .env file into a dict (does NOT modify os.environ)."""
    env = {}
    if not filepath.exists():
        return env
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip quotes
                value = value.strip().strip('"').strip("'")
                env[key.strip()] = value
    return env


def get_api_base_url() -> str:
    """Get the API base URL from port config."""
    ports = load_env_file(PORTS_ENV_FILE)
    host = os.environ.get("GOFR_API_HOST", "localhost")
    port = ports.get("GOFR_WEB_PORT", "8000")
    return f"http://{host}:{port}"


# =============================================================================
# Vault Client Factory (AppRole-aware)
# =============================================================================


def get_vault_client(creds_path: Optional[str] = None) -> "VaultClient":
    """
    Get an authenticated VaultClient using the best available method.

    Priority:
        1. AppRole (if /run/secrets/vault_creds exists) - Production containers
        2. Root Token from secrets/vault_root_token     - Dev/Bootstrap
        3. Environment VAULT_TOKEN                      - Legacy fallback

    Args:
        creds_path: Override path to AppRole credentials (for testing)

    Returns:
        Authenticated VaultClient

    Raises:
        GofrEnvError: If no authentication method is available
    """
    from gofr_common.auth.backends.vault_client import VaultClient
    from gofr_common.auth.backends.vault_config import VaultConfig
    from gofr_common.auth.identity import VaultIdentity

    global _vault_identity

    check_path = creds_path or APPROLE_CREDS_PATH
    vault_addr = os.getenv("VAULT_ADDR", "http://gofr-vault:8201")

    # Strategy 1: AppRole (container runtime)
    if VaultIdentity.is_available(check_path):
        if _vault_identity is None:
            _vault_identity = VaultIdentity(creds_path=check_path, vault_addr=vault_addr)
            _vault_identity.login()
            _vault_identity.start_renewal()
        return _vault_identity.get_client()

    # Strategy 2: Root Token from secure enclave (dev/bootstrap)
    if ROOT_TOKEN_FILE.exists():
        root_token = ROOT_TOKEN_FILE.read_text().strip()
        config = VaultConfig(url=vault_addr, token=root_token)
        return VaultClient(config)

    # Strategy 3: Environment variable (legacy)
    env_token = os.getenv("VAULT_TOKEN")
    if env_token:
        config = VaultConfig(url=vault_addr, token=env_token)
        return VaultClient(config)

    raise GofrEnvError(
        "No Vault authentication available. Options:\n"
        f"  1. Mount credentials to {APPROLE_CREDS_PATH} (container)\n"
        f"  2. Run bootstrap.py to create {ROOT_TOKEN_FILE}\n"
        "  3. Set VAULT_TOKEN environment variable"
    )


def shutdown_vault_identity() -> None:
    """Gracefully stop the VaultIdentity renewal thread (call on app shutdown)."""
    global _vault_identity
    if _vault_identity is not None:
        _vault_identity.stop()
        _vault_identity = None


# Convenience: print SSOT status when run directly
if __name__ == "__main__":
    print("=== GOFR SSOT Environment Check ===\n")
    print(f"Workspace Root: {WORKSPACE_ROOT}")
    print(f"Token File:     {BOOTSTRAP_TOKENS_FILE}")
    print(f"  Exists:       {BOOTSTRAP_TOKENS_FILE.exists()}")

    if BOOTSTRAP_TOKENS_FILE.exists():
        tokens = _load_tokens()
        print(f"  Keys:         {list(tokens.keys())}")
        print(f"\nAdmin Token:    {get_admin_token()[:20]}...")
        print(f"Public Token:   {get_public_token()[:20]}...")
        print(f"API Base URL:   {get_api_base_url()}")
    else:
        print("\n⚠️  Run bootstrap.py first!")

    # Vault client status
    print("\n--- Vault Client ---")
    print(f"AppRole Path:   {APPROLE_CREDS_PATH}")
    print(f"  Available:    {Path(APPROLE_CREDS_PATH).exists()}")
    print(f"Root Token:     {ROOT_TOKEN_FILE}")
    print(f"  Available:    {ROOT_TOKEN_FILE.exists()}")
    print(f"Env VAULT_TOKEN: {'set' if os.getenv('VAULT_TOKEN') else 'not set'}")
