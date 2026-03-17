"""
E2E Test Fixtures - MCP Gateway Dashboard
All services requiring async operations are properly mocked with AsyncMock
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.config import GatewayConfig, ServerConfig
from mcp_gateway.server import McpGatewayServer, ServerDependencies


class MockAuditService:
    """Mock audit service with async operations"""

    def __init__(self):
        self._started = False

    async def start(self):
        """Start audit service"""
        await asyncio.sleep(0)
        self._started = True

    async def stop(self):
        """Stop audit service"""
        await asyncio.sleep(0)
        self._started = False

    async def log_event(self, event_type: str, data: dict):
        """Log an audit event"""
        return True


class MockPathSecurity:
    """Mock path security service"""

    def __init__(self):
        self._started = False

    async def start(self):
        """Start path security service"""
        await asyncio.sleep(0)
        self._started = True

    async def stop(self):
        """Stop path security service"""
        await asyncio.sleep(0)
        self._started = False

    def check_path(self, path: str) -> dict:
        """Check if path is sensitive"""
        return {"path": path, "is_sensitive": False, "matched_pattern": None}


class MockAccessControl:
    """Mock access control service"""

    def __init__(self):
        self._started = False

    async def start(self):
        """Start access control service"""
        await asyncio.sleep(0)
        self._started = True

    async def stop(self):
        """Stop access control service"""
        await asyncio.sleep(0)
        self._started = False

    def get_pending_requests(self):
        return []

    def get_active_grants(self):
        return []

    def get_active_config_grants(self):
        return []


@pytest.fixture
def gateway_config() -> GatewayConfig:
    """Create test gateway configuration."""
    return GatewayConfig(
        host="127.0.0.1",
        port=3000,
        log_level="INFO",
    )


@pytest.fixture
def mock_backend_manager():
    """Create mock backend manager."""
    from mcp.types import Tool

    manager = MagicMock()

    # Create mock backends
    backend1 = MagicMock()
    backend1.name = "memory"
    backend1.is_connected = True
    backend1.tools = [
        Tool(name="add", description="Add memory", inputSchema={}),
        Tool(name="get", description="Get memory", inputSchema={}),
    ]

    backend2 = MagicMock()
    backend2.name = "time"
    backend2.is_connected = True
    backend2.tools = [
        Tool(name="get_current_time", description="Get time", inputSchema={}),
    ]

    manager.backends = {"memory": backend1, "time": backend2}
    manager.get_all_tools.return_value = []
    manager.restart_backend = AsyncMock()
    manager.connect_all = AsyncMock()
    manager.disconnect_all = AsyncMock()

    return manager


@pytest.fixture
def mock_config_manager(tmp_path, gateway_config):
    """Create mock config manager."""
    manager = MagicMock()

    # Set up mcp_servers (not servers which is a read-only property)
    gateway_config.mcp_servers = {
        "memory": ServerConfig(
            name="memory",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        ),
        "time": ServerConfig(
            name="time",
            command="uvx",
            args=["mcp-server-time"],
            disabled_tools=["convert_time"],
        ),
    }

    manager.gateway_config = gateway_config
    manager.reload = AsyncMock()
    manager.save = AsyncMock()
    manager.add_server = AsyncMock()
    manager.update_server = AsyncMock()
    manager.remove_server = AsyncMock()
    return manager


@pytest.fixture
def mock_supervisor():
    """Create mock process supervisor with async methods."""
    supervisor = MagicMock()
    supervisor.start = AsyncMock()
    supervisor.stop = AsyncMock()
    supervisor.start_supervision = AsyncMock()
    supervisor.stop_supervision = AsyncMock()
    supervisor.restart_backend = AsyncMock(return_value=True)
    supervisor.get_stats = MagicMock(
        return_value={
            "memory": {"restarts": 0, "last_restart": None},
            "time": {"restarts": 0, "last_restart": None},
        }
    )
    return supervisor


@pytest.fixture
def mock_audit_service():
    """Create mock audit service with async methods."""
    return MockAuditService()


@pytest.fixture
def mock_path_security():
    """Create mock path security service with async methods."""
    return MockPathSecurity()


@pytest.fixture
def mock_access_control():
    """Create mock access control service with async methods."""
    return MockAccessControl()


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter with async methods."""
    rate_limiter = MagicMock()
    rate_limiter.start = AsyncMock()
    rate_limiter.stop = AsyncMock()
    rate_limiter.check = AsyncMock(return_value=MagicMock(allowed=True))
    return rate_limiter


