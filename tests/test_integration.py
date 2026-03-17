"""Integration tests for MCP Gateway."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcp_gateway.config import GatewayConfig, ServerConfig, load_config


class TestConfigLoadingIntegration:
    """Integration tests for configuration loading."""

    def test_full_config_workflow(self):
        """Test complete config loading workflow."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"

            # Create a comprehensive config
            config_data = {
                "gateway": {
                    "host": "0.0.0.0",
                    "port": 8080,
                    "logLevel": "DEBUG",
                    "enableNamespacing": False,
                    "namespaceSeparator": "::",
                    "apiKey": "test-key",
                    "bearerToken": "test-token",
                    "connectionTimeout": 10.0,
                    "requestTimeout": 30.0,
                },
                "mcpServers": {
                    "stdio-server": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-memory"],
                        "env": {"CUSTOM_VAR": "value"},
                        "disabledTools": ["delete_memory"],
                    },
                    "remote-http": {
                        "type": "streamable-http",
                        "url": "https://api.example.com/mcp",
                        "headers": {
                            "Authorization": "Bearer secret-token",
                            "X-Custom-Header": "custom-value",
                        },
                    },
                    "remote-sse": {"type": "sse", "url": "http://localhost:3001/sse"},
                },
            }

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Load and verify
            config = load_config(config_path)

            # Verify gateway settings
            assert config.host == "0.0.0.0"
            assert config.port == 8080
            assert config.log_level == "DEBUG"
            assert config.enable_namespacing is False
            assert config.namespace_separator == "::"
            assert config.api_key == "test-key"
            assert config.bearer_token == "test-token"
            assert config.connection_timeout == 10.0
            assert config.request_timeout == 30.0

            # Verify stdio server
            stdio = config.servers["stdio-server"]
            assert stdio.command == "npx"
            assert stdio.args == ["-y", "@modelcontextprotocol/server-memory"]
            assert stdio.env == {"CUSTOM_VAR": "value"}
            assert stdio.disabled_tools == ["delete_memory"]
            assert stdio.is_stdio is True

            # Verify remote HTTP server
            http = config.servers["remote-http"]
            assert http.url == "https://api.example.com/mcp"
            assert http.type == "streamable-http"
            assert http.headers == {
                "Authorization": "Bearer secret-token",
                "X-Custom-Header": "custom-value",
            }
            assert http.is_remote is True

            # Verify remote SSE server
            sse = config.servers["remote-sse"]
            assert sse.url == "http://localhost:3001/sse"
            assert sse.type == "sse"


class TestServerConfigurationIntegration:
    """Integration tests for server configuration."""

    def test_server_config_to_backend_integration(self):
        """Test that server config properly configures backend connections."""
        from mcp_gateway.backends import BackendConnection

        config = ServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "test-package"],
            env={"KEY": "value"},
            disabled_tools=["disabled1"],
        )

        # Note: BackendConnection uses __slots__, so we test it directly
        backend = BackendConnection(config)
        # Verify the backend was created with the config
        assert backend.config == config
        assert backend.name == "test-server"
        assert backend.is_connected is False

    def test_gateway_config_to_server_integration(self):
        """Test that gateway config properly configures the server."""
        from mcp_gateway.server import McpGatewayServer, ServerDependencies

        config = GatewayConfig(
            host="127.0.0.1",
            port=3000,
            log_level="INFO",
            api_key="test-key",
            bearer_token="test-token",
        )

        backend_manager = MagicMock()
        backend_manager.backends = {}
        backend_manager.get_all_tools.return_value = []

        deps = ServerDependencies(
            config=config,
            backend_manager=backend_manager,
            config_manager=MagicMock(),
        )
        server = McpGatewayServer(dependencies=deps)
        server.create_app(enable_access_control=False)

        assert server.deps.config == config
        assert server.deps.backend_manager == backend_manager
        assert server.app is not None


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.mark.asyncio
    async def test_complete_server_workflow(self):
        """Test a complete server workflow from config to request handling."""
        from mcp.types import Tool

        from mcp_gateway.backends import BackendManager
        from mcp_gateway.server import McpGatewayServer, ServerDependencies

        # Create config
        config = GatewayConfig(host="127.0.0.1", port=3000, log_level="INFO")

        # Create backend manager
        backend_manager = BackendManager()

        # Mock backends
        mock_backend1 = MagicMock()
        mock_backend1.name = "backend1"
        mock_backend1.is_connected = True
        mock_backend1.tools = [Tool(name="tool1", description="Tool 1", inputSchema={})]

        backend_manager._backends = {"backend1": mock_backend1}
        backend_manager._tool_map = {"backend1__tool1": "backend1"}

        # Create server
        deps = ServerDependencies(
            config=config,
            backend_manager=backend_manager,
            config_manager=MagicMock(),
        )
        server = McpGatewayServer(dependencies=deps)
        server.create_app(enable_access_control=False)

        # Verify server was created correctly
        assert server.deps.config == config
        assert server.deps.backend_manager == backend_manager
        assert server.app is not None

    def test_tool_routing_workflow(self):
        """Test the complete tool routing workflow."""
        from mcp.types import Tool

        from mcp_gateway.backends import BackendManager

        manager = BackendManager()

        # Setup mock backends
        backend1 = MagicMock()
        backend1.name = "memory"
        backend1.is_connected = True
        backend1.tools = [Tool(name="add", description="Add memory", inputSchema={})]

        backend2 = MagicMock()
        backend2.name = "time"
        backend2.is_connected = True
        backend2.tools = [Tool(name="get", description="Get time", inputSchema={})]

        manager._backends = {"memory": backend1, "time": backend2}
        manager._tool_map = {"memory__add": "memory", "time__get": "time"}

        # Test tool lookup
        assert manager.get_backend_for_tool("memory__add") == backend1
        assert manager.get_backend_for_tool("time__get") == backend2
        assert manager.get_backend_for_tool("unknown__tool") is None

        # Test name extraction
        backend, tool = manager.extract_original_tool_name("memory__add")
        assert backend == "memory"
        assert tool == "add"

    def test_custom_namespace_separator_workflow(self):
        """Test workflow with custom namespace separator."""
        from mcp_gateway.backends import BackendManager

        manager = BackendManager(namespace_separator="::")

        backend1 = MagicMock()
        backend1.name = "backend1"
        backend1.is_connected = True

        manager._backends = {"backend1": backend1}
        manager._tool_map = {"backend1::tool1": "backend1"}

        # Test tool lookup with custom separator
        assert manager.get_backend_for_tool("backend1::tool1") == backend1

        # Test name extraction with custom separator
        backend, tool = manager.extract_original_tool_name("backend1::tool1")
        assert backend == "backend1"
        assert tool == "tool1"


