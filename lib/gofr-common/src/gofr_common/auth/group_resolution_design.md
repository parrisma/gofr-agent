# Group Resolution Design

## Overview

This document defines the design for group-based authentication and authorization
in the GoFr system. Groups are identified by both a human-readable **name** and a
system-generated **UUID**. This design clarifies when each identifier is used.

## Core Principle

**Group names flow through the auth system; UUIDs are resolved at point of use.**

## Data Model

### Group Entity
```
Group:
  - id: UUID (system-generated, immutable)
  - name: str (human-readable, unique, immutable after creation)
  - description: str (optional)
  - status: active | defunct
```

### JWT Token Claims
```json
{
  "sub": "token-id",
  "groups": ["premium", "public"],  // ← Group NAMES, not UUIDs
  "exp": 1736294400,
  "iat": 1736208000
}
```

## Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Create Group                                                    │
│     name="premium", uuid=abc-123-...                                │
│     Stored in Vault: groups/premium → {id: "abc-123-...", ...}      │
│                                                                     │
│  2. Create Token                                                    │
│     groups=["premium", "public"]  ← names, not UUIDs                │
│     Groups must exist at token creation time                        │
│                                                                     │
│  3. MCP Call with JWT Token                                         │
│     Authorization: Bearer <jwt>                                     │
│                                                                     │
│  4. group_service extracts groups from token                        │
│     resolve_write_group() → "premium"  ← returns NAME               │
│     get_permitted_groups() → ["premium", "public"]  ← returns NAMES │
│                                                                     │
│  5. Authorization Check (by name)                                   │
│     Admin check: "admin" in groups?  ← name comparison              │
│     Group access: "premium" in permitted_groups?                    │
│                                                                     │
│  6. Write Group Selection                                           │
│     write_group = groups[0]  ← "premium" (name)                     │
│                                                                     │
│  7. UUID Resolution (at point of use)                               │
│     When storing data that requires group UUID:                     │
│     group_uuid = get_group_uuid_by_name("premium")                  │
│     source = Source(group_guid=group_uuid, ...)                     │
└─────────────────────────────────────────────────────────────────────┘
```

## API Functions

### group_service.py (gofr-iq)

| Function | Returns | Purpose |
|----------|---------|---------|
| `resolve_write_group()` | `str` (name) | Get primary write group name |
| `resolve_permitted_groups()` | `list[str]` (names) | Get all readable group names |
| `get_group_uuid_by_name()` | `str` (UUID) | Convert name → UUID |

### Usage Example

```python
# In a tool that creates a Source
from app.services.group_service import resolve_write_group, get_group_uuid_by_name

def create_source(name: str, url: str, auth_tokens: list[str] | None = None):
    # Step 6: Get write group NAME
    write_group_name = resolve_write_group(auth_tokens)
    if not write_group_name:
        raise PermissionError("No write access")
    
    # Step 7: Convert to UUID for storage
    group_uuid = get_group_uuid_by_name(write_group_name)
    if not group_uuid:
        raise ValueError(f"Group not found: {write_group_name}")
    
    # Create source with UUID
    source = Source(
        name=name,
        url=url,
        group_guid=group_uuid,  # UUID for data storage
        ...
    )
```

## Rationale

1. **Names are human-readable**: Easier to debug, log, and understand
2. **Names in tokens**: Tokens remain readable and don't expose internal IDs
3. **UUIDs for data storage**: Immutable references that survive group renames
4. **Late binding**: UUID resolution happens only when needed
5. **Single source of truth**: Auth service owns group name→UUID mapping

## Reserved Groups

| Name | Purpose |
|------|---------|
| `public` | Default group for unauthenticated access |
| `admin` | Administrative privileges |

These groups are created during bootstrap and should always exist.

## Error Handling

- **Group not found**: If `get_group_uuid_by_name()` returns `None`, the group
  doesn't exist or is defunct. Caller should raise appropriate error.
- **No write access**: If `resolve_write_group()` returns `None` when auth is
  enabled, the user is anonymous and cannot write.
