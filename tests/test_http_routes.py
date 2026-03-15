"""Tests for mcp_gateway.server.http_routes module."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.config import GatewayConfig, ServerConfig
from mcp_gateway.server.http_routes import setup_http_routes
from mcp_gateway.services.config_approval_service import ConfigChangeGrant, PendingRequestInfo
from mcp_gateway.server.state import ServerDependencies


class MockTool:
    """Mock tool for testing."""
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


class MockBackend:
    """Mock backend connection for testing."""
    def __init__(self, name: str, connected: bool = True, tools: list | None = None):
        self.name = name
        self._connected = connected
        self._tools = tools or []
        self.config = MagicMock()
        self.config.is_stdio = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self):
        return self._tools


@pytest.fixture
def mock_dependencies(tmp_path):
    """Create mock server dependencies."""
    config = GatewayConfig(
        host="127.0.0.1",
        port=3000,
        log_level="INFO",
        mcp_servers={
            "memory": ServerConfig(
                name="memory",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-memory"]
            ),
            "time": ServerConfig(
                name="time",
                command="uvx",
                args=["mcp-server-time"],
                disabled_tools=["convert_time"]
            )
        }
    )

    # Mock BackendManager
    backend_manager = MagicMock()
    backend_manager.backends = {
        "memory": MockBackend("memory", connected=True, tools=[
            MockTool("add_memory", "Add a memory"),
            MockTool("get_memory", "Get memories")
        ]),
        "time": MockBackend("time", connected=True, tools=[
            MockTool("get_current_time", "Get current time")
        ])
    }
    backend_manager.get_all_tools = MagicMock(return_value=[])
    backend_manager.restart_backend = AsyncMock()

    # Mock ConfigManager
    config_manager = MagicMock()
    config_manager.gateway_config = config
    config_manager.reload = AsyncMock(return_value=config)
    config_manager.save = AsyncMock()
    config_manager.add_server = AsyncMock()
    config_manager.update_server = AsyncMock()
    config_manager.remove_server = AsyncMock()

    # Mock MetricsCollector
    metrics = MagicMock()
    metrics.generate_metrics = MagicMock(return_value="# HELP test metric\n# TYPE test gauge\ntest 1.0")

    # Mock CircuitBreakerRegistry
    circuit_breaker_registry = MagicMock()
    circuit_breaker_registry.get = MagicMock(return_value=MagicMock(
        get_stats=MagicMock(return_value={
            "name": "memory",
            "state": "CLOSED",
            "failure_count": 0,
            "success_count": 0,
            "last_failure_time": None,
            "retry_after": 0.0,
        })
    ))
    circuit_breaker_registry.get_all_stats = MagicMock(return_value={
        "memory": {
            "name": "memory",
            "state": "CLOSED",
            "failure_count": 0,
            "success_count": 0,
            "last_failure_time": None,
            "retry_after": 0.0,
        },
        "time": {
            "name": "time",
            "state": "OPEN",
            "failure_count": 5,
            "success_count": 0,
            "last_failure_time": 1234567890.0,
            "retry_after": 30.0,
        }
    })

    # Mock Supervisor
    supervisor = MagicMock()
    supervisor.get_stats = MagicMock(return_value={
        "memory": {"restarts": 2, "last_restart": "2024-01-01T00:00:00"},
        "time": {"restarts": 0}
    })
    supervisor.restart_backend = AsyncMock(return_value=True)

    # Mock AccessControl
    access_control = MagicMock()
    access_control.get_pending_requests = MagicMock(return_value=[])
    access_control.get_active_grants = MagicMock(return_value=[])
    access_control.get_active_config_grants = MagicMock(return_value=[])
    access_control.approve_request = AsyncMock(return_value=(True, "Approved", None))
    access_control.deny_request = AsyncMock(return_value=(True, "Denied"))
    access_control.revoke_grant = AsyncMock(return_value=True)
    access_control.deny_config_change = AsyncMock(return_value=(True, "Denied"))
    access_control.revoke_config_grant = AsyncMock(return_value=(True, "Revoked"))
    access_control.register_notification_callback = MagicMock()

    # Mock ConfigApprovalService
    config_approval = MagicMock()
    config_approval.get_pending_requests = MagicMock(return_value=[])
    config_approval.check_config_change = AsyncMock(return_value=MagicMock(
        requires_approval=False,
        error=None,
        safe_paths=[],
        pending_requests=[]
    ))
    config_approval.approve = AsyncMock(return_value=(True, "Approved", None))

    # Mock RateLimiter
    rate_limiter = MagicMock()
    rate_limiter.check = AsyncMock(return_value=MagicMock(allowed=True))

    # Mock Templates - return real HTMLResponse instead of MagicMock
    from fastapi.responses import HTMLResponse
    
    templates = MagicMock()
    def template_response(name, context):
        content = f"<!DOCTYPE html><html><head><title>Test</title></head><body>{name}</body></html>"
        return HTMLResponse(content=content)
    templates.TemplateResponse = template_response

    deps = ServerDependencies(
        config=config,
        backend_manager=backend_manager,
        config_manager=config_manager,
        supervisor=supervisor,
        audit_service=MagicMock(),
        path_security=MagicMock(),
        access_control=access_control,
        config_approval=config_approval,
        rate_limiter=rate_limiter,
        circuit_breaker_registry=circuit_breaker_registry,
        metrics=metrics,
        auth=None,
        templates=templates,
    )

    return deps


@pytest.fixture
def client(mock_dependencies):
    """Create a FastAPI test client."""
    from fastapi import FastAPI
    
    app = FastAPI()
    setup_http_routes(app, mock_dependencies, enable_access_control=True)
    
    return TestClient(app)


class TestHealthRoutes:
    """Tests for health and monitoring routes."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["healthy"] is True
        assert data["total_backends"] == 2
        assert data["connected_backends"] == 2
        assert len(data["backends"]) == 2
        
        # Check backend data structure
        backend = data["backends"][0]
        assert "name" in backend
        assert "connected" in backend
        assert "tools" in backend
        assert "type" in backend
        assert "circuit_breaker_state" in backend

    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        
        assert response.status_code == 200
        assert "test metric" in response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

    def test_circuit_breaker_stats(self, client):
        """Test circuit breaker statistics endpoint."""
        response = client.get("/circuit-breakers")
        
        assert response.status_code == 200
        data = response.json()
        assert "memory" in data
        assert "time" in data
        assert data["memory"]["state"] == "CLOSED"
        assert data["time"]["state"] == "OPEN"


