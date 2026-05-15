# Auth Hardening Plan

Goal: harden lib/gofr-common/src/gofr_common/auth to reduce security risk and ensure
all error messages include root cause and a clear remediation path.

Scope reviewed:
- src/gofr_common/auth/{service,token_service,groups,middleware,provider,exceptions,config,identity}
- src/gofr_common/auth/backends/{vault,vault_client,vault_config,factory}


## Priority Order (force-ranked)

1) Normalize error handling and user-facing remediation messages
2) Vault reliability, error classification, and backoff behavior
3) Token verification strictness and claim validation consistency
4) Secret management defaults and unsafe auto-secret usage
5) Audit logging coverage and event structure
6) Admin-only operations hardening (VaultAdmin + policies)
7) Legacy CLI deprecation and exposure controls


## Step-by-step plan

### 1) Normalize error handling and remediation messages (highest priority)

Problem:
- Errors mix ValueError, custom AuthError, and backend exceptions.
- Some messages are low-context (e.g., "Invalid token") or miss remediation.
- Middleware and provider convert exceptions to HTTP errors inconsistently.

Plan:
1.1 Introduce a single error normalizer in auth (e.g., auth/errors.py) that maps:
    - AuthError subclasses -> status + user message
    - Storage errors (StorageUnavailableError, Vault*Error) -> 503 with remediation
    - Unexpected exceptions -> 500 with correlation id
1.2 Standardize all public-facing errors to include:
    - root cause (safe, non-secret)
    - remediation hint (e.g., "check GOFR_VAULT_URL" or "re-authenticate")
    - service/tool context (AuthService, VaultClient, TokenStore)
1.3 Update middleware/provider to use the normalizer instead of raw str(e).
1.4 Add tests asserting error format includes cause + remediation.

Concrete targets:
- src/gofr_common/auth/middleware.py
- src/gofr_common/auth/provider.py
- src/gofr_common/auth/service.py
- src/gofr_common/auth/token_service.py
- src/gofr_common/auth/backends/vault_client.py


### 2) Vault reliability, error classification, and backoff behavior

Problem:
- VaultClient broadly catches Exception and rethrows connection errors without
  differentiating transient vs auth/permission vs not-found.
- VaultTokenStore/VaultGroupStore do not include remediation steps.
- No retry/backoff for transient failures.

Plan:
2.1 Extend VaultClient exception mapping to include:
    - auth failures (401/403) -> VaultAuthenticationError with remediation
    - permission denied -> VaultPermissionError with policy hint
    - connection/timeout -> VaultConnectionError with retry guidance
    - invalid path -> VaultNotFoundError for explicit path context
2.2 Add configurable retry/backoff to VaultClient methods (read/write/list/delete).
2.3 Propagate Vault errors with structured fields (operation, path, mount_point).
2.4 Ensure StorageUnavailableError includes root cause and next steps.
2.5 Add integration tests for failure modes.

Concrete targets:
- src/gofr_common/auth/backends/vault_client.py
- src/gofr_common/auth/backends/vault.py
- src/gofr_common/auth/backends/factory.py


### 3) Token verification strictness and claim validation consistency

Problem:
- AuthService/TokenService allow verify_aud=False and do not always validate
  iat/nbf claims consistently across services.
- Fingerprint validation is optional and not surfaced in error messages.

Plan:
3.1 Introduce a strict verification mode default for server-side APIs:
    - verify_aud=True when audience configured
    - require_store=True for API auth
    - validate_groups=True for protected endpoints
3.2 Make verify settings explicit in middleware/provider, not defaulted in service.
3.3 Expand error messages to include remediation (e.g., "token audience mismatch,
    ensure client uses {audience}").
3.4 Add tests for missing aud, mismatched aud, and expired tokens.

Concrete targets:
- src/gofr_common/auth/service.py
- src/gofr_common/auth/token_service.py
- src/gofr_common/auth/middleware.py
- src/gofr_common/auth/provider.py


### 4) Secret management defaults and unsafe auto-secret usage

Problem:
- TokenService auto-generates a secret when missing, which can silently
  invalidate tokens on restart and weaken security if deployed by mistake.

Plan:
4.1 Add a hard fail in production if secret missing unless explicitly allowed.
4.2 Log an error that includes remediation and a clear opt-out for dev.
4.3 Gate auto-secret behind explicit flag or env var (e.g., GOFR_ALLOW_DEV_SECRET).
4.4 Add tests for prod env enforcing missing-secret failure.

Concrete targets:
- src/gofr_common/auth/token_service.py
- src/gofr_common/auth/config.py


### 5) Audit logging coverage and event structure

Problem:
- Audit logs are present but not structured consistently.
- Some failure paths do not log enough context to debug.

Plan:
6.1 Standardize audit fields: event, actor, client_id, token_id, groups,
    endpoint, outcome, remediation.
6.2 Ensure every auth failure path logs via SecurityAuditorProtocol.
6.3 Provide default auditor that logs structured entries for non-FastAPI usage.

Concrete targets:
- src/gofr_common/auth/middleware.py
- src/gofr_common/auth/provider.py
- src/gofr_common/auth/service.py


### 6) Admin-only operations hardening (VaultAdmin + policies)

Problem:
- VaultAdmin uses broad policies and does not validate mount points or paths.
- Admin operations could be invoked with weak parameters.

Plan:
7.1 Validate policy names and paths before applying.
7.2 Add explicit checks for allowed mount points and path prefixes.
7.3 Emit remediation steps for policy failures (e.g., "confirm policy exists").
7.4 Add tests for policy and AppRole provisioning errors.

Concrete targets:
- src/gofr_common/auth/admin.py
- src/gofr_common/auth/policies.py


### 7) Legacy CLI deprecation and exposure controls

Problem:
- token_manager.py is legacy and inconsistent with current APIs.
- It can create security drift if used by mistake.

Plan:
8.1 Deprecate token_manager.py with a hard warning and runtime exit.
8.2 Update scripts to point to auth_manager.py only.
8.3 Document the migration path in docs/auth.

Concrete targets:
- src/gofr_common/auth/token_manager.py
- scripts/token_manager.sh (service repos)


## Deliverables

- New error normalizer module and integration across middleware/provider/service.
- Updated Vault client with granular error mapping + retries.
- Strict verification mode with explicit options in middleware/provider.
- File-store locking and atomic write safety.
- Updated docs describing error contract and remediation guidance.
- Tests covering new error semantics and failure modes.
