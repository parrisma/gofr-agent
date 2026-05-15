# Vault Integration Spec for GOFR Auth

> Note: Memory and file backends have been removed. Vault is the only supported
> storage backend. Historical references to memory/file stores below are kept
> for context only.

## Overview

Replace file-based token/group storage with HashiCorp Vault KV v2 backend while maintaining existing API and test compatibility.

## 🎉 IMPLEMENTATION COMPLETE

All 11 phases successfully implemented:

| Phase | Description | Status | Tests |
|-------|-------------|--------|-------|
| 1 | Storage Protocol Abstraction | ✅ | 370 |
| 2 | File Backend Extraction | ✅ | 390 |
| 3 | Vault Configuration | ✅ | 415 |
| 4 | Vault Client Wrapper | ✅ | 441 |
| 5 | Vault Infrastructure | ✅ | 441 |
| 6 | Vault Token Store | ✅ | 468 |
| 7 | Vault Group Store | ✅ | 500 |
| 8 | Backend Factory | ✅ | 523 |
| 9 | Integration | ✅ | 523 |
| 10 | Integration Tests | ✅ | 552 |
| 11 | Documentation & Tools | ✅ | 552 |

**Final Test Count: 552 tests (523 unit + 29 integration)**

### Key Deliverables
- **Storage Protocols:** `TokenStore`, `GroupStore` (structural typing)
- **Backends:** Memory, File, Vault (all implement protocols)
- **Factory:** `create_stores_from_env()` for environment-based configuration
- **Vault Infrastructure:** Docker setup at `docker/infra/vault/`
- **Documentation:** `docs/AUTH_MIGRATION_GUIDE.md`
- **Bootstrap Script:** `scripts/init_auth.py` supports all backends

---

## Phase 1: Storage Protocol Abstraction

**Goal:** Extract storage interface from current implementation without changing behavior.

**Status:** ✅ COMPLETE

### Step 1.1: Create TokenStore Protocol
- [x] Create `src/gofr_common/auth/backends/__init__.py`
- [x] Create `src/gofr_common/auth/backends/base.py`
- [x] Define `TokenStore` Protocol with methods:
  - `get(token_id: str) -> Optional[TokenRecord]`
  - `put(token_id: str, record: TokenRecord) -> None`
  - `delete(token_id: str) -> bool` (for soft-delete update)
  - `list_all() -> Dict[str, TokenRecord]`
  - `exists(token_id: str) -> bool`
- [x] Add tests for protocol definition
- [x] Run tests: `./scripts/run_tests.sh -k "test_token_store_protocol"`

### Step 1.2: Create GroupStore Protocol
- [x] Define `GroupStore` Protocol with methods:
  - `get(group_id: str) -> Optional[Group]`
  - `get_by_name(name: str) -> Optional[Group]`
  - `put(group_id: str, group: Group) -> None`
  - `list_all() -> Dict[str, Group]`
  - `exists(group_id: str) -> bool`
- [x] Add tests for protocol definition
- [x] Run tests: `./scripts/run_tests.sh -k "test_group_store_protocol"`

### Step 1.3: Create MemoryTokenStore
- [x] Create `src/gofr_common/auth/backends/memory.py`
- [x] Implement `MemoryTokenStore(TokenStore)`
- [x] Simple dict-based storage
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_memory_token_store"`

### Step 1.4: Create MemoryGroupStore
- [x] Implement `MemoryGroupStore(GroupStore)`
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_memory_group_store"` (370 tests pass)

---

## Phase 2: File Backend Extraction

**Goal:** Extract existing file logic into FileTokenStore/FileGroupStore classes.

**Status:** ✅ COMPLETE

### Step 2.1: Create FileTokenStore
- [x] Create `src/gofr_common/auth/backends/file.py`
- [x] Extract `_load_token_store` and `_save_token_store` from `service.py`
- [x] Implement `FileTokenStore(TokenStore)`
- [x] Add `path` parameter to constructor (accepts str or Path)
- [x] Add tests (should mirror existing file behavior)
- [x] Run tests: `./scripts/run_tests.sh -k "test_file_token_store"`

