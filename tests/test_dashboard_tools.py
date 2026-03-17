"""Tests for Dashboard Tools Loading functionality.

These tests verify that the /api/servers/{name}/tools endpoint
returns correct tool data for the dashboard to display.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.types import Tool

from mcp_gateway.backends import BackendConnection
from mcp_gateway.config import GatewayConfig, ServerConfig
from mcp_gateway.server.http_routes import setup_http_routes
from mcp_gateway.server.state import ServerDependencies


class MockBackend:
    """Mock backend for testing."""

    def __init__(self, name: str, connected: bool = True, tools: list[Tool] | None = None):
        self.name = name
        self._connected = connected
        self._tools = tools or []

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[Tool]:
        return self._tools.copy()


class MockBackendManager:
    """Mock backend manager for testing."""

    def __init__(self, backends: dict[str, MockBackend] | None = None):
        self.backends = backends or {}


class MockConfigManager:
    """Mock config manager for testing."""

    def __init__(self, servers: dict[str, ServerConfig] | None = None):
        self.gateway_config = MagicMock()
        self.gateway_config.servers = servers or {}


@pytest.fixture
def mock_deps() -> ServerDependencies:
    """Create mock dependencies for testing."""
    return ServerDependencies(
        config=MagicMock(spec=GatewayConfig),
        backend_manager=MockBackendManager(),
        config_manager=None,  # Will be set per test
        supervisor=None,
        audit_service=None,
        path_security=None,
        access_control=None,
        config_approval=None,
        rate_limiter=None,
        circuit_breaker_registry=None,
        metrics=None,
        auth=None,
        templates=None,
    )


@pytest.fixture
def app(mock_deps: ServerDependencies) -> FastAPI:
    """Create FastAPI test app with routes."""
    test_app = FastAPI()
    setup_http_routes(test_app, mock_deps, enable_access_control=False)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestGetServerTools:
    """Test suite for GET /api/servers/{name}/tools endpoint."""

    def test_backend_connected_with_tools(self, client: TestClient, mock_deps: ServerDependencies):
        """Test: Backend connected with tools returns tools list."""
        # Arrange
        tools = [
            Tool(name="tool1", description="First tool", inputSchema={}),
            Tool(name="tool2", description="Second tool", inputSchema={}),
        ]
        mock_deps.backend_manager.backends["test-server"] = MockBackend(
            name="test-server", connected=True, tools=tools
        )
        mock_deps.config_manager = MockConfigManager()

        # Act
        response = client.get("/api/servers/test-server/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 2
        assert data["tools"][0]["name"] == "tool1"
        assert data["tools"][0]["description"] == "First tool"
        assert data["tools"][1]["name"] == "tool2"
        assert data["disabledTools"] == []

    def test_backend_connected_no_tools(self, client: TestClient, mock_deps: ServerDependencies):
        """Test: Backend connected but no tools returns empty list."""
        # Arrange
        mock_deps.backend_manager.backends["empty-server"] = MockBackend(
            name="empty-server", connected=True, tools=[]
        )
        mock_deps.config_manager = MockConfigManager()

        # Act
        response = client.get("/api/servers/empty-server/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []
        assert data["disabledTools"] == []

    def test_backend_disconnected_returns_empty_tools(
        self, client: TestClient, mock_deps: ServerDependencies
    ):
        """Test: Backend disconnected returns empty tools (not error)."""
        # Arrange
        tools = [Tool(name="hidden_tool", description="Should not appear", inputSchema={})]
        mock_deps.backend_manager.backends["disconnected-server"] = MockBackend(
            name="disconnected-server",
            connected=False,  # Not connected
            tools=tools,
        )
        mock_deps.config_manager = MockConfigManager()

        # Act
        response = client.get("/api/servers/disconnected-server/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []  # Empty because not connected
        assert data["disabledTools"] == []

    def test_backend_not_found_returns_404(self, client: TestClient, mock_deps: ServerDependencies):
        """Test: Non-existent backend returns 404."""
        # Act
        response = client.get("/api/servers/nonexistent/tools")

        # Assert
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_tools_with_disabled_tools(self, client: TestClient, mock_deps: ServerDependencies):
        """Test: Tools endpoint includes disabled tools from config."""
        # Arrange
        tools = [
            Tool(name="enabled_tool", description="Enabled", inputSchema={}),
            Tool(name="disabled_tool", description="Disabled in config", inputSchema={}),
        ]
        mock_deps.backend_manager.backends["server-with-disabled"] = MockBackend(
            name="server-with-disabled", connected=True, tools=tools
        )

        server_config = MagicMock(spec=ServerConfig)
        server_config.disabled_tools = ["disabled_tool"]
        mock_deps.config_manager = MockConfigManager(
            servers={"server-with-disabled": server_config}
        )

        # Act
        response = client.get("/api/servers/server-with-disabled/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 2  # All tools returned
        assert data["disabledTools"] == ["disabled_tool"]

    def test_tool_description_defaults_to_empty_string(
        self, client: TestClient, mock_deps: ServerDependencies
    ):
        """Test: Tool without description defaults to empty string."""
        # Arrange
        tools = [
            Tool(name="no_desc_tool", description=None, inputSchema={}),
        ]
        mock_deps.backend_manager.backends["desc-test"] = MockBackend(
            name="desc-test", connected=True, tools=tools
        )
        mock_deps.config_manager = MockConfigManager()

        # Act
        response = client.get("/api/servers/desc-test/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["tools"][0]["description"] == ""

    def test_no_config_manager_returns_empty_disabled(
        self, client: TestClient, mock_deps: ServerDependencies
    ):
        """Test: When config_manager is None, disabledTools is empty."""
        # Arrange
        tools = [Tool(name="tool1", description="Test", inputSchema={})]
        mock_deps.backend_manager.backends["no-config"] = MockBackend(
            name="no-config", connected=True, tools=tools
        )
        mock_deps.config_manager = None  # No config manager

        # Act
        response = client.get("/api/servers/no-config/tools")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 1
        assert data["disabledTools"] == []


class TestDashboardToolLoadingScenarios:
    """Integration tests for dashboard tool loading scenarios."""

    def test_dashboard_fetches_tools_for_all_backends(
        self, client: TestClient, mock_deps: ServerDependencies
    ):
        """Test: Dashboard scenario - fetches tools for each backend."""
        # Arrange - Simulate multiple backends
        mock_deps.backend_manager.backends = {
            "memory": MockBackend(
                name="memory",
                connected=True,
                tools=[
                    Tool(
                        name="create_entities", description="Create memory entities", inputSchema={}
                    ),
                    Tool(name="search_nodes", description="Search nodes", inputSchema={}),
                ],
            ),
            "filesystem": MockBackend(
                name="filesystem",
                connected=True,
                tools=[
                    Tool(name="read_file", description="Read a file", inputSchema={}),
                    Tool(name="write_file", description="Write a file", inputSchema={}),
                    Tool(name="list_directory", description="List directory", inputSchema={}),
                ],
            ),
            "disconnected": MockBackend(
                name="disconnected",
                connected=False,
                tools=[Tool(name="broken_tool", description="Won't show", inputSchema={})],
            ),
        }
        mock_deps.config_manager = MockConfigManager()

        # Act & Assert - Fetch tools for each backend
        # Memory server
        response = client.get("/api/servers/memory/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 2

        # Filesystem server
        response = client.get("/api/servers/filesystem/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 3

        # Disconnected server
        response = client.get("/api/servers/disconnected/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 0  # No tools when disconnected


class TestBackendConnectionProperty:
    """Tests for BackendConnection properties that affect tool visibility."""

    def test_backend_connection_is_connected_requires_session(self):
        """Test: is_connected requires both _connected=True and session."""
        from mcp_gateway.config import ServerConfig

        config = ServerConfig(
            name="test",
            command="echo",
            args=["test"],
        )
        backend = BackendConnection(config)

        # Initially not connected
        assert backend.is_connected is False

        # Manually set connected flag (but no session)
        backend._connected = True
        assert backend.is_connected is False  # Still false because no session

    def test_backend_tools_returns_copy(self):
        """Test: tools property returns a copy to prevent external mutation."""
        from mcp_gateway.config import ServerConfig

        config = ServerConfig(name="test", command="echo", args=["test"])
        backend = BackendConnection(config)

        # Set internal tools
        backend._tools = [Tool(name="tool1", description="Test", inputSchema={})]

        # Get tools
        tools1 = backend.tools
        tools2 = backend.tools

        # Should be different copies
        assert tools1 is not tools2
        assert tools1 == tools2
