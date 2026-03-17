"""Tests for mcp_gateway.config module."""

import json

import pytest

from mcp_gateway.config import GatewayConfig, ServerConfig, load_config


class TestServerConfig:
    """Tests for ServerConfig dataclass."""

    def test_stdio_server_defaults(self):
        """Test stdio server configuration with defaults."""
        config = ServerConfig(name="test-server")
        assert config.name == "test-server"
        assert config.command is None
        assert config.args == []
        assert config.env == {}
        assert config.url is None
        assert config.type is None
        assert config.headers == {}
        assert config.disabled_tools == []

    def test_stdio_server_with_command(self):
        """Test stdio server with command specified."""
        config = ServerConfig(
            name="memory",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
            env={"KEY": "value"},
            disabled_tools=["tool1"],
        )
        assert config.is_stdio is True
        assert config.is_remote is False
        assert config.transport_type == "stdio"

    def test_remote_server_streamable_http(self):
        """Test remote server with StreamableHTTP type."""
        config = ServerConfig(
            name="remote",
            url="https://example.com/mcp",
            type="streamable-http",
            headers={"Authorization": "Bearer token"},
        )
        assert config.is_stdio is False
        assert config.is_remote is True
        assert config.transport_type == "streamable-http"

    def test_remote_server_sse(self):
        """Test remote server with SSE type."""
        config = ServerConfig(name="sse-server", url="http://localhost:8001/sse", type="sse")
        assert config.transport_type == "sse"

    def test_transport_type_variations(self):
        """Test transport type parsing with different formats."""
        # Test variations of streamable-http
        for type_val in ["streamablehttp", "streamable-http", "STREAMABLE_HTTP"]:
            config = ServerConfig(name="test", url="http://test", type=type_val)
            assert config.transport_type == "streamable-http"

        # Test SSE variations
        for type_val in ["sse", "SSE", "Sse"]:
            config = ServerConfig(name="test", url="http://test", type=type_val)
            assert config.transport_type == "sse"

    def test_remote_server_default_transport(self):
        """Test that remote servers default to streamable-http."""
        config = ServerConfig(name="remote", url="https://example.com/mcp")
        assert config.transport_type == "streamable-http"


