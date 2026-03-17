"""Test fixtures and utilities for MCP Gateway tests."""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from mcp_gateway.config import GatewayConfig, ServerConfig


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_config_dict():
    """Return a sample configuration dictionary."""
    return {
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
            "remote-server": {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer token123"},
            },
        },
    }


@pytest.fixture
def sample_config_file(temp_dir, sample_config_dict):
    """Create a sample config file and return its path."""
    config_path = temp_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(sample_config_dict, f)
    return config_path


@pytest.fixture
def gateway_config():
    """Return a GatewayConfig instance."""
    config = GatewayConfig(
        host="127.0.0.1",
        port=3000,
        enable_namespacing=True,
        namespace_separator="__",
        log_level="INFO",
    )
    config.mcp_servers = {
        "memory": ServerConfig(
            name="memory", command="npx", args=["-y", "@modelcontextprotocol/server-memory"]
        ),
        "time": ServerConfig(
            name="time", command="uvx", args=["mcp-server-time"], disabled_tools=["convert_time"]
        ),
    }
    return config


@pytest.fixture
def mock_tool():
    """Return a mock Tool instance."""
    return Tool(
        name="test_tool",
        description="A test tool",
        inputSchema={"type": "object", "properties": {}},
    )


@pytest.fixture
def mock_tool_result():
    """Return a mock CallToolResult."""
    return CallToolResult(content=[TextContent(type="text", text="Test result")], isError=False)


@pytest.fixture
def mock_client_session():
    """Return a mock ClientSession."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
    session.call_tool = AsyncMock()
    return session


class MockBackendConnection:
    """Mock BackendConnection for testing."""

    def __init__(self, name: str, tools: list | None = None, connected: bool = True):
        self.config = MagicMock()
        self.config.name = name
        self.config.transport_type = "stdio"
        self._name = name
        self._tools = tools or []
        self._connected = connected
        self.session = AsyncMock() if connected else None

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list:
        return self._tools.copy()

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._tools = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Result from {self.name}.{tool_name}")],
            isError=False,
        )


@pytest.fixture
def mock_backend():
    """Return a MockBackendConnection factory."""

    def _create(name: str, tools: list | None = None, connected: bool = True):
        return MockBackendConnection(name, tools, connected)

    return _create


@pytest.fixture
def mock_backend_manager():
    """Return a mock BackendManager."""
    manager = MagicMock()
    manager.backends = {}
    manager.get_all_tools = MagicMock(return_value=[])
    return manager


@pytest.fixture(scope="session")
def event_loop_policy():
    """Return the event loop policy for the test session."""
    return asyncio.get_event_loop_policy()
