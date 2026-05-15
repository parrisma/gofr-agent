# Auth Service Refactoring Specification

> Note: Memory and file backends have been removed. Vault is the only supported
> storage backend. Historical references to memory/file stores below are kept
> for context only.

## Requirements

1. **Central Register of Groups**
   - 1.1 Groups can be created and made defunct but NEVER deleted
   - 1.2 A group has a string name, an optional description, and a GUID
   - 1.3 Reserved groups (`public`, `admin`) always exist and cannot be made defunct

2. **Central Register of Access Tokens**
   - 2.1 Tokens can be created and revoked but never deleted
   - 2.2 A token has an optional expiry at which point it becomes revoked
   - 2.3 A token points to a list of one or more groups
   - 2.4 A group can be pointed at by zero or more tokens
   - 2.5 Tokens are signed to prove authenticity

3. **Token Validation**
   - Tokens can be validated by signature and then resolved into the associated list of groups
   - The `public` group is always included in resolved groups for any valid token

4. **Reserved Groups**
   - `public`: Automatically added to every token's resolved groups. Cannot be defunct.
   - `admin`: Required for group/token management operations. Cannot be defunct.
   - Reserved groups are bootstrapped via init script (direct store access)

5. **Authorization**
   - Creating/modifying groups requires `admin` group membership
   - Creating/revoking tokens requires `admin` group membership
   - Resolving tokens does NOT require admin (read-only operation)

---

## Phased Implementation Plan

### Phase 1: Create Group Model and Registry

**Goal:** Introduce the `Group` model and `GroupRegistry` with reserved groups support.

**Status:** ✅ COMPLETE

#### Step 1.1: Create Group Model
- [x] Add `Group` dataclass with: `id` (UUID), `name` (str), `description` (Optional[str]), `is_active` (bool), `created_at`, `defunct_at` (Optional), `is_reserved` (bool)
- [x] Add `to_dict()` and `from_dict()` for serialization
- [x] Add tests for `Group` creation and serialization
- [x] Run tests: `./scripts/run_tests.sh -k "test_group"`

#### Step 1.2: Create GroupRegistry Class
- [x] Add `GroupRegistry` class with in-memory and file-based storage
- [x] Define `RESERVED_GROUPS = {"public", "admin"}`
- [x] Implement `create_group(name, description=None) -> Group` (reject reserved names)
- [x] Implement `get_group(group_id: UUID) -> Optional[Group]`
- [x] Implement `get_group_by_name(name: str) -> Optional[Group]`
- [x] Implement `list_groups(include_defunct=False) -> List[Group]`
- [x] Implement `make_defunct(group_id: UUID) -> bool` (reject reserved groups)
- [x] Add `ensure_reserved_groups()` method for bootstrap
- [x] Add tests for all GroupRegistry methods including reserved group protection
- [x] Run tests: `./scripts/run_tests.sh -k "test_group"`

#### Step 1.3: Create Bootstrap Script
- [x] Create `scripts/init_auth.py` for bootstrapping
- [x] Script creates `public` and `admin` groups directly in store
- [x] Script creates initial admin token with `admin` group
- [x] Script outputs admin token to stdout/file for initial setup
- [x] Add documentation for bootstrap process
- [x] Run tests: `./scripts/run_tests.sh -k "test_group"` (40 tests pass)

---

### Phase 2: Create New Token Models

**Goal:** Define new token data structures.

**Status:** ✅ COMPLETE

#### Step 2.1: Create TokenRecord Model
- [x] Add `TokenRecord` dataclass with:
  - `id` (UUID) - unique token identifier
  - `groups` (List[str]) - list of group names
  - `status` (Literal["active", "revoked"]) 
  - `created_at` (datetime)
  - `expires_at` (Optional[datetime])
  - `revoked_at` (Optional[datetime])
  - `fingerprint` (Optional[str])
- [x] Add `to_dict()` and `from_dict()` for serialization
- [x] Add `is_expired` property
- [x] Add `is_valid` property (active and not expired)
- [x] Add tests for TokenRecord
- [x] Run tests: `./scripts/run_tests.sh -k "test_token_record"`

#### Step 2.2: Update TokenInfo
- [x] Change `TokenInfo` to have `groups: List[str]` instead of `group: str`
- [x] Add `has_group()`, `has_any_group()`, `has_all_groups()` helper methods
- [x] Update existing tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_token_info"` (321 tests pass)

---

### Phase 3: Rewrite AuthService

**Goal:** Replace AuthService internals with new architecture.

**Status:** ✅ COMPLETE

#### Step 3.1: Update Token Store Structure
- [x] Change token store to be keyed by UUID string (not JWT)
- [x] Store `TokenRecord` data in store
- [x] Update `_load_token_store()` and `_save_token_store()`
- [x] Add tests for new store format
- [x] Run tests: `./scripts/run_tests.sh -k "test_auth"`

#### Step 3.2: Integrate GroupRegistry
- [x] Add `GroupRegistry` as required component of `AuthService`
- [x] Share storage path logic between token store and group registry
- [x] Add `auth.groups` property to access registry
- [x] Call `ensure_reserved_groups()` on init (creates if missing)
- [x] Add tests for integrated service
- [x] Run tests: `./scripts/run_tests.sh`

#### Step 3.3: Rewrite create_token
- [x] Change signature to `create_token(groups: List[str], ...)`
- [x] Validate all groups exist in registry and are active
- [x] Auto-generate UUID for token
- [x] Store `TokenRecord` in store (keyed by UUID)
- [x] Return signed JWT containing UUID and groups
- [x] **Note:** Admin check enforced at middleware level, not here
- [x] Update tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_create"`

