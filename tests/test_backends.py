"""Tests for mcp_gateway.backends module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from mcp_gateway.backends import BackendConnection, BackendManager
from mcp_gateway.config import ServerConfig


class TestBackendConnection:
    """Tests for BackendConnection class."""
    
    @pytest.fixture
    def stdio_config(self):
        """Return a stdio server config."""
        return ServerConfig(
            name="memory",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"]
        )
    
    @pytest.fixture
    def remote_config(self):
        """Return a remote server config."""
        return ServerConfig(
            name="remote",
            url="https://example.com/mcp",
            type="streamable-http",
            headers={"Authorization": "Bearer token"}
        )
    
    @pytest.fixture
    def sse_config(self):
        """Return an SSE server config."""
        return ServerConfig(
            name="sse-server",
            url="http://localhost:8001/sse",
            type="sse"
        )
    
    def test_initialization_stdio(self, stdio_config):
        """Test BackendConnection initialization for stdio."""
        backend = BackendConnection(stdio_config)
        assert backend.name == "memory"
        assert backend.is_connected is False
        assert backend.tools == []
        assert backend.session is None
    
    def test_initialization_with_timeouts(self, stdio_config):
        """Test BackendConnection initialization with custom timeouts."""
        backend = BackendConnection(stdio_config, connection_timeout=10.0, request_timeout=30.0)
        assert backend._connection_timeout == 10.0
        assert backend._request_timeout == 30.0
    
    def test_initialization_remote(self, remote_config):
        """Test BackendConnection initialization for remote."""
        backend = BackendConnection(remote_config)
        assert backend.name == "remote"
        assert backend.is_connected is False
    
    @pytest.mark.asyncio
    async def test_connect_stdio_success(self, stdio_config):
        """Test successful stdio connection."""
        backend = BackendConnection(stdio_config)
        
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        
        with patch("mcp_gateway.backends.stdio_client") as mock_stdio_client, \
             patch("mcp_gateway.backends.ClientSession") as mock_client_session:
            
            mock_transport = (AsyncMock(), AsyncMock())
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=mock_transport)
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await backend.connect()
            
            assert backend.is_connected is True
            mock_session.initialize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_stdio_with_tools(self, stdio_config):
        """Test stdio connection with tools returned."""
        backend = BackendConnection(stdio_config)
        
        mock_tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={}),
            Tool(name="tool2", description="Tool 2", inputSchema={})
        ]
        
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=mock_tools))
        
        with patch("mcp_gateway.backends.stdio_client") as mock_stdio_client, \
             patch("mcp_gateway.backends.ClientSession") as mock_client_session:
            
            mock_transport = (AsyncMock(), AsyncMock())
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=mock_transport)
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await backend.connect()
            
            assert len(backend.tools) == 2
            assert backend.tools[0].name == "tool1"
    
    @pytest.mark.asyncio
    async def test_connect_stdio_failure(self, stdio_config):
        """Test stdio connection failure."""
        backend = BackendConnection(stdio_config)
        
        with patch("mcp_gateway.backends.stdio_client") as mock_stdio_client:
            mock_stdio_client.return_value.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(Exception, match="Connection failed"):
                await backend.connect()
            
            assert backend.is_connected is False
    
    @pytest.mark.asyncio
    async def test_connect_remote_streamable_http(self, remote_config):
        """Test remote connection via StreamableHTTP."""
        backend = BackendConnection(remote_config)
        
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        
        with patch("mcp_gateway.backends.streamablehttp_client") as mock_http_client, \
             patch("mcp_gateway.backends.ClientSession") as mock_client_session:
            
            mock_transport = (AsyncMock(), AsyncMock())
            mock_http_client.return_value.__aenter__ = AsyncMock(return_value=mock_transport)
            mock_http_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await backend.connect()
            
            assert backend.is_connected is True
            mock_http_client.assert_called_once_with(
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer token"}
            )
    
    @pytest.mark.asyncio
    async def test_connect_remote_sse(self, sse_config):
        """Test remote connection via SSE."""
        backend = BackendConnection(sse_config)
        
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        
        with patch("mcp_gateway.backends.sse_client") as mock_sse_client, \
             patch("mcp_gateway.backends.ClientSession") as mock_client_session:
            
            mock_transport = (AsyncMock(), AsyncMock())
            mock_sse_client.return_value.__aenter__ = AsyncMock(return_value=mock_transport)
            mock_sse_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await backend.connect()
            
            assert backend.is_connected is True
            mock_sse_client.assert_called_once_with(
                url="http://localhost:8001/sse",
                headers={}
            )
    
    @pytest.mark.asyncio
    async def test_connect_remote_fallback_to_sse(self, remote_config):
        """Test that StreamableHTTP failure falls back to SSE."""
        backend = BackendConnection(remote_config)
        
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        
        with patch("mcp_gateway.backends.streamablehttp_client") as mock_http_client, \
             patch("mcp_gateway.backends.sse_client") as mock_sse_client, \
             patch("mcp_gateway.backends.ClientSession") as mock_client_session:
            
            # Make HTTP fail
            mock_http_client.return_value.__aenter__ = AsyncMock(side_effect=Exception("HTTP failed"))
            mock_http_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Make SSE succeed
            mock_transport = (AsyncMock(), AsyncMock())
            mock_sse_client.return_value.__aenter__ = AsyncMock(return_value=mock_transport)
            mock_sse_client.return_value.__aexit__ = AsyncMock(return_value=None)
            
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await backend.connect()
            
            assert backend.is_connected is True
    
    def test_filter_tools(self, stdio_config):
        """Test tool filtering."""
        stdio_config.disabled_tools = ["tool2"]
        backend = BackendConnection(stdio_config)
        
        tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={}),
            Tool(name="tool2", description="Tool 2", inputSchema={}),
            Tool(name="tool3", description="Tool 3", inputSchema={})
        ]
        
        filtered = backend._filter_tools(tools)
        
        assert len(filtered) == 2
        assert all(t.name != "tool2" for t in filtered)
    
    def test_filter_tools_empty_disabled(self, stdio_config):
        """Test tool filtering with no disabled tools."""
        backend = BackendConnection(stdio_config)
        
        tools = [
            Tool(name="tool1", description="Tool 1", inputSchema={})
        ]
        
        filtered = backend._filter_tools(tools)
        
        assert len(filtered) == 1
    
    @pytest.mark.asyncio
    async def test_call_tool_success(self, stdio_config):
        """Test successful tool call."""
        backend = BackendConnection(stdio_config)
        backend._connected = True
        
        mock_session = AsyncMock()
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="Result")],
            isError=False
        )
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        backend.session = mock_session
        
        result = await backend.call_tool("test_tool", {"arg": "value"})
        
        assert result.isError is False
        assert len(result.content) == 1
        mock_session.call_tool.assert_called_once_with("test_tool", arguments={"arg": "value"})
    
    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self, stdio_config):
        """Test tool call when not connected."""
        backend = BackendConnection(stdio_config)
        backend._connected = False
        
        with pytest.raises(RuntimeError, match="not connected"):
            await backend.call_tool("test_tool", {})
    
    @pytest.mark.asyncio
    async def test_disconnect(self, stdio_config):
        """Test disconnection."""
        backend = BackendConnection(stdio_config)
        backend._connected = True
        backend._tools = [Tool(name="tool1", description="Test", inputSchema={})]
        mock_exit_stack = AsyncMock()
        backend._exit_stack = mock_exit_stack
        
        await backend.disconnect()
        
        assert backend.is_connected is False
        assert backend.tools == []
        mock_exit_stack.aclose.assert_called_once()


class TestBackendManager:
    """Tests for BackendManager class."""
    
    @pytest.fixture
    def manager(self):
        """Return a fresh BackendManager instance."""
        return BackendManager()
    
    def test_initialization(self, manager):
        """Test BackendManager initialization."""
        assert manager.backends == {}
        assert manager._tool_map == {}
        assert manager._namespace_separator == "__"
    
    def test_initialization_custom_separator(self):
        """Test BackendManager with custom namespace separator."""
        manager = BackendManager(namespace_separator="::")
        assert manager._namespace_separator == "::"
    
    def test_initialization_custom_timeouts(self):
        """Test BackendManager with custom timeouts."""
        manager = BackendManager(connection_timeout=10.0, request_timeout=30.0)
        assert manager._connection_timeout == 10.0
        assert manager._request_timeout == 30.0
    
    @pytest.mark.asyncio
    async def test_add_backend(self, manager):
        """Test adding a backend."""
        config = ServerConfig(name="test", command="npx")
        
        mock_tools = [Tool(name="tool1", description="Test", inputSchema={})]
        
        # Create a mock backend that simulates a connected backend
        mock_backend = MagicMock()
        mock_backend.name = "test"
        mock_backend.is_connected = True
        mock_backend.tools = mock_tools
        mock_backend.connect = AsyncMock()
        
        with patch.object(BackendConnection, "__new__", return_value=mock_backend):
            actual_backend = await manager.add_backend(config)
            
            assert "test" in manager.backends
            assert f"test{manager._namespace_separator}tool1" in manager._tool_map
            assert manager._tool_map[f"test{manager._namespace_separator}tool1"] == "test"
    
    @pytest.mark.asyncio
    async def test_connect_all(self, manager):
        """Test connecting to all configured backends."""
        configs = {
            "backend1": ServerConfig(name="backend1", command="npx"),
            "backend2": ServerConfig(name="backend2", command="uvx")
        }
        
        with patch.object(BackendConnection, "connect", AsyncMock()):
            await manager.connect_all(configs)
    
    @pytest.mark.asyncio
    async def test_connect_all_with_failure(self, manager):
        """Test connecting to backends with some failures."""
        configs = {
            "backend1": ServerConfig(name="backend1", command="npx"),
            "backend2": ServerConfig(name="backend2", command="uvx")
        }
        
        with patch.object(BackendConnection, "connect", AsyncMock(side_effect=[None, Exception("Failed")])):
            await manager.connect_all(configs)
            
            # Should have attempted both backends
    
    @pytest.mark.asyncio
    async def test_disconnect_all(self, manager):
        """Test disconnecting from all backends."""
        # Add mock backends
        backend1 = MagicMock()
        backend1.disconnect = AsyncMock()
        backend2 = MagicMock()
        backend2.disconnect = AsyncMock()
        
        manager._backends = {"backend1": backend1, "backend2": backend2}
        manager._tool_map = {"tool1": "backend1"}
        
        await manager.disconnect_all()
        
        assert manager.backends == {}
        assert manager._tool_map == {}
        backend1.disconnect.assert_called_once()
        backend2.disconnect.assert_called_once()
    
    def test_get_all_tools(self, manager):
        """Test getting all tools with namespacing."""
        # Create mock backends
        backend1 = MagicMock()
        backend1.name = "backend1"
        backend1.tools = [Tool(name="tool1", description="Tool 1", inputSchema={})]
        
        backend2 = MagicMock()
        backend2.name = "backend2"
        backend2.tools = [Tool(name="tool2", description="Tool 2", inputSchema={})]
        
        manager._backends = {"backend1": backend1, "backend2": backend2}
        
        all_tools = manager.get_all_tools()
        
        assert len(all_tools) == 2
        tool_names = {t.name for t in all_tools}
        assert tool_names == {"backend1__tool1", "backend2__tool2"}
    
    def test_get_backend_for_tool(self, manager):
        """Test getting backend for a tool."""
        backend1 = MagicMock()
        backend1.name = "backend1"
        
        manager._backends = {"backend1": backend1}
        manager._tool_map = {"backend1__tool1": "backend1"}
        
        result = manager.get_backend_for_tool("backend1__tool1")
        
        assert result == backend1
    
    def test_get_backend_for_tool_not_found(self, manager):
        """Test getting backend for non-existent tool."""
        result = manager.get_backend_for_tool("nonexistent__tool")
        
        assert result is None
    
    def test_get_backend_for_tool_invalid_name(self, manager):
        """Test getting backend for tool with invalid name format."""
        result = manager.get_backend_for_tool("invalid_tool_name")
        
        assert result is None
    
    def test_extract_original_tool_name(self, manager):
        """Test extracting original tool name from namespaced name."""
        backend, original = manager.extract_original_tool_name("backend1__tool_name")
        
        assert backend == "backend1"
        assert original == "tool_name"
    
    def test_extract_original_tool_name_custom_separator(self):
        """Test extracting with custom namespace separator."""
        manager = BackendManager(namespace_separator="::")
        backend, original = manager.extract_original_tool_name("backend1::tool_name")
        
        assert backend == "backend1"
        assert original == "tool_name"
    
    def test_extract_original_tool_name_no_separator(self, manager):
        """Test extracting from name without separator."""
        backend, original = manager.extract_original_tool_name("simple_tool")
        
        assert backend == ""
        assert original == "simple_tool"
    
    def test_extract_original_tool_name_multiple_separators(self, manager):
        """Test extracting from name with multiple separators."""
        backend, original = manager.extract_original_tool_name("backend__tool__name")
        
        assert backend == "backend"
        assert original == "tool__name"
