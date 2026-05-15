"""Tests for gofr_common.web module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCORSConfig:
    """Tests for CORSConfig class."""

    def test_default_config(self):
        """Test default CORSConfig values."""
        from gofr_common.web import CORSConfig

        config = CORSConfig()

        assert config.allow_origins == ["*"]
        assert "GET" in config.allow_methods
        assert "POST" in config.allow_methods
        assert config.allow_headers == ["*"]
        assert config.allow_credentials is True
        assert config.expose_headers == []
        assert config.max_age == 600

    def test_permissive_factory(self):
        """Test CORSConfig.permissive() factory."""
        from gofr_common.web import CORSConfig

        config = CORSConfig.permissive()

        assert config.allow_origins == ["*"]
        assert config.allow_credentials is True

    def test_for_mcp_factory(self):
        """Test CORSConfig.for_mcp() factory."""
        from gofr_common.web import CORSConfig

        config = CORSConfig.for_mcp()

        assert config.allow_origins == ["*"]
        assert "Mcp-Session-Id" in config.expose_headers
        assert config.allow_methods == ["GET", "POST", "DELETE"]

    def test_for_mcp_with_env_prefix(self):
        """Test CORSConfig.for_mcp() with environment prefix."""
        from gofr_common.web import CORSConfig

        with patch.dict(os.environ, {"GOFR_TEST_CORS_ORIGINS": "https://example.com"}):
            config = CORSConfig.for_mcp("GOFR_TEST")

        assert config.allow_origins == ["https://example.com"]
        assert "Mcp-Session-Id" in config.expose_headers

    def test_from_env_default(self):
        """Test CORSConfig.from_env() with defaults."""
        from gofr_common.web import CORSConfig

        # Clear env var if set
        with patch.dict(os.environ, {}, clear=True):
            config = CORSConfig.from_env("GOFR_TEST")

        assert "http://localhost:3000" in config.allow_origins
        assert "http://localhost:8000" in config.allow_origins

    def test_from_env_wildcard(self):
        """Test CORSConfig.from_env() with wildcard."""
        from gofr_common.web import CORSConfig

        with patch.dict(os.environ, {"GOFR_TEST_CORS_ORIGINS": "*"}):
            config = CORSConfig.from_env("GOFR_TEST")

        assert config.allow_origins == ["*"]

    def test_from_env_multiple_origins(self):
        """Test CORSConfig.from_env() with multiple origins."""
        from gofr_common.web import CORSConfig

        origins = "https://example.com, https://app.example.com"
        with patch.dict(os.environ, {"GOFR_TEST_CORS_ORIGINS": origins}):
            config = CORSConfig.from_env("GOFR_TEST")

        assert "https://example.com" in config.allow_origins
        assert "https://app.example.com" in config.allow_origins

    def test_from_env_credentials_false(self):
        """Test CORSConfig.from_env() with credentials disabled."""
        from gofr_common.web import CORSConfig

        with patch.dict(os.environ, {"GOFR_TEST_CORS_CREDENTIALS": "false"}):
            config = CORSConfig.from_env("GOFR_TEST")

        assert config.allow_credentials is False


class TestGetCorsOrigins:
    """Tests for get_cors_origins function."""

    def test_wildcard(self):
        """Test wildcard origin."""
        from gofr_common.web import get_cors_origins

        result = get_cors_origins("*")
        assert result == ["*"]

    def test_single_origin(self):
        """Test single origin."""
        from gofr_common.web import get_cors_origins

        result = get_cors_origins("https://example.com")
        assert result == ["https://example.com"]

    def test_multiple_origins(self):
        """Test multiple comma-separated origins."""
        from gofr_common.web import get_cors_origins

        result = get_cors_origins("https://a.com, https://b.com")
        assert result == ["https://a.com", "https://b.com"]

    def test_empty_parts_filtered(self):
        """Test that empty parts are filtered out."""
        from gofr_common.web import get_cors_origins

        result = get_cors_origins("https://a.com,,https://b.com")
        assert result == ["https://a.com", "https://b.com"]


class TestCreateCorsMiddleware:
    """Tests for create_cors_middleware function."""

    def test_creates_middleware(self):
        """Test that middleware is created."""
        from starlette.applications import Starlette

        from gofr_common.web import CORSConfig, create_cors_middleware

        app = Starlette()
        config = CORSConfig.permissive()

        result = create_cors_middleware(app, config)

        # Result should be CORSMiddleware wrapped app
        assert result is not None
        assert hasattr(result, "app")

    def test_default_config_when_none(self):
        """Test default permissive config when None provided."""
        from starlette.applications import Starlette

        from gofr_common.web import create_cors_middleware

        app = Starlette()
        result = create_cors_middleware(app)

        assert result is not None


class TestAuthHeaderMiddleware:
    """Tests for AuthHeaderMiddleware."""

    @pytest.mark.asyncio
    async def test_extracts_auth_header(self):
        """Test that auth header is extracted to context."""
        from gofr_common.web import AuthHeaderMiddleware, get_auth_header_from_context

        # Track if app was called
        app_called = False
        captured_header = None

        async def mock_app(scope, receive, send):
            nonlocal app_called, captured_header
            app_called = True
            captured_header = get_auth_header_from_context()

        middleware = AuthHeaderMiddleware(mock_app)

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token")],
        }

        await middleware(scope, None, None)

        assert app_called
        assert captured_header == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_no_auth_header(self):
        """Test behavior when no auth header present."""
        from gofr_common.web import AuthHeaderMiddleware, get_auth_header_from_context

        captured_header = None

        async def mock_app(scope, receive, send):
            nonlocal captured_header
            captured_header = get_auth_header_from_context()

        middleware = AuthHeaderMiddleware(mock_app)

        scope = {
            "type": "http",
            "headers": [],
        }

        await middleware(scope, None, None)

        assert captured_header == ""

    @pytest.mark.asyncio
    async def test_passthrough_non_http(self):
        """Test that non-HTTP requests pass through."""
        from gofr_common.web import AuthHeaderMiddleware

        app_called = False

        async def mock_app(scope, receive, send):
            nonlocal app_called
            app_called = True

        middleware = AuthHeaderMiddleware(mock_app)

        scope = {"type": "websocket"}

        await middleware(scope, None, None)

        assert app_called


class TestRequestLoggingMiddleware:
    """Tests for RequestLoggingMiddleware."""

    @pytest.mark.asyncio
    async def test_logs_request(self):
        """Test that requests are logged."""
        from gofr_common.web.middleware import RequestLoggingMiddleware

        logger = MagicMock()

        async def mock_app(scope, receive, send):
            # Send a response
            await send({
                "type": "http.response.start",
                "status": 200,
            })
            await send({
                "type": "http.response.body",
                "body": b"",
            })

        middleware = RequestLoggingMiddleware(mock_app, logger)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
        }

        await middleware(scope, None, AsyncMock())

        # Logger should have been called
        logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_logger_passthrough(self):
        """Test passthrough when no logger provided."""
        from gofr_common.web.middleware import RequestLoggingMiddleware

        app_called = False

        async def mock_app(scope, receive, send):
            nonlocal app_called
            app_called = True

        middleware = RequestLoggingMiddleware(mock_app, logger=None)

        scope = {"type": "http", "method": "GET", "path": "/"}

        await middleware(scope, None, None)

        assert app_called


class TestHealthResponses:
    """Tests for health check response functions."""

    def test_create_ping_response(self):
        """Test create_ping_response function."""
        from gofr_common.web import create_ping_response

        response = create_ping_response("gofr-test")

        assert response["status"] == "ok"
        assert response["service"] == "gofr-test"
        assert "timestamp" in response

    def test_create_ping_response_custom_status(self):
        """Test create_ping_response with custom status."""
        from gofr_common.web import create_ping_response

        response = create_ping_response("gofr-test", status="degraded")

        assert response["status"] == "degraded"

    def test_create_health_response(self):
        """Test create_health_response function."""
        from gofr_common.web import create_health_response

        response = create_health_response("gofr-test", auth_enabled=True)

        assert response["status"] == "healthy"
        assert response["service"] == "gofr-test"
        assert response["auth_enabled"] is True

    def test_create_health_response_unhealthy(self):
        """Test create_health_response when unhealthy."""
        from gofr_common.web import create_health_response

        response = create_health_response("gofr-test", healthy=False)

        assert response["status"] == "unhealthy"

    def test_create_health_response_extra_fields(self):
        """Test create_health_response with extra fields."""
        from gofr_common.web import create_health_response

        response = create_health_response(
            "gofr-test",
            extra={"version": "1.0.0", "uptime": 3600},
        )

        assert response["version"] == "1.0.0"
        assert response["uptime"] == 3600


class TestCreateHealthRoutes:
    """Tests for create_health_routes function."""

    def test_creates_routes(self):
        """Test that routes are created."""
        from gofr_common.web import create_health_routes

        routes = create_health_routes("gofr-test")

        assert len(routes) == 2

        paths = [r.path for r in routes]
        assert "/ping" in paths
        assert "/health" in paths

    @pytest.mark.asyncio
    async def test_ping_endpoint(self):
        """Test ping route handler."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from gofr_common.web import create_health_routes

        routes = create_health_routes("gofr-test")
        app = Starlette(routes=routes)

        client = TestClient(app)
        response = client.get("/ping")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "gofr-test"

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health route handler."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from gofr_common.web import create_health_routes

        routes = create_health_routes("gofr-test", auth_enabled=True)
        app = Starlette(routes=routes)

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["auth_enabled"] is True

    @pytest.mark.asyncio
    async def test_health_with_check_function(self):
        """Test health route with custom check function."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from gofr_common.web import create_health_routes

        def unhealthy_check():
            return False

        routes = create_health_routes("gofr-test", health_check=unhealthy_check)
        app = Starlette(routes=routes)

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"


class TestCreateStarletteApp:
    """Tests for create_starlette_app factory."""

    def test_creates_app(self):
        """Test basic app creation."""
        from gofr_common.web import create_starlette_app

        app = create_starlette_app()

        assert app is not None

    def test_with_routes(self):
        """Test app creation with routes."""
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from gofr_common.web import create_starlette_app

        async def hello(request):
            return JSONResponse({"message": "hello"})

        routes = [Route("/hello", endpoint=hello)]
        app = create_starlette_app(routes=routes)

        client = TestClient(app)
        response = client.get("/hello")

        assert response.status_code == 200
        assert response.json()["message"] == "hello"

    def test_with_cors_config(self):
        """Test app creation with CORS config."""
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from gofr_common.web import CORSConfig, create_starlette_app

        async def test_endpoint(request):
            return JSONResponse({"ok": True})

        config = CORSConfig(allow_origins=["https://example.com"])
        routes = [Route("/test", endpoint=test_endpoint)]

        app = create_starlette_app(routes=routes, cors_config=config)

        client = TestClient(app)

        # Test CORS preflight
        response = client.options(
            "/test",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        # Should have CORS headers
        assert "access-control-allow-origin" in response.headers


class TestCreateMcpStarletteApp:
    """Tests for create_mcp_starlette_app factory."""

    def test_creates_mcp_app(self):
        """Test MCP app creation."""
        from gofr_common.web import create_mcp_starlette_app

        async def mock_mcp_handler(scope, receive, send):
            pass

        app = create_mcp_starlette_app(mcp_handler=mock_mcp_handler)

        assert app is not None

    def test_with_env_prefix(self):
        """Test MCP app with environment prefix."""
        from gofr_common.web import create_mcp_starlette_app

        async def mock_mcp_handler(scope, receive, send):
            pass

        with patch.dict(os.environ, {"GOFR_TEST_CORS_ORIGINS": "https://example.com"}):
            app = create_mcp_starlette_app(
                mcp_handler=mock_mcp_handler,
                env_prefix="GOFR_TEST",
            )

        assert app is not None

    def test_custom_mcp_path(self):
        """Test MCP app with custom path."""
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        from gofr_common.web import create_mcp_starlette_app

        async def mock_mcp_handler(scope, receive, send):
            response = JSONResponse({"type": "mcp"})
            await response(scope, receive, send)

        app = create_mcp_starlette_app(
            mcp_handler=mock_mcp_handler,
            mcp_path="/api/mcp/",
        )

        client = TestClient(app)
        response = client.get("/api/mcp/")

        assert response.status_code == 200

    def test_with_additional_routes(self):
        """Test MCP app with additional routes."""
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from gofr_common.web import create_mcp_starlette_app

        async def mock_mcp_handler(scope, receive, send):
            pass

        async def status_endpoint(request):
            return JSONResponse({"status": "ok"})

        additional = [Route("/status", endpoint=status_endpoint)]

        app = create_mcp_starlette_app(
            mcp_handler=mock_mcp_handler,
            additional_routes=additional,
        )

        client = TestClient(app)
        response = client.get("/status")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAuthContextFunctions:
    """Tests for auth context helper functions."""

    def test_set_and_get_context(self):
        """Test setting and getting auth header context."""
        from gofr_common.web import (
            get_auth_header_from_context,
            reset_auth_header_context,
            set_auth_header_context,
        )

        # Initial state should be empty
        assert get_auth_header_from_context() == ""

        # Set a value
        token = set_auth_header_context("Bearer test123")
        assert get_auth_header_from_context() == "Bearer test123"

        # Reset
        reset_auth_header_context(token)
        assert get_auth_header_from_context() == ""