@pytest.fixture
def mock_config_approval():
    """Create mock config approval service with async methods."""
    config_approval = MagicMock()
    config_approval.start = AsyncMock()
    config_approval.stop = AsyncMock()
    config_approval.get_pending_requests = MagicMock(return_value=[])
    config_approval.check_config_change = AsyncMock(
        return_value=MagicMock(
            requires_approval=False, error=None, safe_paths=[], pending_requests=[]
        )
    )
    config_approval.approve = AsyncMock(return_value=(True, "Approved", None))
    return config_approval


@pytest.fixture
def test_client(
    gateway_config,
    mock_backend_manager,
    mock_config_manager,
    mock_supervisor,
    mock_audit_service,
    mock_path_security,
    mock_access_control,
    mock_rate_limiter,
    mock_config_approval,
    tmp_path,
) -> Generator[TestClient, None, None]:
    """Create FastAPI test client with mocked dependencies."""
    from mcp_gateway.circuit_breaker import CircuitBreakerRegistry
    from mcp_gateway.metrics import MetricsCollector

    # Create template directory with test templates
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    templates_content = {
        "dashboard.html": """<!DOCTYPE html>
<html>
<head><title>MCP Gateway Dashboard</title></head>
<body>
    <h1>Dashboard</h1>
    <div class="stats-grid"></div>
    <div class="server-list"></div>
</body>
</html>""",
        "admin.html": """<!DOCTYPE html>
<html>
<head><title>MCP Gateway Admin</title></head>
<body>
    <h1>Admin Panel</h1>
    <nav class="nav"></nav>
    <div class="server-config"></div>
</body>
</html>""",
        "blue-box.html": """<!DOCTYPE html>
<html>
<head><title>Blue Box Dashboard</title></head>
<body class="blue-theme">
    <h1>Blue Box</h1>
    <div class="terminal"></div>
</body>
</html>""",
        "retro-dashboard.html": """<!DOCTYPE html>
<html>
<head><title>Retro Dashboard</title></head>
<body class="retro-theme">
    <h1>Retro 80s Dashboard</h1>
    <div class="crt-effect"></div>
</body>
</html>""",
        "retro-admin.html": """<!DOCTYPE html>
<html>
<head><title>Retro Admin</title></head>
<body class="retro-theme">
    <h1>Retro Admin Panel</h1>
    <div class="crt-effect"></div>
</body>
</html>""",
    }

    for name, content in templates_content.items():
        (template_dir / name).write_text(content)

    # Create Jinja2 templates
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(template_dir))

    # Create dependencies with proper async services
    deps = ServerDependencies(
        config=gateway_config,
        backend_manager=mock_backend_manager,
        config_manager=mock_config_manager,
        supervisor=mock_supervisor,
        audit_service=mock_audit_service,
        path_security=mock_path_security,
        access_control=mock_access_control,
        config_approval=mock_config_approval,
        rate_limiter=mock_rate_limiter,
        circuit_breaker_registry=CircuitBreakerRegistry(),
        metrics=MetricsCollector(),
        auth=None,
        templates=templates,
    )

    # Create server and app
    server = McpGatewayServer(dependencies=deps)
    app = server.create_app(enable_access_control=False)

    with TestClient(app) as client:
        yield client


@pytest.fixture
def xss_payloads() -> list[str]:
    """XSS payloads for security testing."""
    return [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "javascript:alert('XSS')",
        "<svg onload=alert('XSS')>",
        "<body onload=alert('XSS')>",
        "<iframe src='javascript:alert(\"XSS\")'>",
    ]


@pytest.fixture
def html_templates() -> list[str]:
    """List of all HTML templates to test."""
    return [
        "dashboard.html",
        "admin.html",
        "blue-box.html",
        "retro-dashboard.html",
        "retro-admin.html",
    ]