class TestDashboardRoutes:
    """Tests for dashboard HTML routes."""

    def test_main_dashboard(self, client):
        """Test main dashboard page."""
        response = client.get("/")
        
        assert response.status_code == 200
        assert "dashboard.html" in response.text
        assert response.headers["content-type"] == "text/html; charset=utf-8"

    def test_admin_dashboard(self, client):
        """Test admin dashboard page."""
        response = client.get("/admin")
        
        assert response.status_code == 200
        assert "admin.html" in response.text

    def test_blue_box_dashboard(self, client):
        """Test blue box themed dashboard."""
        response = client.get("/blue-box")
        
        assert response.status_code == 200
        assert "blue-box.html" in response.text

    def test_retro_dashboard(self, client):
        """Test retro themed dashboard."""
        response = client.get("/retro")
        
        assert response.status_code == 200
        assert "retro-dashboard.html" in response.text

    def test_retro_admin(self, client):
        """Test retro themed admin panel."""
        response = client.get("/retro-admin")
        
        assert response.status_code == 200
        assert "retro-admin.html" in response.text

    def test_dashboard_no_templates(self, client, mock_dependencies):
        """Test dashboard when templates are not available."""
        mock_dependencies.templates = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=True)
        test_client = TestClient(app)
        
        response = test_client.get("/")
        
        assert response.status_code == 500
        assert "Templates not available" in response.json()["detail"]


