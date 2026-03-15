"""Tests for mcp_gateway.main module."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.main import main, main_async, setup_logging


class TestSetupLogging:
    """Tests for setup_logging function."""
    
    def test_setup_logging_info(self):
        """Test setting up INFO level logging."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging("INFO")
            
            mock_basic_config.assert_called_once()
            call_args = mock_basic_config.call_args
            assert call_args.kwargs["level"] == 20  # logging.INFO
    
    def test_setup_logging_debug(self):
        """Test setting up DEBUG level logging."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging("DEBUG")
            
            call_args = mock_basic_config.call_args
            assert call_args.kwargs["level"] == 10  # logging.DEBUG
    
    def test_setup_logging_warning(self):
        """Test setting up WARNING level logging."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging("WARNING")
            
            call_args = mock_basic_config.call_args
            assert call_args.kwargs["level"] == 30  # logging.WARNING
    
    def test_setup_logging_error(self):
        """Test setting up ERROR level logging."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging("ERROR")
            
            call_args = mock_basic_config.call_args
            assert call_args.kwargs["level"] == 40  # logging.ERROR


class TestMainAsync:
    """Tests for main_async function."""
    
    @pytest.fixture
    def temp_config_file(self, tmp_path):
        """Create a temporary config file."""
        config_path = tmp_path / "config.json"
        import json
        config = {
            "gateway": {
                "host": "127.0.0.1",
                "port": 3000,
                "logLevel": "INFO"
            },
            "mcpServers": {}
        }
        with open(config_path, "w") as f:
            json.dump(config, f)
        return str(config_path)
    
    @pytest.mark.asyncio
    async def test_main_async_missing_config(self):
        """Test main_async with missing config file."""
        test_args = ["mcp-gateway", "--config", "/nonexistent/config.json"]
        
        with patch.object(sys, "argv", test_args):
            result = await main_async()
            
            assert result == 1
    
    @pytest.mark.asyncio
    async def test_main_async_invalid_config(self, tmp_path):
        """Test main_async with invalid config file."""
        config_path = tmp_path / "invalid.json"
        with open(config_path, "w") as f:
            f.write("{not valid json}")
        
        test_args = ["mcp-gateway", "--config", str(config_path)]
        
        with patch.object(sys, "argv", test_args):
            result = await main_async()
            
            assert result == 1
    
    @pytest.mark.asyncio
    async def test_main_async_no_backends(self, temp_config_file):
        """Test main_async when no backends connect."""
        test_args = ["mcp-gateway", "--config", temp_config_file]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class:
            
            mock_manager = MagicMock()
            mock_manager.backends = {}
            mock_manager.connect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            result = await main_async()
            
            assert result == 1
            mock_manager_class.assert_called_once_with(namespace_separator="__")
    
    @pytest.mark.asyncio
    async def test_main_async_successful_startup(self, temp_config_file):
        """Test main_async with successful startup."""
        test_args = ["mcp-gateway", "--config", temp_config_file]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.signal") as mock_signal:
            
            # Setup mock backend manager
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            # Setup mock server
            mock_server = MagicMock()
            mock_server.run = AsyncMock()
            mock_server_class.return_value = mock_server
            
            # Run and cancel immediately
            mock_server.run.side_effect = asyncio.CancelledError()
            
            result = await main_async()
            
            assert result == 0
            mock_manager.connect_all.assert_called_once()
            mock_server.run.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_main_async_with_cli_overrides(self, temp_config_file):
        """Test main_async with CLI argument overrides."""
        test_args = [
            "mcp-gateway",
            "--config", temp_config_file,
            "--host", "0.0.0.0",
            "--port", "8080",
            "--log-level", "DEBUG"
        ]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.setup_structured_logging") as mock_setup_logging:
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock(side_effect=asyncio.CancelledError())
            mock_server_class.return_value = mock_server
            
            await main_async()
            
            # Verify logging was called with DEBUG
            mock_setup_logging.assert_called_once()
            call_kwargs = mock_setup_logging.call_args.kwargs
            assert call_kwargs.get("log_level") == "DEBUG" or call_kwargs.get("json_format") == True
    
    @pytest.mark.asyncio
    async def test_main_async_backend_initialization_failure(self, temp_config_file):
        """Test main_async when backend initialization fails."""
        test_args = ["mcp-gateway", "--config", temp_config_file]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class:
            
            mock_manager = MagicMock()
            mock_manager.connect_all = AsyncMock(side_effect=Exception("Connection failed"))
            mock_manager_class.return_value = mock_manager
            
            result = await main_async()
            
            assert result == 1
    
    @pytest.mark.asyncio
    async def test_main_async_graceful_shutdown(self, temp_config_file):
        """Test main_async graceful shutdown handling."""
        test_args = ["mcp-gateway", "--config", temp_config_file]
        
        shutdown_handler = None
        
        def capture_signal_handler(sig, handler):
            nonlocal shutdown_handler
            if sig == signal.SIGINT:
                shutdown_handler = handler
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.signal.signal", side_effect=capture_signal_handler):
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock()
            mock_server_class.return_value = mock_server
            
            result = await main_async()
            
            assert result == 0
    
    @pytest.mark.asyncio
    async def test_main_async_with_hot_reload(self, temp_config_file):
        """Test main_async with hot reload enabled."""
        test_args = ["mcp-gateway", "--config", temp_config_file, "--hot-reload"]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.HotReloadManager") as mock_hot_reload_class:
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_hot_reload = MagicMock()
            mock_hot_reload.start = AsyncMock()
            mock_hot_reload.stop = AsyncMock()
            mock_hot_reload_class.return_value = mock_hot_reload
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock(side_effect=asyncio.CancelledError())
            mock_server.metrics = None
            mock_server_class.return_value = mock_server
            
            result = await main_async()
            
            assert result == 0
            mock_hot_reload_class.assert_called_once()
            mock_hot_reload.start.assert_called_once_with(use_polling=False)
            mock_hot_reload.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_main_async_with_hot_reload_polling(self, temp_config_file):
        """Test main_async with hot reload using polling."""
        test_args = ["mcp-gateway", "--config", temp_config_file, "--hot-reload", "--poll"]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.HotReloadManager") as mock_hot_reload_class:
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_hot_reload = MagicMock()
            mock_hot_reload.start = AsyncMock()
            mock_hot_reload.stop = AsyncMock()
            mock_hot_reload_class.return_value = mock_hot_reload
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock(side_effect=asyncio.CancelledError())
            mock_server.metrics = None
            mock_server_class.return_value = mock_server
            
            result = await main_async()
            
            assert result == 0
            mock_hot_reload.start.assert_called_once_with(use_polling=True)
    
    @pytest.mark.asyncio
    async def test_main_async_with_supervision(self, temp_config_file):
        """Test main_async with process supervision enabled."""
        test_args = ["mcp-gateway", "--config", temp_config_file]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.ProcessSupervisor") as mock_supervisor_class:
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_supervisor = MagicMock()
            mock_supervisor.start_supervision = AsyncMock()
            mock_supervisor.stop_supervision = AsyncMock()
            mock_supervisor_class.return_value = mock_supervisor
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock(side_effect=asyncio.CancelledError())
            mock_server.app.state = MagicMock()
            mock_server_class.return_value = mock_server
            
            result = await main_async()
            
            assert result == 0
            mock_supervisor_class.assert_called_once()
            mock_supervisor.start_supervision.assert_called_once()
            mock_supervisor.stop_supervision.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_main_async_no_supervision(self, temp_config_file):
        """Test main_async with supervision disabled."""
        test_args = ["mcp-gateway", "--config", temp_config_file, "--no-supervision"]
        
        with patch.object(sys, "argv", test_args), \
             patch("mcp_gateway.main.BackendManager") as mock_manager_class, \
             patch("mcp_gateway.main.McpGatewayServer") as mock_server_class, \
             patch("mcp_gateway.main.ProcessSupervisor") as mock_supervisor_class:
            
            mock_manager = MagicMock()
            mock_manager.backends = {"backend1": MagicMock()}
            mock_manager.connect_all = AsyncMock()
            mock_manager.disconnect_all = AsyncMock()
            mock_manager_class.return_value = mock_manager
            
            mock_server = MagicMock()
            mock_server.run = AsyncMock(side_effect=asyncio.CancelledError())
            mock_server_class.return_value = mock_server
            
            result = await main_async()
            
            assert result == 0
            mock_supervisor_class.assert_not_called()


class TestMain:
    """Tests for main function."""
    
    def test_main_success(self):
        """Test successful main execution."""
        with patch("mcp_gateway.main.main_async") as mock_main_async:
            mock_main_async.return_value = 0
            
            result = main()
            
            assert result == 0
            mock_main_async.assert_called_once()
    
    def test_main_keyboard_interrupt(self):
        """Test main with keyboard interrupt."""
        with patch("mcp_gateway.main.main_async") as mock_main_async:
            mock_main_async.side_effect = KeyboardInterrupt()
            
            result = main()
            
            assert result == 0
    
    def test_main_unexpected_error(self):
        """Test main with unexpected error."""
        with patch("mcp_gateway.main.main_async") as mock_main_async:
            mock_main_async.side_effect = Exception("Unexpected error")
            
            result = main()
            
            assert result == 1


class TestArgumentParsing:
    """Tests for CLI argument parsing."""
    
    def test_default_config_path(self):
        """Test default config path."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway"]):
            args = parse_args()
            
            assert args.config == "config.json"
    
    def test_custom_config_path(self):
        """Test custom config path."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--config", "/path/to/config.json"]):
            args = parse_args()
            
            assert args.config == "/path/to/config.json"
    
    def test_host_override(self):
        """Test host override argument."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--host", "0.0.0.0"]):
            args = parse_args()
            
            assert args.host == "0.0.0.0"
    
    def test_port_override(self):
        """Test port override argument."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--port", "8080"]):
            args = parse_args()
            
            assert args.port == 8080
    
    def test_log_level_override(self):
        """Test log level override argument."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--log-level", "DEBUG"]):
            args = parse_args()
            
            assert args.log_level == "DEBUG"
    
    def test_hot_reload_flag(self):
        """Test hot reload flag."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--hot-reload"]):
            args = parse_args()
            
            assert args.hot_reload is True
    
    def test_poll_flag(self):
        """Test poll flag."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--hot-reload", "--poll"]):
            args = parse_args()
            
            assert args.poll is True
    
    def test_no_supervision_flag(self):
        """Test no supervision flag."""
        from mcp_gateway.main import parse_args
        
        with patch.object(sys, "argv", ["mcp-gateway", "--no-supervision"]):
            args = parse_args()
            
            assert args.no_supervision is True
