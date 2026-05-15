# GOFR Auth Module

## Overview

The `gofr_common.auth` module provides JWT-based authentication with multi-group access control for GOFR microservices. This document is designed for LLM-assisted integration and migration from the previous single-group token system.

---

## Key Concepts

### Multi-Group Tokens (New in v2)

Tokens now support **multiple groups** instead of a single group:

```python
# OLD (v1) - Single group per token
token = auth.create_token(group="admin")
info.group  # "admin" (string)

# NEW (v2) - Multiple groups per token  
token = auth.create_token(groups=["admin", "users"])
info.groups  # ["admin", "users"] (list)
```

### Reserved Groups

Two groups are **always present** and **cannot be made defunct**:

| Group | Purpose | Auto-included |
|-------|---------|---------------|
| `public` | Universal access - automatically added when resolving any valid token | Yes |
| `admin` | Administrative operations (group/token management) | No |

### Soft-Delete Architecture

- **Groups** can be made defunct but never deleted
- **Tokens** can be revoked but never deleted
- Token store is keyed by UUID, not the JWT string
- Full audit trail preserved

---

## Store Configuration (Vault-only)

Vault is the only supported backend for tokens and groups.

```python
from gofr_common.auth import AuthService, GroupRegistry
from gofr_common.auth.backends import VaultConfig, VaultClient, VaultGroupStore, VaultTokenStore

# Configure Vault from environment
vault_config = VaultConfig.from_env("GOFR_DIG")
vault_client = VaultClient(vault_config)

token_store = VaultTokenStore(vault_client)
group_store = VaultGroupStore(vault_client)
group_registry = GroupRegistry(store=group_store)

auth = AuthService(
    token_store=token_store,
    group_registry=group_registry,
    env_prefix="GOFR_DIG",
)
```

Environment variables:
- `GOFR_DIG_VAULT_URL` (required)
- `GOFR_DIG_VAULT_TOKEN` or `GOFR_DIG_VAULT_ROLE_ID` + `GOFR_DIG_VAULT_SECRET_ID`
- `GOFR_DIG_VAULT_MOUNT` (default: secret)
- `GOFR_DIG_VAULT_PATH_PREFIX` (default: gofr/auth)

---

## Migration Guide (v1 → v2)

### Breaking Changes

1. **`create_token` signature changed**
   ```python
   # OLD
   token = auth.create_token(group="admin", expires_in_seconds=3600)
   
   # NEW  
   token = auth.create_token(groups=["admin"], expires_in_seconds=3600)
   ```

2. **`TokenInfo.group` → `TokenInfo.groups`**
   ```python
   # OLD
   if info.group == "admin": ...
   
   # NEW
   if "admin" in info.groups: ...
   # Or use helper methods:
   if info.has_group("admin"): ...
   ```

3. **Token store format changed**
   ```json
   // OLD: Keyed by JWT string
   {"eyJhbG...": {"group": "admin", "created_at": "..."}}
   
   // NEW: Keyed by UUID
   {"550e8400-...": {"id": "550e8400-...", "groups": ["admin"], "status": "active", ...}}
   ```

4. **`get_group_for_token()` removed** - Use `resolve_token_groups()` instead

### Migration Steps

1. **Update token creation calls**
   ```python
   # Find and replace
   auth.create_token(group="X")  →  auth.create_token(groups=["X"])
   ```

2. **Update token verification usage**
   ```python
   # Find and replace
   info.group  →  info.groups[0]  # If you need single group
   info.group == "X"  →  info.has_group("X")  # For checks
   ```

3. **Run bootstrap script** to create reserved groups
   ```bash
   python scripts/init_auth.py --data-dir /path/to/auth/data
   ```

4. **Migrate existing tokens** (if needed)
   - Old tokens will fail validation (different store format)
   - Issue new tokens to all clients
   - Old token store can be archived

---

## API Reference

### AuthService

```python
from gofr_common.auth import AuthService

token_store, group_store = create_stores_from_env("GOFR")
groups = GroupRegistry(store=group_store)

auth = AuthService(
    token_store=token_store,
    group_registry=groups,
    env_prefix="GOFR",                   # For env var fallback
    audience="my-api",                   # JWT audience claim
)
```

