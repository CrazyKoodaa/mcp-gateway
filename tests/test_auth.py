"""Tests for mcp_gateway.auth module."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from mcp_gateway.auth import AuthConfig, AuthMiddleware, setup_auth, verify_auth


class TestAuthConfig:
    """Tests for AuthConfig class."""

    def test_default_values(self):
        """Test AuthConfig default values."""
        config = AuthConfig()
        assert config.api_key is None
        assert config.bearer_token is None
        assert config.exclude_paths == ["/health", "/docs", "/openapi.json"]

    def test_custom_values(self):
        """Test AuthConfig with custom values."""
        config = AuthConfig(
            api_key="test-api-key",
            bearer_token="test-bearer-token",
            exclude_paths=["/health", "/metrics"],
        )
        assert config.api_key == "test-api-key"
        assert config.bearer_token == "test-bearer-token"
        assert config.exclude_paths == ["/health", "/metrics"]

    def test_is_enabled_with_api_key(self):
        """Test is_enabled when api_key is set."""
        config = AuthConfig(api_key="test-key")
        assert config.is_enabled is True

    def test_is_enabled_with_bearer_token(self):
        """Test is_enabled when bearer_token is set."""
        config = AuthConfig(bearer_token="test-token")
        assert config.is_enabled is True

    def test_is_enabled_disabled(self):
        """Test is_enabled when no auth is configured."""
        config = AuthConfig()
        assert config.is_enabled is False

    def test_generate_api_key(self):
        """Test API key generation."""
        config = AuthConfig()
        api_key = config.generate_api_key()

        assert api_key.startswith("mg_")
        assert len(api_key) > 32


class TestAuthMiddleware:
    """Tests for AuthMiddleware class."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""
        request = MagicMock(spec=Request)
        request.url.path = "/mcp"
        request.headers = {}
        return request

    @pytest.fixture
    def auth_config(self):
        """Create an auth config with both auth methods."""
        return AuthConfig(api_key="test-api-key", bearer_token="test-bearer-token")

    @pytest.mark.asyncio
    async def test_excluded_path(self, mock_request, auth_config):
        """Test that excluded paths bypass authentication."""
        mock_request.url.path = "/health"
        middleware = AuthMiddleware(auth_config)

        result = await middleware(mock_request)

        assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_disabled_auth(self, mock_request):
        """Test that disabled auth allows all requests."""
        config = AuthConfig()  # No auth configured
        middleware = AuthMiddleware(config)

        result = await middleware(mock_request)

        assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_valid_api_key(self, mock_request, auth_config):
        """Test authentication with valid API key."""
        mock_request.headers = {"X-API-Key": "test-api-key"}
        middleware = AuthMiddleware(auth_config)

        result = await middleware(mock_request)

        assert result.startswith("apikey:")

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, mock_request, auth_config):
        """Test authentication with invalid API key."""
        mock_request.headers = {"X-API-Key": "wrong-key"}
        middleware = AuthMiddleware(auth_config)

        with pytest.raises(HTTPException) as exc_info:
            await middleware(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid API key" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_valid_bearer_token(self, mock_request, auth_config):
        """Test authentication with valid Bearer token."""
        mock_request.headers = {"Authorization": "Bearer test-bearer-token"}
        middleware = AuthMiddleware(auth_config)

        result = await middleware(mock_request)

        assert result.startswith("bearer:")

    @pytest.mark.asyncio
    async def test_invalid_bearer_token(self, mock_request, auth_config):
        """Test authentication with invalid Bearer token."""
        mock_request.headers = {"Authorization": "Bearer wrong-token"}
        middleware = AuthMiddleware(auth_config)

        with pytest.raises(HTTPException) as exc_info:
            await middleware(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid bearer token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_no_credentials(self, mock_request, auth_config):
        """Test authentication with no credentials."""
        middleware = AuthMiddleware(auth_config)

        with pytest.raises(HTTPException) as exc_info:
            await middleware(mock_request)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_bearer_without_prefix(self, mock_request, auth_config):
        """Test authentication with Bearer token missing 'Bearer ' prefix."""
        mock_request.headers = {"Authorization": "test-bearer-token"}
        middleware = AuthMiddleware(auth_config)

        with pytest.raises(HTTPException) as exc_info:
            await middleware(mock_request)

        assert exc_info.value.status_code == 401


class TestSetupAuth:
    """Tests for setup_auth function."""

    def test_setup_auth_disabled(self):
        """Test setup_auth when auth is disabled."""
        from fastapi import FastAPI

        app = FastAPI()
        config = AuthConfig()  # No auth

        setup_auth(app, config)

        # Should not add middleware when disabled
        assert getattr(app.state, "auth_middleware", None) is None

    def test_setup_auth_enabled(self):
        """Test setup_auth when auth is enabled."""
        from fastapi import FastAPI

        app = FastAPI()
        config = AuthConfig(api_key="test-key")

        setup_auth(app, config)

        # Should add middleware to app state
        assert app.state.auth_middleware is not None
        assert isinstance(app.state.auth_middleware, AuthMiddleware)
        assert app.state.auth_config == config

    def test_setup_auth_with_bearer(self):
        """Test setup_auth with Bearer token."""
        from fastapi import FastAPI

        app = FastAPI()
        config = AuthConfig(bearer_token="test-token")

        setup_auth(app, config)

        assert app.state.auth_middleware is not None


class TestVerifyAuth:
    """Tests for verify_auth function."""

    @pytest.mark.asyncio
    async def test_verify_auth_no_middleware(self):
        """Test verify_auth when no middleware is configured."""
        from fastapi import FastAPI, Request

        app = FastAPI()
        request = MagicMock(spec=Request)
        request.app = app

        result = await verify_auth(request)

        assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_verify_auth_with_middleware(self):
        """Test verify_auth with middleware configured."""
        from unittest.mock import AsyncMock

        from fastapi import FastAPI, Request

        app = FastAPI()
        mock_middleware = AsyncMock()
        mock_middleware.return_value = "client:123..."
        app.state.auth_middleware = mock_middleware

        request = MagicMock(spec=Request)
        request.app = app

        result = await verify_auth(request)

        assert result == "client:123..."