### Step 2.2: Create FileGroupStore
- [x] Extract file logic from `GroupRegistry`
- [x] Implement `FileGroupStore(GroupStore)`
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_file_group_store"`

### Step 2.3: Refactor AuthService to Use TokenStore
- [x] Add `token_store: Optional[TokenStore]` parameter to `__init__`
- [x] If `token_store` provided, use it directly
- [x] If `token_store_path=":memory:"`, create `MemoryTokenStore`
- [x] If `token_store_path` is path, create `FileTokenStore`
- [x] Remove internal `_load_token_store`/`_save_token_store` methods
- [x] All existing tests pass unchanged (390 tests)
- [x] Run tests: `./scripts/run_tests.sh -k "test_auth"`

### Step 2.4: Refactor GroupRegistry to Use GroupStore
- [x] Add `store: Optional[GroupStore]` parameter
- [x] Same pattern as AuthService
- [x] All existing tests pass unchanged (390 tests)
- [x] Run tests: `./scripts/run_tests.sh -k "test_group"`

---

## Phase 3: Vault Configuration

**Goal:** Define Vault connection configuration.

**Status:** ✅ COMPLETE

### Step 3.1: Create VaultConfig
- [x] Create `src/gofr_common/auth/backends/vault_config.py`
- [x] Define `VaultConfig` dataclass with fields:
  - `url: str` - Vault server URL
  - `token: Optional[str]` - Token authentication
  - `role_id: Optional[str]` - AppRole role ID
  - `secret_id: Optional[str]` - AppRole secret ID
  - `mount_point: str = "secret"` - KV mount point
  - `path_prefix: str = "gofr/auth"` - Path prefix
  - `timeout: int = 30` - Connection timeout
  - `namespace: Optional[str]` - Vault Enterprise namespace
  - `verify_ssl: bool = True` - SSL verification
- [x] Add `from_env(prefix: str) -> VaultConfig` class method
- [x] Add `validate() -> None` method (raises if invalid)
- [x] Add `auth_method`, `tokens_path`, `groups_path` properties
- [x] Add tests for config creation and validation (25 tests)
- [x] Run tests: `./scripts/run_tests.sh -k "VaultConfig"` (415 total tests pass)

### Step 3.2: Environment Variables
- [x] Document environment variables:
  - `{PREFIX}_VAULT_URL` - Vault server URL (required)
  - `{PREFIX}_VAULT_TOKEN` - Token for token auth
  - `{PREFIX}_VAULT_ROLE_ID` - AppRole role ID
  - `{PREFIX}_VAULT_SECRET_ID` - AppRole secret ID
  - `{PREFIX}_VAULT_MOUNT` - KV mount point (default: "secret")
  - `{PREFIX}_VAULT_PATH_PREFIX` - Path prefix (default: "gofr/auth")
  - `{PREFIX}_VAULT_TIMEOUT` - Timeout in seconds (default: 30)
  - `{PREFIX}_VAULT_NAMESPACE` - Vault Enterprise namespace
  - `{PREFIX}_VAULT_VERIFY_SSL` - SSL verification (default: "true")
- [x] Add tests for env var loading
- [x] Run tests: `./scripts/run_tests.sh -k "VaultConfig"` (415 total tests pass)

---

## Phase 4: Vault Client Wrapper

**Goal:** Create thin wrapper around hvac client with error handling.

**Status:** ✅ COMPLETE

### Step 4.1: Add hvac Dependency
- [x] Add `hvac>=2.1.0` to `pyproject.toml` optional dependencies
- [x] Create `[vault]` extras group
- [x] Run: `uv pip install -e ".[vault]"` (installed hvac 2.4.0)