#### Token Operations

```python
# Create token
token = auth.create_token(
    groups=["admin", "users"],
    expires_in_seconds=86400,  # 24 hours
    fingerprint="device-hash",  # Optional
)

# Verify token (raises TokenNotFoundError, TokenRevokedError, or ValueError)
info: TokenInfo = auth.verify_token(token)
print(info.groups)      # ["admin", "users"]
print(info.expires_at)  # datetime

# Verify without store lookup (signature only)
info = auth.verify_token(token, stateless=True)

# Revoke token (soft-delete)
auth.revoke_token(token)

# List tokens
all_tokens: List[TokenRecord] = auth.list_tokens()
active_only = auth.list_tokens(status="active")
revoked_only = auth.list_tokens(status="revoked")

# Resolve token to Group objects (public always included)
groups: List[Group] = auth.resolve_token_groups(token)
```

#### Group Operations (via registry)

```python
# Access group registry
registry = auth.groups

# Create group
group = registry.create_group("editors", "Can edit content")

# Get groups
group = registry.get_group_by_name("editors")
group = registry.get_group(uuid_obj)

# List groups
active_groups = registry.list_groups()
all_groups = registry.list_groups(include_defunct=True)

# Make group defunct (soft-delete)
registry.make_defunct(group.id)

# Get reserved groups
public = registry.get_reserved_group("public")
admin = registry.get_reserved_group("admin")
```

### TokenInfo

```python
@dataclass
class TokenInfo:
    token: str                      # The JWT string
    groups: List[str]               # Group names
    expires_at: Optional[datetime]  # Expiration time
    issued_at: datetime             # Creation time
    
    # Helper methods
    def has_group(self, name: str) -> bool: ...
    def has_any_group(self, names: List[str]) -> bool: ...
    def has_all_groups(self, names: List[str]) -> bool: ...
```

### TokenRecord

```python
@dataclass
class TokenRecord:
    id: UUID                        # Unique identifier
    groups: List[str]               # Group names
    status: Literal["active", "revoked"]
    created_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    fingerprint: Optional[str]
    
    @property
    def is_expired(self) -> bool: ...
    @property
    def is_valid(self) -> bool: ...  # active AND not expired
```

### Group

```python
@dataclass
class Group:
    id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    defunct_at: Optional[datetime]
    is_reserved: bool  # True for public, admin
```

---

## FastAPI Integration

### Basic Setup

```python
from fastapi import FastAPI, Depends
from gofr_common.auth import (
    AuthService,
    TokenInfo,
    init_auth_service,
    verify_token,
    require_admin,
    require_group,
    require_any_group,
    require_all_groups,
)

app = FastAPI()

# Initialize auth service on startup
@app.on_event("startup")
async def startup():
    init_auth_service(
        secret_key="your-secret",
        token_store_path="/data/auth/tokens.json",
    )
```

### Endpoint Protection

```python
# Any valid token required
@app.get("/profile")
def get_profile(token: TokenInfo = Depends(verify_token)):
    return {"groups": token.groups}

# Admin required
@app.post("/groups")
def create_group(token: TokenInfo = Depends(require_admin)):
    # Only tokens with "admin" group reach here
    ...

# Specific group required
@app.get("/reports")
def get_reports(token: TokenInfo = Depends(require_group("analysts"))):
    ...

# Any of multiple groups
@app.get("/dashboard")
def get_dashboard(token: TokenInfo = Depends(require_any_group(["admin", "managers"]))):
    ...

# All groups required
@app.post("/audit")
def create_audit(token: TokenInfo = Depends(require_all_groups(["admin", "compliance"]))):
    ...
```

### Optional Authentication

```python
from gofr_common.auth import optional_verify_token

@app.get("/public-or-enhanced")
def mixed_endpoint(token: Optional[TokenInfo] = Depends(optional_verify_token)):
    if token and token.has_group("premium"):
        return {"data": "enhanced content"}
    return {"data": "basic content"}
```

---

## Testing Patterns

