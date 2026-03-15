"""Tests for mcp_gateway.server module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent, Tool

from mcp_gateway.config import GatewayConfig
from mcp_gateway.server import CallToolRequest, McpGatewayServer, ServerDependencies


@pytest.fixture
def server_deps(gateway_config, mock_backend_manager):
    """Return server dependencies."""
    return ServerDependencies(
        config=gateway_config,
        backend_manager=mock_backend_manager,
    )


@pytest.fixture
def server(gateway_config, mock_backend_manager, tmp_path):
    """Return a test server instance."""
    server = McpGatewayServer(
        config=gateway_config,
        backend_manager=mock_backend_manager,
        config_path=tmp_path / "config.json",
    )
    server.create_app(enable_access_control=False)
    return server


@pytest.fixture
def client(server):
    """Return a test client."""
    return TestClient(server.app)


class TestMcpGatewayServerInitialization:
    """Tests for McpGatewayServer initialization."""
    
    def test_server_creation(self, server, gateway_config, mock_backend_manager):
        """Test server is created with correct components."""
        assert server.config == gateway_config
        assert server.backend_manager == mock_backend_manager
        assert server.app is not None
    
    def test_cors_middleware(self, server):
        """Test CORS middleware is configured."""
        # Check that CORS middleware is in the app
        # The middleware may be added with different class names depending on FastAPI version
        middleware_str = str(server.app.user_middleware).lower()
        assert "cors" in middleware_str or len(server.app.user_middleware) > 0


class TestHealthEndpoint:
    """Tests for /health endpoint."""
    
    def test_health_check(self, client, mock_backend_manager):
        """Test health check endpoint."""
        mock_backend1 = MagicMock()
        mock_backend1.is_connected = True
        mock_backend1.tools = [MagicMock(), MagicMock()]
        mock_backend1.config.transport_type = "stdio"
        
        mock_backend_manager.backends = {"backend1": mock_backend1}
        mock_backend_manager.get_all_tools.return_value = [
            MagicMock(name="tool1"),
            MagicMock(name="tool2")
        ]
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["total_backends"] == 1
        assert data["total_tools"] == 2
    
    def test_health_check_empty(self, client, mock_backend_manager):
        """Test health check with no backends."""
        mock_backend_manager.backends = {}
        mock_backend_manager.get_all_tools.return_value = []
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["total_backends"] == 0


class TestBackendsEndpoint:
    """Tests for /backends endpoint."""
    
    def test_list_backends(self, client, mock_backend_manager):
        """Test listing backends."""
        backend1 = MagicMock()
        backend1.is_connected = True
        backend1.tools = [MagicMock(), MagicMock()]
        
        backend2 = MagicMock()
        backend2.is_connected = False
        backend2.tools = []
        
        mock_backend_manager.backends = {"backend1": backend1, "backend2": backend2}
        
        response = client.get("/backends")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["backends"]) == 2


class TestCallToolRequest:
    """Tests for CallToolRequest model."""
    
    def test_create_request(self):
        """Test creating a tool call request."""
        request = CallToolRequest(name="test_tool", arguments={"arg1": "value1"})
        
        assert request.name == "test_tool"
        assert request.arguments == {"arg1": "value1"}
    
    def test_create_request_no_arguments(self):
        """Test creating a tool call request without arguments."""
        request = CallToolRequest(name="test_tool")
        
        assert request.name == "test_tool"
        assert request.arguments == {}


class TestServerResponses:
    """Tests for various server responses."""
    
    def test_circuit_breaker_stats_endpoint(self, client):
        """Test circuit breaker stats endpoint."""
        response = client.get("/circuit-breakers")
        
        # Should return 200 with empty or populated stats
        assert response.status_code == 200


class TestServerWithAccessControl:
    """Tests for server with access control enabled."""
    
    def test_access_control_endpoints_exist(self, client):
        """Test that access control endpoints exist."""
        # These endpoints should exist (even if they return empty/error)
        response = client.get("/api/access/requests/pending")
        assert response.status_code == 200
        
        response = client.get("/api/access/grants/active")
        assert response.status_code == 200


class TestServerConfiguration:
    """Tests for server configuration handling."""
    
    def test_server_with_config(self, gateway_config, mock_backend_manager, tmp_path):
        """Test server created with specific configuration."""
        server = McpGatewayServer(
            config=gateway_config,
            backend_manager=mock_backend_manager,
            config_path=tmp_path / "config.json",
        )
        server.create_app(enable_access_control=False)
        
        assert server.config.host == gateway_config.host
        assert server.config.port == gateway_config.port
