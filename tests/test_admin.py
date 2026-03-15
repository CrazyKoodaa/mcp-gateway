"""Tests for mcp_gateway.admin module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPBasicCredentials

from mcp_gateway.admin import (
    AdminAuth,
    AdminConfig,
    ConfigManager,
    setup_admin,
    validate_server_config,
)
from mcp_gateway.config import GatewayConfig, ServerConfig


class TestAdminConfig:
    """Tests for AdminConfig dataclass."""
    
    def test_default_values(self):
        """Test AdminConfig default values."""
        config = AdminConfig()
        assert config.username == "admin"
        assert config.password is None
        assert config.enabled is False
        assert config.secret_key is None
    
    def test_custom_values(self):
        """Test AdminConfig with custom values."""
        config = AdminConfig(
            username="myadmin",
            password="secret123",
            enabled=True,
            secret_key="my-secret-key"
        )
        assert config.username == "myadmin"
        assert config.password == "secret123"
        assert config.enabled is True
        assert config.secret_key == "my-secret-key"


class TestConfigManager:
    """Tests for ConfigManager class."""
    
    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "gateway": {"host": "127.0.0.1", "port": 3000},
                "mcpServers": {
                    "memory": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-memory"]
                    }
                }
            }
            json.dump(config, f)
            temp_path = f.name
        yield temp_path
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.fixture
    def gateway_config(self):
        """Create a test gateway config."""
        config = GatewayConfig(host="127.0.0.1", port=3000)
        config.mcp_servers["memory"] = ServerConfig(
            name="memory",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"]
        )
        return config
    
    @pytest.fixture
    def config_manager(self, temp_config_file, gateway_config):
        """Create a ConfigManager instance."""
        return ConfigManager(temp_config_file, gateway_config)
    
    def test_initialization(self, temp_config_file, gateway_config):
        """Test ConfigManager initialization."""
        manager = ConfigManager(temp_config_file, gateway_config)
        assert manager.config_path == Path(temp_config_file)
        assert manager.gateway_config == gateway_config
        assert manager._lock is False
    
    @pytest.mark.asyncio
    async def test_reload(self, config_manager):
        """Test reloading configuration."""
        config = await config_manager.reload()
        assert isinstance(config, GatewayConfig)
        assert config.host == "127.0.0.1"
    
    @pytest.mark.asyncio
    async def test_save(self, config_manager, temp_config_file):
        """Test saving configuration."""
        await config_manager.save()
        
        # Verify file was written
        with open(temp_config_file, 'r') as f:
            saved = json.load(f)
        
        assert "gateway" in saved
        assert "mcpServers" in saved
        assert saved["gateway"]["host"] == "127.0.0.1"
    
    @pytest.mark.asyncio
    async def test_save_locked(self, config_manager):
        """Test save when locked."""
        config_manager._lock = True
        
        with pytest.raises(RuntimeError, match="locked"):
            await config_manager.save()
    
    def test_serialize_config(self, config_manager):
        """Test configuration serialization."""
        data = config_manager._serialize_config()
        
        assert "gateway" in data
        assert "mcpServers" in data
        assert data["gateway"]["host"] == "127.0.0.1"
        assert "memory" in data["mcpServers"]
    
    def test_serialize_server_stdio(self, config_manager):
        """Test serializing stdio server config."""
        server = ServerConfig(
            name="test",
            command="npx",
            args=["-y", "package"],
            env={"KEY": "value"},
            disabled_tools=["tool1"]
        )
        
        data = config_manager._serialize_server(server)
        
        assert data["command"] == "npx"
        assert data["args"] == ["-y", "package"]
        assert data["env"] == {"KEY": "value"}
        assert data["disabledTools"] == ["tool1"]
    
    def test_serialize_server_remote(self, config_manager):
        """Test serializing remote server config."""
        server = ServerConfig(
            name="remote",
            url="https://api.example.com/mcp",
            type="streamable-http",
            headers={"Authorization": "Bearer token"}
        )
        
        data = config_manager._serialize_server(server)
        
        assert data["url"] == "https://api.example.com/mcp"
        assert data["type"] == "streamable-http"
        assert data["headers"] == {"Authorization": "Bearer token"}
        assert "command" not in data
    
    @pytest.mark.asyncio
    async def test_add_server(self, config_manager):
        """Test adding a new server."""
        config = {"command": "uvx", "args": ["mcp-server-time"]}
        
        server = await config_manager.add_server("time", config)
        
        assert "time" in config_manager.gateway_config.servers
        assert server.name == "time"
        assert server.command == "uvx"
    
    @pytest.mark.asyncio
    async def test_add_server_already_exists(self, config_manager):
        """Test adding a server that already exists."""
        config = {"command": "npx", "args": ["test"]}
        
        with pytest.raises(ValueError, match="already exists"):
            await config_manager.add_server("memory", config)
    
    @pytest.mark.asyncio
    async def test_update_server(self, config_manager):
        """Test updating an existing server."""
        config = {"command": "uvx", "args": ["updated-package"]}
        
        server = await config_manager.update_server("memory", config)
        
        assert server.command == "uvx"
        assert server.args == ["updated-package"]
    
    @pytest.mark.asyncio
    async def test_update_server_not_found(self, config_manager):
        """Test updating a non-existent server."""
        config = {"command": "npx", "args": ["test"]}
        
        with pytest.raises(ValueError, match="not found"):
            await config_manager.update_server("nonexistent", config)
    
    @pytest.mark.asyncio
    async def test_remove_server(self, config_manager):
        """Test removing a server."""
        await config_manager.remove_server("memory")
        
        assert "memory" not in config_manager.gateway_config.servers
    
    @pytest.mark.asyncio
    async def test_remove_server_not_found(self, config_manager):
        """Test removing a non-existent server."""
        with pytest.raises(ValueError, match="not found"):
            await config_manager.remove_server("nonexistent")
    
    def test_parse_server_config(self, config_manager):
        """Test parsing server config from dict."""
        config = {
            "command": "npx -y @modelcontextprotocol/server-memory",
            "env": {"KEY": "value"},
            "disabledTools": ["tool1"]
        }
        
        server = config_manager._parse_server_config("test", config)
        
        assert server.name == "test"
        assert server.command == "npx"
        assert server.args == ["-y", "@modelcontextprotocol/server-memory"]
        assert server.env == {"KEY": "value"}
        assert server.disabled_tools == ["tool1"]


class TestAdminAuth:
    """Tests for AdminAuth class."""
    
    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.app.state = MagicMock()
        request.app.state.auth_config = MagicMock()
        request.app.state.auth_config.api_key = None
        return request
    
    @pytest.mark.asyncio
    async def test_admin_disabled_no_api_key(self, mock_request):
        """Test when admin is disabled and no API key fallback."""
        config = AdminConfig(enabled=False)
        auth = AdminAuth(config)
        
        with pytest.raises(HTTPException) as exc_info:
            await auth(mock_request, None)
        
        assert exc_info.value.status_code == 403
        assert "disabled" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_admin_disabled_with_valid_api_key(self, mock_request):
        """Test API key fallback when admin is disabled."""
        config = AdminConfig(enabled=False)
        auth = AdminAuth(config)
        
        mock_request.headers = {"X-API-Key": "valid-key"}
        mock_request.app.state.auth_config.api_key = "valid-key"
        
        result = await auth(mock_request, None)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_admin_enabled_no_credentials(self, mock_request):
        """Test when credentials are missing."""
        config = AdminConfig(enabled=True, username="admin", password="secret")
        auth = AdminAuth(config)
        
        with pytest.raises(HTTPException) as exc_info:
            await auth(mock_request, None)
        
        assert exc_info.value.status_code == 401
        assert "WWW-Authenticate" in exc_info.value.headers
    
    @pytest.mark.asyncio
    async def test_admin_enabled_no_password_configured(self, mock_request):
        """Test when admin is enabled but no password set."""
        config = AdminConfig(enabled=True, username="admin", password=None)
        auth = AdminAuth(config)
        
        credentials = HTTPBasicCredentials(username="admin", password="anything")
        
        with pytest.raises(HTTPException) as exc_info:
            await auth(mock_request, credentials)
        
        assert exc_info.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_admin_valid_credentials(self, mock_request):
        """Test with valid credentials."""
        config = AdminConfig(enabled=True, username="admin", password="secret")
        auth = AdminAuth(config)
        
        credentials = HTTPBasicCredentials(username="admin", password="secret")
        
        result = await auth(mock_request, credentials)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_admin_invalid_username(self, mock_request):
        """Test with invalid username."""
        config = AdminConfig(enabled=True, username="admin", password="secret")
        auth = AdminAuth(config)
        
        credentials = HTTPBasicCredentials(username="wrong", password="secret")
        
        with pytest.raises(HTTPException) as exc_info:
            await auth(mock_request, credentials)
        
        assert exc_info.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_admin_invalid_password(self, mock_request):
        """Test with invalid password."""
        config = AdminConfig(enabled=True, username="admin", password="secret")
        auth = AdminAuth(config)
        
        credentials = HTTPBasicCredentials(username="admin", password="wrong")
        
        with pytest.raises(HTTPException) as exc_info:
            await auth(mock_request, credentials)
        
        assert exc_info.value.status_code == 401


class TestSetupAdmin:
    """Tests for setup_admin function."""
    
    def test_setup_admin_disabled(self):
        """Test setup when admin is not configured."""
        config = GatewayConfig()
        
        admin_config, config_manager = setup_admin(config)
        
        assert admin_config.enabled is False
        assert config_manager is None
    
    def test_setup_admin_enabled(self):
        """Test setup when admin is configured."""
        config = GatewayConfig(admin_username="myadmin", admin_password="secret")
        
        admin_config, config_manager = setup_admin(config)
        
        assert admin_config.username == "myadmin"
        assert admin_config.password == "secret"
        assert admin_config.enabled is True


class TestValidateServerConfig:
    """Tests for validate_server_config function."""
    
    def test_valid_stdio_config(self):
        """Test valid stdio server config."""
        config = {"command": "npx", "args": ["-y", "package"]}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is True
        assert error == ""
    
    def test_valid_remote_config(self):
        """Test valid remote server config."""
        config = {"url": "https://api.example.com/mcp", "type": "streamable-http"}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is True
        assert error == ""
    
    def test_missing_command_and_url(self):
        """Test config missing both command and url."""
        config = {"env": {"KEY": "value"}}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is False
        assert "command" in error.lower() or "url" in error.lower()
    
    def test_invalid_type(self):
        """Test config with invalid server type."""
        config = {"url": "https://example.com", "type": "invalid-type"}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is False
        assert "type" in error.lower()
    
    def test_invalid_url_format(self):
        """Test config with invalid URL format."""
        config = {"url": "ftp://example.com/mcp"}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is False
        assert "http" in error.lower()
    
    def test_empty_command(self):
        """Test config with empty command."""
        config = {"command": "   "}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is False
        assert "command" in error.lower()
    
    def test_valid_sse_type(self):
        """Test valid SSE type."""
        config = {"url": "http://localhost:3001/sse", "type": "sse"}
        
        is_valid, error = validate_server_config(config)
        
        assert is_valid is True
    
    def test_valid_streamablehttp_type(self):
        """Test valid streamablehttp type variations."""
        for type_val in ["streamable-http", "streamablehttp", "stdio"]:
            config = {"url": "https://example.com/mcp", "type": type_val}
            is_valid, error = validate_server_config(config)
            assert is_valid is True, f"Type {type_val} should be valid"