class TestGatewayConfig:
    """Tests for GatewayConfig dataclass."""

    def test_default_values(self):
        """Test GatewayConfig default values."""
        config = GatewayConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 3000
        assert config.enable_namespacing is True
        assert config.namespace_separator == "__"
        assert config.log_level == "INFO"
        assert config.servers == {}
        # New fields
        assert config.api_key is None
        assert config.bearer_token is None
        assert config.auth_exclude_paths == ["/health", "/metrics", "/docs", "/openapi.json"]
        assert config.connection_timeout == 30.0
        assert config.request_timeout == 60.0

    def test_custom_values(self):
        """Test GatewayConfig with custom values."""
        config = GatewayConfig(
            host="0.0.0.0",
            port=8080,
            enable_namespacing=False,
            namespace_separator="::",
            log_level="DEBUG",
            api_key="test-api-key",
            bearer_token="test-bearer-token",
            auth_exclude_paths=["/health"],
            connection_timeout=10.0,
            request_timeout=30.0,
        )
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.enable_namespacing is False
        assert config.namespace_separator == "::"
        assert config.log_level == "DEBUG"
        assert config.api_key == "test-api-key"
        assert config.bearer_token == "test-bearer-token"
        assert config.auth_exclude_paths == ["/health"]
        assert config.connection_timeout == 10.0
        assert config.request_timeout == 30.0


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, sample_config_file, sample_config_dict):
        """Test loading a valid configuration file."""
        config = load_config(sample_config_file)

        assert config.host == "127.0.0.1"
        assert config.port == 3000
        assert config.log_level == "INFO"
        assert config.enable_namespacing is True
        assert config.namespace_separator == "__"
        assert len(config.servers) == 3

    def test_load_stdio_server_config(self, sample_config_file):
        """Test loading stdio server configuration."""
        config = load_config(sample_config_file)

        memory = config.servers["memory"]
        assert memory.name == "memory"
        assert memory.command == "npx"
        assert memory.args == ["-y", "@modelcontextprotocol/server-memory"]
        assert memory.is_stdio is True

    def test_load_stdio_with_disabled_tools(self, sample_config_file):
        """Test loading stdio server with disabled tools."""
        config = load_config(sample_config_file)

        time_server = config.servers["time"]
        assert time_server.name == "time"
        assert time_server.command == "uvx"
        assert time_server.disabled_tools == ["convert_time"]

    def test_load_remote_server_config(self, sample_config_file):
        """Test loading remote server configuration."""
        config = load_config(sample_config_file)

        remote = config.servers["remote-server"]
        assert remote.name == "remote-server"
        assert remote.url == "https://example.com/mcp"
        assert remote.type == "streamable-http"
        assert remote.headers == {"Authorization": "Bearer token123"}
        assert remote.is_remote is True

    def test_load_nonexistent_file(self, temp_dir):
        """Test loading a non-existent configuration file."""
        with pytest.raises(FileNotFoundError):
            load_config(temp_dir / "nonexistent.json")

    def test_load_minimal_config(self, temp_dir):
        """Test loading minimal configuration."""
        config_path = temp_dir / "minimal.json"
        with open(config_path, "w") as f:
            json.dump({"mcpServers": {}}, f)

        config = load_config(config_path)
        assert config.host == "127.0.0.1"  # Default
        assert config.port == 3000  # Default
        assert len(config.servers) == 0

    def test_load_config_with_string_args(self, temp_dir):
        """Test loading config where args is a string instead of list."""
        config_path = temp_dir / "string_args.json"
        with open(config_path, "w") as f:
            json.dump({"mcpServers": {"test": {"command": "npx", "args": "-y server-package"}}}, f)

        config = load_config(config_path)
        assert config.servers["test"].args == ["-y", "server-package"]

    def test_load_config_with_command_containing_spaces(self, temp_dir):
        """Test loading config where command contains spaces."""
        config_path = temp_dir / "spaced_command.json"
        with open(config_path, "w") as f:
            json.dump(
                {"mcpServers": {"test": {"command": "npx -y @modelcontextprotocol/server-memory"}}},
                f,
            )

        config = load_config(config_path)
        assert config.servers["test"].command == "npx"
        assert config.servers["test"].args == ["-y", "@modelcontextprotocol/server-memory"]

    def test_load_config_with_disabled_tools_snake_case(self, temp_dir):
        """Test loading config with disabled_tools (snake_case)."""
        config_path = temp_dir / "snake_case.json"
        with open(config_path, "w") as f:
            json.dump(
                {"mcpServers": {"test": {"command": "npx", "disabled_tools": ["tool1", "tool2"]}}},
                f,
            )

        config = load_config(config_path)
        assert config.servers["test"].disabled_tools == ["tool1", "tool2"]

    def test_load_config_with_env(self, temp_dir):
        """Test loading config with environment variables."""
        config_path = temp_dir / "with_env.json"
        with open(config_path, "w") as f:
            json.dump(
                {
                    "mcpServers": {
                        "test": {"command": "npx", "env": {"API_KEY": "secret", "DEBUG": "1"}}
                    }
                },
                f,
            )

        config = load_config(config_path)
        assert config.servers["test"].env == {"API_KEY": "secret", "DEBUG": "1"}

    def test_load_config_with_camelCase_disabled_tools(self, temp_dir):
        """Test loading config with disabledTools (camelCase)."""
        config_path = temp_dir / "camel_case.json"
        with open(config_path, "w") as f:
            json.dump({"mcpServers": {"test": {"command": "npx", "disabledTools": ["tool1"]}}}, f)

        config = load_config(config_path)
        assert config.servers["test"].disabled_tools == ["tool1"]

    def test_load_config_with_authentication(self, temp_dir):
        """Test loading config with authentication settings."""
        config_path = temp_dir / "with_auth.json"
        with open(config_path, "w") as f:
            json.dump(
                {
                    "gateway": {
                        "apiKey": "my-api-key",
                        "bearerToken": "my-bearer-token",
                        "authExcludePaths": ["/health", "/public"],
                    },
                    "mcpServers": {},
                },
                f,
            )

        config = load_config(config_path)
        assert config.api_key == "my-api-key"
        assert config.bearer_token == "my-bearer-token"
        assert config.auth_exclude_paths == ["/health", "/public"]

    def test_load_config_with_auth_snake_case(self, temp_dir):
        """Test loading config with authentication (snake_case)."""
        config_path = temp_dir / "with_auth_snake.json"
        with open(config_path, "w") as f:
            json.dump(
                {
                    "gateway": {"api_key": "my-api-key", "bearer_token": "my-bearer-token"},
                    "mcpServers": {},
                },
                f,
            )

        config = load_config(config_path)
        assert config.api_key == "my-api-key"
        assert config.bearer_token == "my-bearer-token"

    def test_load_config_with_timeouts(self, temp_dir):
        """Test loading config with timeout settings."""
        config_path = temp_dir / "with_timeouts.json"
        with open(config_path, "w") as f:
            json.dump(
                {"gateway": {"connectionTimeout": 15.0, "requestTimeout": 45.0}, "mcpServers": {}},
                f,
            )

        config = load_config(config_path)
        assert config.connection_timeout == 15.0
        assert config.request_timeout == 45.0

    def test_load_config_with_admin_settings(self, temp_dir):
        """Test loading config with admin panel settings."""
        config_path = temp_dir / "with_admin.json"
        with open(config_path, "w") as f:
            json.dump(
                {
                    "gateway": {"adminUsername": "myadmin", "adminPassword": "secret123"},
                    "mcpServers": {},
                },
                f,
            )

        config = load_config(config_path)
        assert config.admin_username == "myadmin"
        assert config.admin_password == "secret123"