### Step 4.2: Create VaultClient Wrapper
- [x] Create `src/gofr_common/auth/backends/vault_client.py`
- [x] Implement `VaultClient` class:
  - `__init__(config: VaultConfig)` - creates hvac client
  - `_authenticate()` - handle token or AppRole auth
  - `read_secret(path: str) -> Optional[Dict]`
  - `write_secret(path: str, data: Dict) -> None`
  - `delete_secret(path: str) -> bool`
  - `list_secrets(path: str) -> List[str]`
  - `secret_exists(path: str) -> bool`
  - `is_authenticated() -> bool`
- [x] Add custom exceptions:
  - `VaultError` - base exception
  - `VaultConnectionError`
  - `VaultAuthenticationError`
  - `VaultNotFoundError`
  - `VaultPermissionError`
- [x] Add tests with mocked hvac client (26 tests)
- [x] Run tests: `./scripts/run_tests.sh -k "VaultClient"` (441 total tests pass)

### Step 4.3: Connection Health Check
- [x] Add `health_check() -> bool` method
- [x] Add `reconnect() -> None` method
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh -k "VaultClient"` (441 total tests pass)

---

## Phase 5: Vault Infrastructure

**Goal:** Add Vault to shared infrastructure (like chroma/neo4j).

**Status:** ✅ COMPLETE

### Step 5.1: Create Vault Docker Infrastructure
- [x] Create `docker/infra/vault/` directory
- [x] Create `Dockerfile` - based on official hashicorp/vault image
- [x] Create `vault-config.hcl` - file storage backend config for prod
- [x] Create `build.sh` - build script
- [x] Create `run.sh` - run with `--test` (ephemeral) or `--prod` (persistent) modes
- [x] Create `stop.sh` - stop script

### Step 5.2: Add to Docker Compose
- [x] Add vault service to `docker-compose.infra.yml`
- [x] Add `gofr-vault-data` and `gofr-vault-logs` volumes (for prod)
- [x] Dev mode auto-unseals with root token `gofr-dev-root-token`
- [x] Configure health check
- [x] Port 8201 (default, configurable via GOFR_VAULT_PORT)

### Step 5.3: Configure pytest Integration Marker
- [x] Add `vault_integration` marker to `pyproject.toml`
- [x] Integration tests skip when vault unavailable
- [x] Unit tests use mocked VaultClient (Phase 4)

### Step 5.4: Verify Infrastructure
- [x] Run: `./docker/infra/vault/build.sh`
- [x] Run: `./docker/infra/vault/run.sh --test`
- [x] Verify: `curl http://gofr-vault:8200/v1/sys/health`
- [x] VaultClient test: connect, write, read, delete ✅

### Usage Summary
```bash
# Test mode (ephemeral, for development/testing)
./docker/infra/vault/run.sh --test
# - In-memory storage (lost on restart)
# - Auto-unsealed, auto-initialized
# - Root token: gofr-dev-root-token

# Production mode (persistent volumes)
./docker/infra/vault/run.sh --prod
# - File storage in gofr-vault-data volume
# - Logs in gofr-vault-logs volume
# - Requires manual init/unseal

# From other containers on gofr-net:
export VAULT_ADDR=http://gofr-vault:8200
export VAULT_TOKEN=gofr-dev-root-token
```

---

## Phase 6: Vault Token Store

**Goal:** Implement TokenStore backed by Vault.

**Status:** ✅ COMPLETE