class TestServerRoutes:
    """Tests for server management routes."""

    def test_list_servers(self, client):
        """Test listing all configured servers."""
        response = client.get("/api/servers")
        
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        assert len(data["servers"]) == 2
        
        # Check server data structure
        server = data["servers"][0]
        assert "name" in server
        assert "command" in server
        assert "args" in server
        assert "availableTools" in server
        assert "disabledTools" in server

    def test_get_server_tools(self, client):
        """Test getting tools for a specific server."""
        response = client.get("/api/servers/memory/tools")
        
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "disabledTools" in data
        assert len(data["tools"]) == 2

    def test_get_server_tools_not_found(self, client):
        """Test getting tools for non-existent server."""
        response = client.get("/api/servers/nonexistent/tools")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_server(self, client, mock_dependencies):
        """Test creating a new server."""
        mock_dependencies.config_manager.add_server = AsyncMock(
            return_value=ServerConfig(name="new-server", command="test")
        )
        
        payload = {
            "name": "new-server",
            "config": {
                "command": "npx",
                "args": ["-y", "new-package"]
            }
        }
        response = client.post("/api/servers", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server"]["name"] == "new-server"

    def test_create_server_missing_name(self, client):
        """Test creating server without name."""
        payload = {
            "config": {"command": "npx"}
        }
        response = client.post("/api/servers", json=payload)
        
        assert response.status_code == 400
        assert "name is required" in response.json()["detail"].lower()

    def test_create_server_invalid_config(self, client):
        """Test creating server with invalid config."""
        payload = {
            "name": "invalid",
            "config": {"env": {}}  # Missing command or url
        }
        response = client.post("/api/servers", json=payload)
        
        assert response.status_code == 400

    def test_create_server_already_exists(self, client, mock_dependencies):
        """Test creating server that already exists."""
        payload = {
            "name": "memory",
            "config": {"command": "npx"}
        }
        response = client.post("/api/servers", json=payload)
        
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_update_server(self, client, mock_dependencies):
        """Test updating an existing server."""
        mock_dependencies.config_manager.update_server = AsyncMock(
            return_value=ServerConfig(name="memory", command="updated")
        )
        
        payload = {
            "command": "uvx",
            "args": ["updated-package"]
        }
        response = client.put("/api/servers/memory", json=payload)
        
        assert response.status_code == 200

    def test_update_server_not_found(self, client, mock_dependencies):
        """Test updating non-existent server."""
        mock_dependencies.config_manager.update_server = AsyncMock(
            side_effect=ValueError("Server 'nonexistent' not found")
        )
        
        payload = {"command": "npx"}
        response = client.put("/api/servers/nonexistent", json=payload)
        
        assert response.status_code == 404

    def test_update_server_requires_approval(self, client, mock_dependencies):
        """Test update that requires config approval."""
        from mcp_gateway.services.config_approval_service import PendingRequestInfo
        
        mock_dependencies.config_approval.check_config_change = AsyncMock(
            return_value=MagicMock(
                requires_approval=True,
                error=None,
                safe_paths=[],
                pending_requests=[
                    PendingRequestInfo(
                        code="ABC123",
                        path="/sensitive/path",
                    )
                ]
            )
        )
        
        payload = {
            "command": "npx",
            "args": ["-y", "new-package", "/sensitive/path"]
        }
        response = client.put("/api/servers/memory", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["requires_approval"] is True
        assert data["approval_code"] == "ABC123"
        assert len(data["pending_requests"]) == 1

    def test_delete_server(self, client, mock_dependencies):
        """Test deleting a server."""
        mock_dependencies.config_manager.remove_server = AsyncMock()
        
        response = client.delete("/api/servers/time")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "time" in data["message"]

    def test_delete_server_not_found(self, client, mock_dependencies):
        """Test deleting non-existent server."""
        mock_dependencies.config_manager.remove_server = AsyncMock(
            side_effect=ValueError("Server 'nonexistent' not found")
        )
        
        response = client.delete("/api/servers/nonexistent")
        
        assert response.status_code == 404

    def test_reload_config(self, client, mock_dependencies):
        """Test reloading configuration."""
        response = client.post("/api/reload")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_dependencies.config_manager.reload.assert_called_once()

    def test_list_backends(self, client):
        """Test listing all backends."""
        response = client.get("/backends")
        
        assert response.status_code == 200
        data = response.json()
        assert "backends" in data
        assert len(data["backends"]) == 2

    def test_get_supervision(self, client, mock_dependencies):
        """Test getting supervision status."""
        response = client.get("/supervision")
        
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert "backends" in data

    def test_get_supervision_disabled(self, client, mock_dependencies):
        """Test supervision status when disabled."""
        mock_dependencies.supervisor = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=True)
        test_client = TestClient(app)
        
        response = test_client.get("/supervision")
        
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    def test_restart_backend_with_supervisor(self, client, mock_dependencies):
        """Test restarting backend with supervisor."""
        response = client.post("/backends/memory/restart")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_dependencies.supervisor.restart_backend.assert_called_once_with("memory")

    def test_restart_backend_without_supervisor(self, client, mock_dependencies):
        """Test restarting backend without supervisor."""
        mock_dependencies.supervisor = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=True)
        test_client = TestClient(app)
        
        response = test_client.post("/backends/memory/restart")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_restart_backend_not_found(self, client, mock_dependencies):
        """Test restarting non-existent backend via supervisor."""
        # When supervisor exists but fails, it returns 500 (not 404)
        mock_dependencies.supervisor.restart_backend = AsyncMock(return_value=False)
        
        response = client.post("/backends/nonexistent/restart")
        
        assert response.status_code == 500

    def test_restart_backend_failure(self, client, mock_dependencies):
        """Test backend restart failure."""
        mock_dependencies.supervisor.restart_backend = AsyncMock(return_value=False)
        
        response = client.post("/backends/memory/restart")
        
        assert response.status_code == 500


