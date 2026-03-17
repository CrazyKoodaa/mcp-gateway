"""Shared fixtures for integration tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from mcp_gateway.admin import ConfigManager
from mcp_gateway.config import load_config
from mcp_gateway.server import McpGatewayServer, ServerDependencies


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config = {
        "gateway": {
            "host": "127.0.0.1",
            "port": 3000,
            "logLevel": "INFO",
            "enableNamespacing": True,
            "namespaceSeparator": "__",
        },
        "mcpServers": {
            "memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
            "time": {
                "command": "uvx",
                "args": ["mcp-server-time"],
                "disabledTools": ["convert_time"],
            },
        },
    }
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f)
    return config_path


@pytest.fixture
def mock_backend_manager():
    """Create a mock backend manager."""
    manager = MagicMock()
    manager.backends = {}
    manager.get_all_tools = MagicMock(return_value=[])
    manager.connect_all = MagicMock()
    manager.disconnect_all = MagicMock()
    return manager


@pytest.fixture
def test_app(temp_config_file, mock_backend_manager):
    """Create a test FastAPI app with mocked dependencies."""
    config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, config)

    deps = ServerDependencies(
        config=config,
        backend_manager=mock_backend_manager,
        config_manager=config_manager,
    )

    server = McpGatewayServer(dependencies=deps)
    app = server.create_app(enable_access_control=False)

    return app, config_manager, mock_backend_manager, temp_config_file


@pytest.fixture
def client(test_app):
    """Create a test client."""
    from fastapi.testclient import TestClient

    app, _, _, _ = test_app
    return TestClient(app)