#### Step 3.4: Rewrite verify_token
- [x] Decode JWT and extract UUID
- [x] Look up `TokenRecord` by UUID
- [x] Check status is "active"
- [x] Check not expired
- [x] Return `TokenInfo` with groups list
- [x] Update tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_verify"`

#### Step 3.5: Rewrite revoke_token
- [x] Accept token JWT string
- [x] Extract UUID from JWT
- [x] Set `TokenRecord.status = "revoked"` and `revoked_at = now`
- [x] Do NOT delete from store
- [x] **Note:** Admin check enforced at middleware level, not here
- [x] Update tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_revoke"`

#### Step 3.6: Update list_tokens
- [x] Return all `TokenRecord` entries with full metadata
- [x] Add optional `status` filter parameter
- [x] Update tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_list"` (326 tests pass)

#### Step 3.7: Update Bootstrap Script
- [x] Update `scripts/init_auth.py` to create admin token
- [x] Script outputs admin JWT to stdout for initial setup

---

### Phase 4: Add Group Resolution

**Goal:** Add method to resolve token to Group objects with `public` auto-inclusion.

**Status:** ✅ COMPLETE (implemented in Phase 3)

#### Step 4.1: Add resolve_token_groups
- [x] Add `resolve_token_groups(token: str, include_defunct=False) -> List[Group]`
- [x] Verify token, get group names from TokenInfo
- [x] Look up each group in registry
- [x] **Always include `public` group in result** (even if not in token)
- [x] Return list of Group objects
- [x] Add tests (verify public always present)
- [x] Run tests: `./scripts/run_tests.sh -k "test_resolve"`

#### Step 4.2: Remove get_group_for_token
- [x] Delete `get_group_for_token()` method
- [x] Update any internal usages
- [x] Remove old tests
- [x] Run tests: `./scripts/run_tests.sh`

---

### Phase 5: Update Middleware

**Goal:** Update FastAPI middleware for multi-group tokens with admin enforcement.

**Status:** ✅ COMPLETE

#### Step 5.1: Update verify_token Dependency
- [x] Update to return `TokenInfo` with `groups: List[str]`
- [x] Update tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_middleware"`

#### Step 5.2: Add Authorization Helpers
- [x] Add `require_group(group_name: str)` dependency
- [x] Add `require_any_group(group_names: List[str])` dependency  
- [x] Add `require_all_groups(group_names: List[str])` dependency
- [x] Add `require_admin()` dependency (convenience for `require_group("admin")`)
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh` (338 tests pass)

---

### Phase 6: Update Exports and Documentation

**Goal:** Clean up public API.

**Status:** ✅ COMPLETE

#### Step 6.1: Update __init__.py
- [x] Export `Group`, `GroupRegistry`, `TokenRecord`
- [x] Export `RESERVED_GROUPS` constant
- [x] Export authorization helpers including `require_admin`
- [x] Update module docstring

#### Step 6.2: Update All Docstrings
- [x] Update `AuthService` class docstring
- [x] Update all public method docstrings
- [x] Add usage examples
- [x] Document reserved groups behavior

#### Step 6.3: Final Test Run
- [x] Run full test suite: `./scripts/run_tests.sh`
- [x] Verify all tests pass (338 tests)

---

## Data Models (Final)

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

### TokenRecord
```python
@dataclass  
class TokenRecord:
    id: UUID
    groups: List[str]
    status: Literal["active", "revoked"]
    created_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    fingerprint: Optional[str]
```

### TokenInfo (returned from verify)
```python
@dataclass
class TokenInfo:
    token: str
    groups: List[str]
    expires_at: Optional[datetime]
    issued_at: datetime
```

---

## Reserved Groups

### Constants
```python
RESERVED_GROUPS = frozenset({"public", "admin"})
```

### Behavior

| Group | Purpose | Auto-included | Can be Defunct |
|-------|---------|---------------|----------------|
| `public` | Universal access | Yes (on resolution) | No |
| `admin` | Management operations | No | No |

### Bootstrap Process
The init script (`scripts/init_auth.py`) performs:
1. Creates `groups.json` with `public` and `admin` groups (if not exists)
2. Creates `tokens.json` with initial admin token (if not exists)
3. Outputs admin JWT to stdout for initial system access

```bash
# First-time setup
python scripts/init_auth.py --data-dir /path/to/data/auth
# Output: Admin token: eyJhbG...
```

---

## Storage Format (Final)

### groups.json
```json
{
  "550e8400-e29b-41d4-a716-446655440000": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "public",
    "description": "Universal access group - automatically included for all tokens",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00",
    "defunct_at": null,
    "is_reserved": true
  },
  "550e8400-e29b-41d4-a716-446655440001": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "admin",
    "description": "Administrative access - required for group and token management",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00",
    "defunct_at": null,
    "is_reserved": true
  },
  "uuid-3": {
    "id": "uuid-3",
    "name": "users",
    "description": "Regular users",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00",
    "defunct_at": null,
    "is_reserved": false
  }
}
```

### tokens.json
```json
{
  "uuid-1": {
    "id": "uuid-1", 
    "groups": ["admin"],
    "status": "active",
    "created_at": "2024-01-01T00:00:00",
    "expires_at": null,
    "revoked_at": null,
    "fingerprint": null
  }
}
```

---

## Authorization Matrix

| Operation | Required Group |
|-----------|---------------|
| `create_group()` | admin |
| `make_defunct()` | admin |
| `create_token()` | admin |
| `revoke_token()` | admin |
| `list_groups()` | (any valid token) |
| `list_tokens()` | admin |
| `verify_token()` | (no token required) |
| `resolve_token_groups()` | (any valid token) |
