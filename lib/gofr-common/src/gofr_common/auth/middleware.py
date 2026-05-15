"""Authentication middleware for FastAPI.

Provides utilities for validating JWT tokens in web requests,
including multi-group authorization helpers.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Protocol

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .service import AuthService
from .tokens import TokenInfo

if TYPE_CHECKING:
    from .jwt_secret_provider import JwtSecretProvider


class SecurityAuditorProtocol(Protocol):
    """Protocol for security auditor integration.

    Implement this protocol to receive security events from the middleware.
    """

    def log_auth_failure(
        self,
        client_id: str,
        reason: str,
        endpoint: Optional[str] = None,
        **details: Any,
    ) -> None:
        """Log authentication failure."""
        ...


# Global auth service instance
_auth_service: Optional[AuthService] = None

# Global security auditor instance (optional)
_security_auditor: Optional[SecurityAuditorProtocol] = None

# FastAPI security schemes
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def _generate_fingerprint(request: Request) -> str:
    """Generate a device fingerprint from request context.

    Combines User-Agent and client IP to create a stable fingerprint.
    Used for token binding to prevent token theft.

    Args:
        request: FastAPI request object

    Returns:
        SHA256 hash of user-agent + IP
    """
    user_agent = request.headers.get("user-agent", "unknown")
    client_ip = request.client.host if request.client else "unknown"
    fingerprint_data = f"{user_agent}:{client_ip}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()


def init_auth_service(
    auth_service: Optional[AuthService] = None,
    secret_provider: Optional[JwtSecretProvider] = None,
    env_prefix: str = "GOFR",
) -> AuthService:
    """Initialize the global auth service.

    Args:
        auth_service: Existing AuthService instance (preferred).
            If not provided, creates one using create_stores_from_env().
        secret_provider: JwtSecretProvider instance used to load the JWT signing secret.
            If not provided, one is created from environment configuration.
        env_prefix: Environment variable prefix for Vault/auth settings (default: GOFR).

    Returns:
        AuthService instance

    Example:
        # Option 1: Pass existing service (recommended)
        auth = AuthService(token_store=..., group_registry=..., secret_provider=...)
        init_auth_service(auth_service=auth)

        # Option 2: Create from environment
        init_auth_service(env_prefix="GOFR")
    """
    global _auth_service

    if auth_service is not None:
        _auth_service = auth_service
    else:
        from .backends import create_stores_from_env, create_vault_client_from_env
        from .groups import GroupRegistry
        from .jwt_secret_provider import JwtSecretProvider

        if secret_provider is None:
            vault_client = create_vault_client_from_env(env_prefix)
            secret_provider = JwtSecretProvider(vault_client=vault_client)
            token_store, group_store = create_stores_from_env(env_prefix, vault_client=vault_client)
        else:
            token_store, group_store = create_stores_from_env(env_prefix)
        groups = GroupRegistry(store=group_store)
        _auth_service = AuthService(
            token_store=token_store,
            group_registry=groups,
            secret_provider=secret_provider,
            env_prefix=env_prefix,
        )

    return _auth_service


def get_auth_service() -> AuthService:
    """Get the global auth service instance.

    Returns:
        AuthService instance

    Raises:
        RuntimeError: If auth service not initialized
    """
    if _auth_service is None:
        raise RuntimeError("AuthService not initialized. Call init_auth_service() first.")
    return _auth_service


def set_security_auditor(auditor: Optional[SecurityAuditorProtocol]) -> None:
    """Set the global security auditor instance.

    Args:
        auditor: SecurityAuditor instance or None to disable auditing
    """
    global _security_auditor
    _security_auditor = auditor


def get_security_auditor() -> Optional[SecurityAuditorProtocol]:
    """Get the global security auditor instance.

    Returns:
        SecurityAuditor instance or None if not configured
    """
    return _security_auditor


def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> TokenInfo:
    """Verify JWT token from request with enhanced security checks.

    Generates device fingerprint and validates token binding if configured.

    Args:
        request: FastAPI request object (for fingerprinting)
        credentials: HTTP authorization credentials

    Returns:
        TokenInfo with group and expiry information

    Raises:
        HTTPException: If token is invalid or missing
    """
    try:
        auth_service = get_auth_service()
        # Generate fingerprint for token binding validation
        fingerprint = _generate_fingerprint(request)
        token_info = auth_service.verify_token(
            credentials.credentials,
            fingerprint=fingerprint,
        )
        return token_info
    except ValueError as e:
        # Log authentication failure
        auditor = get_security_auditor()
        if auditor:
            client_ip = request.client.host if request.client else "unknown"
            auditor.log_auth_failure(
                client_id=client_ip,
                reason=str(e),
                endpoint=str(request.url.path),
            )
        raise HTTPException(status_code=401, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


def optional_verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(optional_security),
) -> Optional[TokenInfo]:
    """Optionally verify JWT token from request.

    Doesn't require authentication - returns None if no token provided.

    Args:
        request: FastAPI request object
        credentials: HTTP authorization credentials (optional)

    Returns:
        TokenInfo if token provided and valid, None if no token provided

    Raises:
        HTTPException: If token is provided but invalid
    """
    if credentials is None:
        return None

    try:
        auth_service = get_auth_service()
        fingerprint = _generate_fingerprint(request)
        token_info = auth_service.verify_token(
            credentials.credentials,
            fingerprint=fingerprint,
        )
        return token_info
    except ValueError as e:
        auditor = get_security_auditor()
        if auditor:
            client_ip = request.client.host if request.client else "unknown"
            auditor.log_auth_failure(
                client_id=client_ip,
                reason=str(e),
                endpoint=str(request.url.path),
            )
        raise HTTPException(status_code=401, detail=str(e))
    except RuntimeError:
        # Auth service not initialized - allow anonymous access
        return None


def verify_token_simple(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> TokenInfo:
    """Verify JWT token from request (simple version without fingerprinting).

    Use this when you don't need device fingerprinting or don't have
    access to the Request object.

    Args:
        credentials: HTTP authorization credentials

    Returns:
        TokenInfo with groups and expiry information

    Raises:
        HTTPException: If token is invalid or missing
    """
    try:
        auth_service = get_auth_service()
        token_info = auth_service.verify_token(credentials.credentials)
        return token_info
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Authorization Helpers
# =============================================================================


def require_group(group_name: str) -> Callable[..., TokenInfo]:
    """Create a dependency that requires a specific group.

    Args:
        group_name: Name of the required group

    Returns:
        FastAPI dependency function

    Example:
        @app.get("/admin")
        def admin_endpoint(token: TokenInfo = Depends(require_group("admin"))):
            return {"message": "Admin access granted"}
    """
    def _require_group(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> TokenInfo:
        token_info = verify_token(request, credentials)
        if not token_info.has_group(group_name):
            auditor = get_security_auditor()
            if auditor:
                client_ip = request.client.host if request.client else "unknown"
                auditor.log_auth_failure(
                    client_id=client_ip,
                    reason=f"Missing required group: {group_name}",
                    endpoint=str(request.url.path),
                    groups=token_info.groups,
                )
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required group: {group_name}",
            )
        return token_info
    return _require_group


def require_any_group(group_names: List[str]) -> Callable[..., TokenInfo]:
    """Create a dependency that requires any of the specified groups.

    Args:
        group_names: List of group names (any one is sufficient)

    Returns:
        FastAPI dependency function

    Example:
        @app.get("/data")
        def data_endpoint(token: TokenInfo = Depends(require_any_group(["admin", "users"]))):
            return {"message": "Access granted"}
    """
    def _require_any_group(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> TokenInfo:
        token_info = verify_token(request, credentials)
        if not token_info.has_any_group(group_names):
            auditor = get_security_auditor()
            if auditor:
                client_ip = request.client.host if request.client else "unknown"
                auditor.log_auth_failure(
                    client_id=client_ip,
                    reason=f"Missing required groups (any of): {group_names}",
                    endpoint=str(request.url.path),
                    groups=token_info.groups,
                )
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required groups (any of): {group_names}",
            )
        return token_info
    return _require_any_group


def require_all_groups(group_names: List[str]) -> Callable[..., TokenInfo]:
    """Create a dependency that requires all of the specified groups.

    Args:
        group_names: List of group names (all are required)

    Returns:
        FastAPI dependency function

    Example:
        @app.get("/restricted")
        def restricted_endpoint(token: TokenInfo = Depends(require_all_groups(["admin", "auditor"]))):
            return {"message": "Full access granted"}
    """
    def _require_all_groups(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> TokenInfo:
        token_info = verify_token(request, credentials)
        if not token_info.has_all_groups(group_names):
            missing = set(group_names) - set(token_info.groups)
            auditor = get_security_auditor()
            if auditor:
                client_ip = request.client.host if request.client else "unknown"
                auditor.log_auth_failure(
                    client_id=client_ip,
                    reason=f"Missing required groups: {list(missing)}",
                    endpoint=str(request.url.path),
                    groups=token_info.groups,
                )
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Missing groups: {list(missing)}",
            )
        return token_info
    return _require_all_groups


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> TokenInfo:
    """Dependency that requires admin group membership.

    Convenience function equivalent to require_group("admin").

    Args:
        request: FastAPI request object
        credentials: HTTP authorization credentials

    Returns:
        TokenInfo if user is admin

    Raises:
        HTTPException: 401 if not authenticated, 403 if not admin

    Example:
        @app.post("/groups")
        def create_group(token: TokenInfo = Depends(require_admin)):
            return {"message": "Admin action performed"}
    """
    token_info = verify_token(request, credentials)
    if not token_info.has_group("admin"):
        auditor = get_security_auditor()
        if auditor:
            client_ip = request.client.host if request.client else "unknown"
            auditor.log_auth_failure(
                client_id=client_ip,
                reason="Admin access required",
                endpoint=str(request.url.path),
                groups=token_info.groups,
            )
        raise HTTPException(
            status_code=403,
            detail="Access denied. Admin privileges required.",
        )
    return token_info
