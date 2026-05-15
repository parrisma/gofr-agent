"""Authentication Provider for FastAPI dependency injection.

Provides a clean dependency injection pattern for authentication,
replacing global state with explicit service injection.

Example:
    from fastapi import FastAPI, Depends
    from gofr_common.auth import AuthService, AuthProvider

    # Create auth service
    auth_service = AuthService(token_store=..., group_registry=...)

    # Create provider for dependency injection
    auth = AuthProvider(auth_service)

    app = FastAPI()

    # Use provider's dependencies
    @app.get("/protected")
    def protected_endpoint(token: TokenInfo = Depends(auth.verify_token)):
        return {"groups": token.groups}

    @app.get("/admin")
    def admin_endpoint(token: TokenInfo = Depends(auth.require_group("admin"))):
        return {"message": "Admin access granted"}

    # Or inject the service directly
    @app.get("/tokens")
    def list_tokens(service: AuthService = Depends(auth.get_service)):
        return service.list_tokens()
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Protocol

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .tokens import TokenInfo

if TYPE_CHECKING:
    from .jwt_secret_provider import JwtSecretProvider
    from .service import AuthService


class SecurityAuditorProtocol(Protocol):
    """Protocol for security auditor integration."""

    def log_auth_failure(
        self,
        client_id: str,
        reason: str,
        endpoint: Optional[str] = None,
        **details: Any,
    ) -> None:
        """Log authentication failure."""
        ...


# FastAPI security schemes
_security = HTTPBearer()
_optional_security = HTTPBearer(auto_error=False)


def _generate_fingerprint(request: Request) -> str:
    """Generate a device fingerprint from request context."""
    user_agent = request.headers.get("user-agent", "unknown")
    client_ip = request.client.host if request.client else "unknown"
    fingerprint_data = f"{user_agent}:{client_ip}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()


class AuthProvider:
    """Dependency injection provider for authentication.

    This class provides FastAPI dependencies for authentication without
    relying on global state. Create an instance with your AuthService
    and use its methods as FastAPI dependencies.

    Attributes:
        service: The underlying AuthService instance
        auditor: Optional security auditor for logging auth failures

    Example:
        # Setup
        auth_service = AuthService(...)
        auth = AuthProvider(auth_service)

        # Use in FastAPI
        @app.get("/api/data")
        def get_data(token: TokenInfo = Depends(auth.verify_token)):
            return {"user_groups": token.groups}

        @app.post("/api/admin")
        def admin_action(token: TokenInfo = Depends(auth.require_admin)):
            return {"status": "ok"}
    """

    def __init__(
        self,
        auth_service: "AuthService",
        auditor: Optional[SecurityAuditorProtocol] = None,
    ) -> None:
        """Initialize the auth provider.

        Args:
            auth_service: The AuthService instance to use
            auditor: Optional security auditor for logging failures
        """
        self._service = auth_service
        self._auditor = auditor

    @property
    def service(self) -> "AuthService":
        """Get the underlying AuthService instance."""
        return self._service

    @property
    def auditor(self) -> Optional[SecurityAuditorProtocol]:
        """Get the security auditor if configured."""
        return self._auditor

    def set_auditor(self, auditor: Optional[SecurityAuditorProtocol]) -> None:
        """Set or clear the security auditor.

        Args:
            auditor: Security auditor instance or None to disable
        """
        self._auditor = auditor

    def get_service(self) -> "AuthService":
        """FastAPI dependency that returns the AuthService.

        Use this when you need direct access to the service.

        Example:
            @app.get("/tokens")
            def list_tokens(service: AuthService = Depends(auth.get_service)):
                return service.list_tokens()
        """
        return self._service

    def _log_failure(
        self,
        request: Request,
        reason: str,
        groups: Optional[List[str]] = None,
    ) -> None:
        """Log authentication/authorization failure if auditor configured."""
        if self._auditor:
            client_ip = request.client.host if request.client else "unknown"
            kwargs: dict[str, Any] = {
                "client_id": client_ip,
                "reason": reason,
                "endpoint": str(request.url.path),
            }
            if groups is not None:
                kwargs["groups"] = groups
            self._auditor.log_auth_failure(**kwargs)

    def verify_token(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(_security),
    ) -> TokenInfo:
        """Verify JWT token from request with fingerprinting.

        This is a FastAPI dependency function.

        Args:
            request: FastAPI request object
            credentials: HTTP authorization credentials

        Returns:
            TokenInfo with groups and expiry information

        Raises:
            HTTPException: 401 if token invalid, 500 if service error
        """
        try:
            fingerprint = _generate_fingerprint(request)
            return self._service.verify_token(
                credentials.credentials,
                fingerprint=fingerprint,
            )
        except ValueError as e:
            self._log_failure(request, str(e))
            raise HTTPException(status_code=401, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    def verify_token_strict(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(_security),
    ) -> TokenInfo:
        """Verify JWT token with group validation.

        Like verify_token(), but also validates that all groups in the token
        are still active in the group registry. Use this when you need
        real-time enforcement of group status.

        This is a FastAPI dependency function.

        Args:
            request: FastAPI request object
            credentials: HTTP authorization credentials

        Returns:
            TokenInfo with groups and expiry information

        Raises:
            HTTPException: 401 if token invalid, 403 if group defunct, 500 if service error
        """
        from .exceptions import InvalidGroupError

        try:
            fingerprint = _generate_fingerprint(request)
            return self._service.verify_token(
                credentials.credentials,
                fingerprint=fingerprint,
                validate_groups=True,
            )
        except InvalidGroupError as e:
            self._log_failure(request, str(e))
            raise HTTPException(status_code=403, detail=str(e))
        except ValueError as e:
            self._log_failure(request, str(e))
            raise HTTPException(status_code=401, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    def verify_token_optional(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_optional_security),
    ) -> Optional[TokenInfo]:
        """Optionally verify JWT token - returns None if not provided.

        This is a FastAPI dependency function.

        Args:
            request: FastAPI request object
            credentials: HTTP authorization credentials (optional)

        Returns:
            TokenInfo if token provided and valid, None otherwise

        Raises:
            HTTPException: 401 if token provided but invalid
        """
        if credentials is None:
            return None

        try:
            fingerprint = _generate_fingerprint(request)
            return self._service.verify_token(
                credentials.credentials,
                fingerprint=fingerprint,
            )
        except ValueError as e:
            self._log_failure(request, str(e))
            raise HTTPException(status_code=401, detail=str(e))
        except RuntimeError:
            return None

    def verify_token_simple(
        self,
        credentials: HTTPAuthorizationCredentials = Security(_security),
    ) -> TokenInfo:
        """Verify JWT token without fingerprinting.

        Use when you don't need device binding or don't have Request access.

        Args:
            credentials: HTTP authorization credentials

        Returns:
            TokenInfo with groups and expiry information

        Raises:
            HTTPException: 401 if token invalid, 500 if service error
        """
        try:
            return self._service.verify_token(credentials.credentials)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    def require_group(self, group_name: str) -> Callable[..., TokenInfo]:
        """Create a dependency requiring a specific group.

        Args:
            group_name: Name of the required group

        Returns:
            FastAPI dependency function

        Example:
            @app.get("/users")
            def list_users(token: TokenInfo = Depends(auth.require_group("users"))):
                return {"groups": token.groups}
        """

        def _require_group(
            request: Request,
            credentials: HTTPAuthorizationCredentials = Security(_security),
        ) -> TokenInfo:
            token_info = self.verify_token(request, credentials)
            if not token_info.has_group(group_name):
                self._log_failure(
                    request,
                    f"Missing required group: {group_name}",
                    groups=token_info.groups,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Required group: {group_name}",
                )
            return token_info

        return _require_group

    def require_any_group(self, group_names: List[str]) -> Callable[..., TokenInfo]:
        """Create a dependency requiring any of the specified groups.

        Args:
            group_names: List of group names (any one is sufficient)

        Returns:
            FastAPI dependency function

        Example:
            @app.get("/data")
            def get_data(token: TokenInfo = Depends(auth.require_any_group(["admin", "users"]))):
                return {"data": "..."}
        """

        def _require_any_group(
            request: Request,
            credentials: HTTPAuthorizationCredentials = Security(_security),
        ) -> TokenInfo:
            token_info = self.verify_token(request, credentials)
            if not token_info.has_any_group(group_names):
                self._log_failure(
                    request,
                    f"Missing required groups (any of): {group_names}",
                    groups=token_info.groups,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Required groups (any of): {group_names}",
                )
            return token_info

        return _require_any_group

    def require_all_groups(self, group_names: List[str]) -> Callable[..., TokenInfo]:
        """Create a dependency requiring all of the specified groups.

        Args:
            group_names: List of group names (all are required)

        Returns:
            FastAPI dependency function

        Example:
            @app.delete("/critical")
            def delete_critical(token: TokenInfo = Depends(auth.require_all_groups(["admin", "superuser"]))):
                return {"deleted": True}
        """

        def _require_all_groups(
            request: Request,
            credentials: HTTPAuthorizationCredentials = Security(_security),
        ) -> TokenInfo:
            token_info = self.verify_token(request, credentials)
            if not token_info.has_all_groups(group_names):
                missing = set(group_names) - set(token_info.groups)
                self._log_failure(
                    request,
                    f"Missing required groups: {list(missing)}",
                    groups=token_info.groups,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Missing groups: {list(missing)}",
                )
            return token_info

        return _require_all_groups

    @property
    def require_admin(self) -> Callable[..., TokenInfo]:
        """Dependency requiring admin group membership.

        Convenience property equivalent to require_group("admin").

        Example:
            @app.post("/groups")
            def create_group(token: TokenInfo = Depends(auth.require_admin)):
                return {"created": True}
        """
        return self.require_group("admin")


def create_auth_provider(
    auth_service: Optional["AuthService"] = None,
    secret_provider: Optional["JwtSecretProvider"] = None,
    auditor: Optional[SecurityAuditorProtocol] = None,
) -> AuthProvider:
    """Factory function to create an AuthProvider.

    If no auth_service is provided, creates one using environment configuration.

    Args:
        auth_service: Existing AuthService (preferred)
        secret_provider: JwtSecretProvider if creating new service
        auditor: Optional security auditor

    Returns:
        Configured AuthProvider

    Example:
        # With existing service
        auth = create_auth_provider(auth_service=my_service)

        # From environment
        auth = create_auth_provider()
    """
    if auth_service is None:
        from .backends import create_stores_from_env, create_vault_client_from_env
        from .groups import GroupRegistry
        from .jwt_secret_provider import JwtSecretProvider
        from .service import AuthService

        if secret_provider is None:
            vault_client = create_vault_client_from_env("GOFR")
            secret_provider = JwtSecretProvider(vault_client=vault_client)
            token_store, group_store = create_stores_from_env("GOFR", vault_client=vault_client)
        else:
            token_store, group_store = create_stores_from_env("GOFR")
        groups = GroupRegistry(store=group_store)
        auth_service = AuthService(
            token_store=token_store,
            group_registry=groups,
            secret_provider=secret_provider,
        )

    return AuthProvider(auth_service=auth_service, auditor=auditor)