### Pytest Fixtures

```python
import pytest
from gofr_common.auth import AuthService, init_auth_service

@pytest.fixture
def auth_service():
    """Isolated in-memory auth service for each test."""
    auth = AuthService(
        secret_key="test-secret-key",
        token_store_path=":memory:",
    )
    init_auth_service(auth_service=auth)
    return auth

@pytest.fixture
def admin_token(auth_service):
    """Pre-created admin token."""
    return auth_service.create_token(groups=["admin"])

@pytest.fixture
def user_token(auth_service):
    """Pre-created user token."""
    # Create the users group first
    auth_service.groups.create_group("users", "Regular users")
    return auth_service.create_token(groups=["users"])
```

### Test Examples

```python
def test_admin_endpoint_rejects_user(client, user_token):
    response = client.post(
        "/admin/groups",
        headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403

def test_admin_endpoint_accepts_admin(client, admin_token):
    response = client.post(
        "/admin/groups",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "testers"}
    )
    assert response.status_code == 200

def test_multi_group_token(auth_service):
    # Create custom group
    auth_service.groups.create_group("editors")
    
    # Token with multiple groups
    token = auth_service.create_token(groups=["admin", "editors"])
    info = auth_service.verify_token(token)
    
    assert info.has_group("admin")
    assert info.has_group("editors")
    assert info.has_all_groups(["admin", "editors"])
```

---

## Bootstrap Script

For first-time setup or data recovery:

```bash
# Create reserved groups and admin token
python scripts/init_auth.py --data-dir /path/to/auth/data

# Output:
# Created groups.json with reserved groups: public, admin
# Created tokens.json with admin token
# 
# Admin token (save this!):
# eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

The script:
1. Creates `groups.json` with `public` and `admin` groups
2. Creates `tokens.json` with an initial admin token (100-year expiry)
3. Outputs the admin JWT for initial system access

---

## Exceptions

```python
from gofr_common.auth import (
    InvalidGroupError,      # Group doesn't exist or is defunct
    TokenNotFoundError,     # Token UUID not in store
    TokenRevokedError,      # Token has been revoked
    GroupRegistryError,     # Base for group errors
    ReservedGroupError,     # Can't modify reserved groups
    DuplicateGroupError,    # Group name already exists
    GroupNotFoundError,     # Group not found
)
```

---

## Storage Format Reference

### tokens.json

```json
{
  "550e8400-e29b-41d4-a716-446655440000": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "groups": ["admin"],
    "status": "active",
    "created_at": "2024-01-15T10:30:00",
    "expires_at": "2024-02-14T10:30:00",
    "revoked_at": null,
    "fingerprint": null
  }
}
```

### groups.json

```json
{
  "550e8400-e29b-41d4-a716-446655440001": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "public",
    "description": "Universal access group",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00",
    "defunct_at": null,
    "is_reserved": true
  },
  "550e8400-e29b-41d4-a716-446655440002": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "admin",
    "description": "Administrative access",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00",
    "defunct_at": null,
    "is_reserved": true
  }
}
```

---

## Quick Reference

### Imports

```python
# Core
from gofr_common.auth import AuthService, TokenInfo, TokenRecord

# Groups
from gofr_common.auth import Group, GroupRegistry, RESERVED_GROUPS

# FastAPI middleware
from gofr_common.auth import (
    init_auth_service,
    verify_token,
    optional_verify_token,
    require_admin,
    require_group,
    require_any_group,
    require_all_groups,
)

# Exceptions
from gofr_common.auth import (
    InvalidGroupError,
    TokenNotFoundError,
    TokenRevokedError,
    ReservedGroupError,
    DuplicateGroupError,
    GroupNotFoundError,
)
```

### Common Patterns

```python
# Check if user is admin
if token_info.has_group("admin"): ...

# Check if user can access resource
if token_info.has_any_group(["admin", "editors", "viewers"]): ...

# Require multiple permissions
if token_info.has_all_groups(["verified", "premium"]): ...

# Get all groups including auto-added public
groups = auth.resolve_token_groups(token)
# groups always contains "public" group
```