class TestAccessControlRoutes:
    """Tests for access control routes."""

    def test_list_pending_access_requests(self, client):
        """Test listing pending access requests."""
        response = client.get("/api/access/requests/pending")
        
        assert response.status_code == 200
        data = response.json()
        assert "requests" in data

    def test_list_active_access_grants(self, client):
        """Test listing active access grants."""
        response = client.get("/api/access/grants/active")
        
        assert response.status_code == 200
        data = response.json()
        assert "grants" in data

    def test_approve_access_request(self, client, mock_dependencies):
        """Test approving an access request."""
        mock_dependencies.access_control.approve_request = AsyncMock(return_value=(
            True, "Approved successfully", MagicMock(
                id="grant-1",
                mcp_name="test-mcp",
                path="/test/path",
                expires_at=datetime.now() + timedelta(minutes=30),
                duration_minutes=30
            )
        ))
        
        payload = {"duration_minutes": 30}
        response = client.post("/api/access/requests/ABC123/approve", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_deny_access_request(self, client, mock_dependencies):
        """Test denying an access request."""
        mock_dependencies.access_control.deny_request = AsyncMock(
            return_value=(True, "Request denied")
        )
        
        response = client.post("/api/access/requests/ABC123/deny")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_revoke_access_grant(self, client, mock_dependencies):
        """Test revoking an access grant."""
        response = client.delete("/api/access/grants/grant-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_revoke_access_grant_not_found(self, client, mock_dependencies):
        """Test revoking non-existent grant."""
        mock_dependencies.access_control.revoke_grant = AsyncMock(return_value=False)
        
        response = client.delete("/api/access/grants/nonexistent")
        
        assert response.status_code == 404


class TestConfigApprovalRoutes:
    """Tests for config approval routes."""

    def test_list_pending_config_changes(self, client):
        """Test listing pending config changes."""
        response = client.get("/api/config-changes/pending")
        
        assert response.status_code == 200
        data = response.json()
        assert "requests" in data

    def test_list_config_change_grants(self, client):
        """Test listing active config change grants."""
        response = client.get("/api/config-changes/grants")
        
        assert response.status_code == 200
        data = response.json()
        assert "grants" in data

    def test_approve_config_change(self, client, mock_dependencies):
        """Test approving a config change."""
        from mcp_gateway.services.config_approval_service import ConfigChangeGrant
        
        mock_dependencies.config_approval.approve = AsyncMock(return_value=(
            True, "Approved", ConfigChangeGrant(
                id="grant-1",
                request_id="req-1",
                server_name="memory",
                sensitive_path="/path",
                path_index=0,
                target_args=["-y", "package"],
                original_args=["-y", "old-package"],
                granted_at=datetime.now(),
                expires_at=datetime.now() + timedelta(minutes=30),
                duration_minutes=30,
                approved_by="web"
            )
        ))
        
        payload = {"duration_minutes": 30, "approved_by": "admin"}
        response = client.post("/api/config-changes/ABC123/approve", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_approve_config_change_rate_limited(self, client, mock_dependencies):
        """Test config change approval with rate limit."""
        mock_dependencies.rate_limiter.check = AsyncMock(return_value=MagicMock(
            allowed=False,
            retry_after=60.0
        ))
        
        payload = {"duration_minutes": 30}
        response = client.post("/api/config-changes/ABC123/approve", json=payload)
        
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()

    def test_deny_config_change(self, client, mock_dependencies):
        """Test denying a config change."""
        mock_dependencies.access_control.deny_config_change = AsyncMock(
            return_value=(True, "Request denied")
        )
        
        response = client.post("/api/config-changes/ABC123/deny")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_revoke_config_change_grant(self, client, mock_dependencies):
        """Test revoking a config change grant."""
        response = client.delete("/api/config-changes/grants/grant-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_revoke_config_change_grant_not_found(self, client, mock_dependencies):
        """Test revoking non-existent config change grant."""
        mock_dependencies.access_control.revoke_config_grant = AsyncMock(
            return_value=(False, "Grant not found")
        )
        
        response = client.delete("/api/config-changes/grants/nonexistent")
        
        assert response.status_code == 404


class TestAccessEventsSSE:
    """Tests for SSE events endpoint."""

    def test_access_events_sse(self, client):
        """Test SSE events endpoint returns streaming response."""
        response = client.get("/api/access/events")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"


class TestNoConfigManager:
    """Tests when config manager is not available."""

    def test_list_servers_no_config_manager(self, client, mock_dependencies):
        """Test listing servers when config manager is None."""
        mock_dependencies.config_manager = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=True)
        test_client = TestClient(app)
        
        response = test_client.get("/api/servers")
        
        assert response.status_code == 503
        assert "config management not available" in response.json()["detail"].lower()

    def test_create_server_no_config_manager(self, client, mock_dependencies):
        """Test creating server when config manager is None."""
        mock_dependencies.config_manager = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=True)
        test_client = TestClient(app)
        
        payload = {"name": "test", "config": {"command": "npx"}}
        response = test_client.post("/api/servers", json=payload)
        
        assert response.status_code == 503


class TestNoAccessControl:
    """Tests when access control is disabled."""

    def test_list_pending_requests_no_access_control(self, client, mock_dependencies):
        """Test listing requests when access control is None."""
        mock_dependencies.access_control = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=False)
        test_client = TestClient(app)
        
        response = test_client.get("/api/access/requests/pending")
        
        # Should still work but return empty list
        assert response.status_code == 200
        assert response.json()["requests"] == []

    def test_approve_request_no_access_control(self, client, mock_dependencies):
        """Test approving request when access control is None."""
        mock_dependencies.access_control = None
        
        from fastapi import FastAPI
        app = FastAPI()
        setup_http_routes(app, mock_dependencies, enable_access_control=False)
        test_client = TestClient(app)
        
        response = test_client.post("/api/access/requests/ABC123/approve")
        
        assert response.status_code == 503
        assert "access control service not available" in response.json()["detail"].lower()