### Step 6.1: Implement VaultTokenStore
- [x] Create `src/gofr_common/auth/backends/vault.py`
- [x] Implement `VaultTokenStore(TokenStore)`:
  - Constructor takes `VaultClient` and `path_prefix`
  - `get()` reads from `{prefix}/tokens/{token_id}`
  - `put()` writes to `{prefix}/tokens/{token_id}`
  - `delete()` soft deletes in Vault (marks versions as deleted)
  - `list_all()` lists and fetches all tokens
  - `exists()` checks path exists
  - `reload()` no-op (Vault doesn't cache)
  - `clear()` deletes all tokens
  - `__len__()` returns token count
- [x] Add tests with mocked VaultClient
- [x] Run tests: `./scripts/run_tests.sh -k "VaultTokenStore"` - 27 tests pass

### Step 6.2: Error Handling
- [x] Handle `VaultConnectionError` - raises `StorageUnavailableError`
- [x] Handle missing secrets - returns None
- [x] All operations wrap VaultClient errors appropriately
- [x] Add tests for error scenarios (connection errors raise StorageUnavailableError)
- [x] Run tests: Full suite 468 tests pass

### Implementation Summary

**Created Files:**
- `src/gofr_common/auth/backends/vault.py` - VaultTokenStore class (~220 lines)

**Updated Files:**
- `src/gofr_common/auth/backends/__init__.py` - Added VaultTokenStore export
- `tests/test_backends.py` - Added 27 VaultTokenStore tests

**Usage:**
```python
from gofr_common.auth.backends import VaultConfig, VaultClient, VaultTokenStore

config = VaultConfig(url="http://gofr-vault:8200", token="gofr-dev-root-token")
client = VaultClient(config)
store = VaultTokenStore(client, path_prefix="gofr/auth")

# Store a token
store.put(str(token.id), token)

# Get a token
token = store.get("uuid-string")

# List all tokens
all_tokens = store.list_all()
```

---

## Phase 7: Vault Group Store

**Goal:** Implement GroupStore backed by Vault.

**Status:** ✅ COMPLETE

### Step 7.1: Implement VaultGroupStore
- [x] Implement `VaultGroupStore(GroupStore)`:
  - `get()` reads from `{prefix}/groups/{group_id}`
  - `get_by_name()` uses name index for efficient lookup
  - `put()` writes to `{prefix}/groups/{group_id}` and updates index
  - `delete()` removes group and updates index
  - `list_all()` lists and fetches all groups (skips _index)
  - `exists()` checks path exists
  - `reload()` no-op (Vault doesn't cache)
  - `clear()` deletes all groups and index
  - `__len__()` returns group count (excludes _index)
- [x] Add tests with mocked VaultClient
- [x] Run tests: `./scripts/run_tests.sh -k "VaultGroupStore"` - 32 tests pass

### Step 7.2: Name Index
- [x] Store name->id mapping at `{prefix}/groups/_index/names`
- [x] Update index on `put()` (handles renames)
- [x] Use index for `get_by_name()` lookups
- [x] Remove from index on `delete()`
- [x] Add tests for index operations
- [x] Run tests: Full suite 500 tests pass

### Implementation Summary

**Updated Files:**
- `src/gofr_common/auth/backends/vault.py` - Added VaultGroupStore class (~230 lines)
- `src/gofr_common/auth/backends/__init__.py` - Added VaultGroupStore export
- `tests/test_backends.py` - Added 32 VaultGroupStore tests

**Usage:**
```python
from gofr_common.auth.backends import VaultConfig, VaultClient, VaultGroupStore

config = VaultConfig(url="http://gofr-vault:8200", token="gofr-dev-root-token")
client = VaultClient(config)
store = VaultGroupStore(client, path_prefix="gofr/auth")

# Store a group
store.put(str(group.id), group)

# Get by ID
group = store.get("uuid-string")

# Get by name (uses index)
group = store.get_by_name("admin")

# List all groups
all_groups = store.list_all()
```

---

## Phase 8: Backend Factory

**Goal:** Factory function to create stores from configuration.

**Status:** ✅ COMPLETE

### Step 8.1: Create Store Factory
- [x] Create `src/gofr_common/auth/backends/factory.py`
- [x] Implement `create_token_store(backend: str, **kwargs) -> TokenStore`
- [x] Implement `create_group_store(backend: str, **kwargs) -> GroupStore`
- [x] Support backends: `"memory"`, `"file"`, `"vault"`
- [x] Add tests
- [x] Run tests: `./scripts/run_tests.sh -k "test_store_factory"` - 23 tests pass

### Step 8.2: Environment-Based Factory
- [x] Add `create_stores_from_env() -> Tuple[TokenStore, GroupStore]`
- [x] Read `GOFR_AUTH_BACKEND` to determine backend type
- [x] Add tests
- [x] Run tests: Full suite 523 tests pass

---

## Phase 9: Integration

**Goal:** Wire everything together, all existing tests pass.

**Status:** ✅ COMPLETE

### Step 9.1: Simplify AuthService Constructor
- [x] Require `token_store: TokenStore` parameter (no more path params)
- [x] Require `group_registry: GroupRegistry` parameter
- [x] Remove backward compatibility (per user request)
- [x] Update tests with `create_memory_auth()` and `create_file_auth()` helpers
- [x] All tests pass
- [x] Run tests: `./scripts/run_tests.sh` - 523 tests pass

### Step 9.2: Simplify GroupRegistry Constructor
- [x] Require `store: GroupStore` parameter (no more store_path)
- [x] Update tests to use `MemoryGroupStore()` / `FileGroupStore()` directly
- [x] All tests pass
- [x] Run tests: `./scripts/run_tests.sh` - 523 tests pass

### Step 9.3: Update Exports
- [x] Export all backend classes from `__init__.py`:
  - `TokenStore`, `GroupStore` (protocols)
  - `MemoryTokenStore`, `MemoryGroupStore`
  - `FileTokenStore`, `FileGroupStore`
  - `VaultConfig`, `VaultClient`, `VaultTokenStore`, `VaultGroupStore`
  - `create_token_store`, `create_group_store`, `create_stores_from_env`
  - `VaultConnectionError`, `VaultAuthenticationError`, etc.
- [x] Run tests: `./scripts/run_tests.sh` - 523 tests pass

---

## Phase 10: Integration Tests

**Goal:** Test against real Vault container.

**Status:** ✅ COMPLETE

### Step 10.1: Integration Test Suite
- [x] Create `tests/test_vault_integration.py`
- [x] Mark tests with `@pytest.mark.vault_integration`
- [x] Skip if Vault not available (`vault_available()` helper)
- [x] Test full CRUD cycle with real Vault:
  - VaultClient: health, auth, write/read/delete, list, exists
  - VaultTokenStore: put/get, exists, list_all, delete, clear, len
  - VaultGroupStore: put/get, get_by_name, rename index, delete
  - GroupRegistry: reserved groups, create, defunct, list
  - AuthService: create/verify token, revoke, list, resolve groups
- [x] Run: `./scripts/run_tests.sh -m vault_integration` - 29 tests pass

### Step 10.2: Multi-Client Test
- [x] Test two AuthService instances sharing same Vault
- [x] Create token on instance A, verify on instance B ✅
- [x] Revoke on instance A, verify rejected on instance B ✅
- [x] Create group on A, visible on B ✅
- [x] Run: `./scripts/run_tests.sh -m vault_integration` - 29 tests pass

### Implementation Notes
- Fixed `VaultClient.delete_secret()` - added `hard=True` option for permanent deletion
- `clear()` methods now use hard delete for proper cleanup
- Total: 552 tests pass (523 unit + 29 integration)

---

## Phase 11: Documentation & Tools

**Goal:** Documentation and bootstrap script updates.

**Status:** ✅ COMPLETE

### Step 11.1: Migration Documentation
- [x] Create `docs/AUTH_MIGRATION_GUIDE.md`
- [x] Document all backends (Memory, File, Vault)
- [x] Quick start examples for each backend
- [x] Factory pattern usage with environment variables
- [x] Migration from old API to new API
- [x] Architecture diagram and protocol definitions
- [x] Vault configuration (dev mode, production, path organization)
- [x] Testing patterns (unit with memory, integration with Vault)
- [x] Common patterns (singleton, DI, multi-service)
- [x] Troubleshooting guide
- [x] API reference

### Step 11.2: Bootstrap Script Update
- [x] Update `scripts/init_auth.py` to support `--backend vault`
- [x] Add Vault options: `--vault-url`, `--vault-token`, `--vault-role-id`, `--vault-secret-id`, `--vault-path-prefix`
- [x] Support environment variables: `GOFR_AUTH_BACKEND`, `GOFR_VAULT_*`
- [x] Auto-detect existing initialization for all backends
- [x] Create reserved groups in Vault ✅
- [x] Create admin token in Vault ✅
- [x] Manual test with dev Vault ✅

---

## File Structure (Final)

```
src/gofr_common/auth/
├── __init__.py              # Updated exports
├── service.py               # Uses TokenStore protocol
├── groups.py                # Uses GroupStore protocol  
├── tokens.py                # Unchanged
├── middleware.py            # Unchanged
├── readme.md                # Updated with Vault docs
├── spec.md                  # Original refactoring spec
├── vault_spec.md            # This spec
└── backends/
    ├── __init__.py          # Factory exports
    ├── base.py              # Protocol definitions
    ├── memory.py            # MemoryTokenStore, MemoryGroupStore
    ├── file.py              # FileTokenStore, FileGroupStore
    ├── vault_config.py      # VaultConfig
    ├── vault_client.py      # VaultClient wrapper
    ├── vault.py             # VaultTokenStore, VaultGroupStore
    └── factory.py           # create_token_store, create_group_store

tests/
├── test_auth.py             # Existing tests (must pass)
├── test_groups.py           # Existing tests (must pass)
├── test_tokens.py           # Existing tests (must pass)
├── test_backends/
│   ├── test_protocols.py
│   ├── test_memory_store.py
│   ├── test_file_store.py
│   ├── test_vault_config.py
│   ├── test_vault_client.py
│   ├── test_vault_store.py
│   └── test_factory.py
└── test_vault_integration.py  # Real Vault tests
```

---

## Test Count Targets

| Phase | New Tests | Cumulative |
|-------|-----------|------------|
| Current | - | 338 |
| Phase 1 | ~20 | 358 |
| Phase 2 | ~15 | 373 |
| Phase 3 | ~10 | 383 |
| Phase 4 | ~15 | 398 |
| Phase 5 | ~12 | 410 |
| Phase 6 | ~12 | 422 |
| Phase 7 | ~8 | 430 |
| Phase 8 | ~5 | 435 |
| Phase 9 | ~10 | 445 |
| Phase 10 | ~5 | 450 |

---

## Environment Variables Reference

### File Backend (Default)
```bash
GOFR_AUTH_BACKEND=file
GOFR_TOKEN_STORE=/data/auth/tokens.json
# group store derived from token store path
```

### Memory Backend (Testing)
```bash
GOFR_AUTH_BACKEND=memory
# No additional config needed
```

### Vault Backend (Production)
```bash
GOFR_AUTH_BACKEND=vault
GOFR_VAULT_URL=https://vault.gofr.local:8200
GOFR_VAULT_ROLE_ID=xxx
GOFR_VAULT_SECRET_ID=xxx
GOFR_VAULT_MOUNT=secret
GOFR_VAULT_PATH_PREFIX=gofr/auth
```

---

## Vault Setup Reference

### Required Vault Policy

```hcl
# gofr-auth-policy.hcl

# Read/write tokens
path "secret/data/gofr/auth/tokens/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Read/write groups
path "secret/data/gofr/auth/groups/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# List paths
path "secret/metadata/gofr/auth/*" {
  capabilities = ["list"]
}
```

### AppRole Setup Commands

```bash
# Enable AppRole auth
vault auth enable approle

# Create policy
vault policy write gofr-auth gofr-auth-policy.hcl

# Create role
vault write auth/approle/role/gofr-auth \
    token_policies="gofr-auth" \
    token_ttl=1h \
    token_max_ttl=4h

# Get role_id
vault read auth/approle/role/gofr-auth/role-id

# Generate secret_id
vault write -f auth/approle/role/gofr-auth/secret-id
```

---

## Ready to Start?

Say **"go 1"** to begin Phase 1 (Storage Protocol Abstraction).