class TestErrorHandlingIntegration:
    """Integration tests for error handling."""

    def test_config_loading_error_handling(self):
        """Test error handling during config loading."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "invalid.json"

            # Write invalid JSON
            with open(config_path, "w") as f:
                f.write("{not valid json}")

            with pytest.raises(json.JSONDecodeError):
                load_config(config_path)

    def test_missing_required_fields(self):
        """Test handling of missing required fields in config."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "incomplete.json"

            # Config with missing fields should still load with defaults
            config_data = {"gateway": {}, "mcpServers": {}}

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            # Should use defaults
            assert config.host == "127.0.0.1"
            assert config.port == 3000
            assert len(config.servers) == 0
            assert config.api_key is None
            assert config.connection_timeout == 30.0


class TestConfigurationVariations:
    """Tests for various configuration scenarios."""

    def test_empty_servers_config(self):
        """Test configuration with empty servers list."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "empty.json"

            config_data = {"gateway": {"port": 5000}, "mcpServers": {}}

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            assert len(config.servers) == 0
            assert config.port == 5000

    def test_config_with_only_stdio_servers(self):
        """Test configuration with only stdio servers."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "stdio_only.json"

            config_data = {
                "mcpServers": {
                    "server1": {"command": "npx", "args": ["pkg1"]},
                    "server2": {"command": "uvx", "args": ["pkg2"]},
                }
            }

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            assert len(config.servers) == 2
            assert all(s.is_stdio for s in config.servers.values())

    def test_config_with_only_remote_servers(self):
        """Test configuration with only remote servers."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "remote_only.json"

            config_data = {
                "mcpServers": {
                    "api1": {"type": "streamable-http", "url": "https://api1.com/mcp"},
                    "api2": {"type": "sse", "url": "http://api2.com/sse"},
                }
            }

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            assert len(config.servers) == 2
            assert all(s.is_remote for s in config.servers.values())

    def test_mixed_server_types(self):
        """Test configuration with mixed server types."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "mixed.json"

            config_data = {
                "mcpServers": {
                    "local": {"command": "npx", "args": ["local-pkg"]},
                    "remote": {"type": "streamable-http", "url": "https://remote.com/mcp"},
                }
            }

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            assert config.servers["local"].is_stdio is True
            assert config.servers["remote"].is_remote is True

    def test_full_authentication_config(self):
        """Test configuration with full authentication setup."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "auth_full.json"

            config_data = {
                "gateway": {
                    "apiKey": "secret-api-key-123",
                    "bearerToken": "secret-bearer-token-456",
                    "authExcludePaths": ["/health", "/metrics", "/docs"],
                },
                "mcpServers": {"test": {"command": "npx", "args": ["test"]}},
            }

            with open(config_path, "w") as f:
                json.dump(config_data, f)

            config = load_config(config_path)

            assert config.api_key == "secret-api-key-123"
            assert config.bearer_token == "secret-bearer-token-456"
            assert config.auth_exclude_paths == ["/health", "/metrics", "/docs"]
