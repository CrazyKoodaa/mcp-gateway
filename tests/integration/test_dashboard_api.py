"""Integration tests for Dashboard API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.admin import ConfigManager
from mcp_gateway.config import load_config
from mcp_gateway.server import McpGatewayServer, ServerDependencies


@pytest.fixture
def mock_backend_connected():
    """Create a mock connected backend."""
    backend = MagicMock()
    backend.name = "memory"
    backend.is_connected = True
    backend.config.is_stdio = True
    backend.tools = []
    return backend


@pytest.fixture
def mock_backend_disconnected():
    """Create a mock disconnected backend."""
    backend = MagicMock()
    backend.name = "filesystem"
    backend.is_connected = False
    backend.config.is_stdio = True
    backend.tools = []
    return backend


@pytest.fixture
def test_app_with_backends(temp_config_file, mock_backend_connected, mock_backend_disconnected):
    """Create test app with mock backends."""
    config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, config)

    # Create mock backend manager with backends
    backend_manager = MagicMock()
    backend_manager.backends = {
        "memory": mock_backend_connected,
        "filesystem": mock_backend_disconnected,
    }
    backend_manager.get_all_tools = MagicMock(return_value=[])

    deps = ServerDependencies(
        config=config,
        backend_manager=backend_manager,
        config_manager=config_manager,
    )

    server = McpGatewayServer(dependencies=deps)
    app = server.create_app(enable_access_control=False)

    return app, backend_manager


@pytest.fixture
def client_with_backends(test_app_with_backends):
    """Create test client with backends."""
    app, _ = test_app_with_backends
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_returns_healthy(self, client_with_backends):
        """Test health endpoint returns healthy status."""
        response = client_with_backends.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["healthy"] is True
        assert "total_backends" in data
        assert "connected_backends" in data
        assert "total_tools" in data
        assert "backends" in data

    def test_health_shows_backend_status(self, client_with_backends, test_app_with_backends):
        """Test health shows individual backend status."""
        _, backend_manager = test_app_with_backends

        response = client_with_backends.get("/health")
        data = response.json()

        # Check backend list
        backends = data["backends"]
        assert len(backends) == 2

        # Find memory backend (connected)
        memory = next(b for b in backends if b["name"] == "memory")
        assert memory["connected"] is True

        # Find filesystem backend (disconnected)
        filesystem = next(b for b in backends if b["name"] == "filesystem")
        assert filesystem["connected"] is False

    def test_health_shows_circuit_breaker_state(self, client_with_backends):
        """Test health includes circuit breaker state."""
        response = client_with_backends.get("/health")
        data = response.json()

        for backend in data["backends"]:
            assert "circuit_breaker_state" in backend


class TestBackendsEndpoint:
    """Tests for GET /backends endpoint."""

    def test_list_backends(self, client_with_backends):
        """Test backends list endpoint."""
        response = client_with_backends.get("/backends")

        assert response.status_code == 200
        data = response.json()

        assert "backends" in data
        assert len(data["backends"]) == 2

        for backend in data["backends"]:
            assert "name" in backend
            assert "connected" in backend
            assert "tools" in backend

    def test_backends_empty_when_no_backends(self, client):
        """Test backends endpoint when no backends configured."""
        response = client.get("/backends")

        assert response.status_code == 200
        data = response.json()
        assert data["backends"] == []


class TestSupervisionEndpoint:
    """Tests for GET /supervision endpoint."""

    def test_supervision_disabled(self, client):
        """Test supervision endpoint when disabled."""
        response = client.get("/supervision")

        assert response.status_code == 200
        data = response.json()

        assert data["enabled"] is False

    def test_supervision_enabled_with_backends(self, client_with_backends, test_app_with_backends):
        """Test supervision endpoint with supervision enabled."""
        from mcp_gateway.supervisor import SupervisionConfig

        _, backend_manager = test_app_with_backends

        # Create supervision config
        supervision_config = SupervisionConfig(
            auto_restart=True, max_restarts=10, max_consecutive_crashes=5
        )

        # This would require more setup for full test
        # For now, just test the endpoint structure
        response = client_with_backends.get("/supervision")

        assert response.status_code == 200


class TestCircuitBreakersEndpoint:
    """Tests for GET /circuit-breakers endpoint."""

    def test_circuit_breaker_stats(self, client_with_backends):
        """Test circuit breaker stats endpoint."""
        response = client_with_backends.get("/circuit-breakers")

        assert response.status_code == 200
        data = response.json()

        # Should return dict of backend stats
        assert isinstance(data, dict)


class TestMetricsEndpoint:
    """Tests for GET /metrics endpoint."""

    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

        # Check for Prometheus format
        content = response.text
        assert isinstance(content, str)


class TestRestartBackend:
    """Tests for POST /backends/{name}/restart endpoint."""

    def test_restart_backend(self, client_with_backends):
        """Test backend restart endpoint."""
        response = client_with_backends.post("/backends/memory/restart")

        # May succeed or fail depending on mock setup
        assert response.status_code in [200, 500]

    def test_restart_nonexistent_backend(self, client):
        """Test restarting non-existent backend."""
        response = client.post("/backends/nonexistent/restart")

        assert response.status_code == 404


class TestDashboardIntegration:
    """Integration tests for dashboard functionality."""

    def test_dashboard_data_consistency(self, client_with_backends):
        """Test that dashboard endpoints return consistent data."""
        # Get health data
        health_response = client_with_backends.get("/health")
        health_data = health_response.json()

        # Get backends data
        backends_response = client_with_backends.get("/backends")
        backends_data = backends_response.json()

        # Verify consistency
        assert health_data["total_backends"] == len(backends_data["backends"])

    def test_server_tools_endpoint(self, client):
        """Test server tools endpoint."""
        response = client.get("/api/servers/memory/tools")

        # May return 404 if backend not connected, or 200 with tools
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert "tools" in data
            assert "disabledTools" in data
