"""Tests for mcp_gateway.hot_reload module."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.hot_reload import (
    ConfigChange,
    ConfigFileHandler,
    ConfigWatcher,
    HotReloadManager,
)


class TestConfigChange:
    """Tests for ConfigChange dataclass."""
    
    def test_added_change(self):
        """Test creating an 'added' change."""
        change = ConfigChange(
            action="added",
            server_name="new-server",
            new_config={"command": "npx", "args": ["pkg"]}
        )
        assert change.action == "added"
        assert change.server_name == "new-server"
        assert change.old_config is None
        assert change.new_config == {"command": "npx", "args": ["pkg"]}
    
    def test_removed_change(self):
        """Test creating a 'removed' change."""
        change = ConfigChange(
            action="removed",
            server_name="old-server",
            old_config={"command": "npx"}
        )
        assert change.action == "removed"
        assert change.server_name == "old-server"
        assert change.old_config == {"command": "npx"}
        assert change.new_config is None
    
    def test_modified_change(self):
        """Test creating a 'modified' change."""
        change = ConfigChange(
            action="modified",
            server_name="existing-server",
            old_config={"command": "npx"},
            new_config={"command": "uvx"}
        )
        assert change.action == "modified"
        assert change.server_name == "existing-server"
        assert change.old_config == {"command": "npx"}
        assert change.new_config == {"command": "uvx"}


class TestConfigFileHandler:
    """Tests for ConfigFileHandler class."""
    
    @pytest.mark.asyncio
    async def test_on_modified_directory(self):
        """Test that directory modifications are ignored."""
        callback = AsyncMock()
        handler = ConfigFileHandler(callback)
        
        event = MagicMock()
        event.is_directory = True
        
        handler.on_modified(event)
        
        callback.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_on_modified_file(self):
        """Test handling file modification."""
        callback = MagicMock()
        handler = ConfigFileHandler(callback)
        
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/config.json"
        
        # Mock asyncio.get_event_loop().time()
        with patch.object(asyncio.get_event_loop(), 'time', return_value=10.0):
            handler.on_modified(event)
        
        # Should have scheduled callback
        await asyncio.sleep(0.1)  # Let async tasks run


class TestConfigWatcher:
    """Tests for ConfigWatcher class."""
    
    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "gateway": {"host": "127.0.0.1"},
                "mcpServers": {
                    "memory": {"command": "npx", "args": ["memory-server"]}
                }
            }
            json.dump(config, f)
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.fixture
    def mock_reload_callback(self):
        """Create a mock reload callback."""
        return AsyncMock()
    
    @pytest.mark.asyncio
    async def test_initialization_polling(self, temp_config_file, mock_reload_callback):
        """Test watcher initialization with polling."""
        watcher = ConfigWatcher(
            temp_config_file,
            mock_reload_callback,
            use_polling=True,
            poll_interval=1.0
        )
        
        assert watcher.config_path == Path(temp_config_file)
        assert watcher.use_polling is True
        assert watcher.poll_interval == 1.0
        assert watcher._running is False
    
    @pytest.mark.asyncio
    async def test_start_stop_polling(self, temp_config_file, mock_reload_callback):
        """Test starting and stopping polling watcher."""
        watcher = ConfigWatcher(
            temp_config_file,
            mock_reload_callback,
            use_polling=True,
            poll_interval=0.1
        )
        
        await watcher.start()
        assert watcher._running is True
        
        await watcher.stop()
        assert watcher._running is False
    
    @pytest.mark.asyncio
    async def test_load_initial_config(self, temp_config_file, mock_reload_callback):
        """Test loading initial configuration."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        await watcher._load_initial_config()
        
        assert watcher._last_config["gateway"]["host"] == "127.0.0.1"
        assert "memory" in watcher._last_config["mcpServers"]
    
    @pytest.mark.asyncio
    async def test_compute_changes_added(self, temp_config_file, mock_reload_callback):
        """Test computing changes - server added."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        old_config = {"mcpServers": {}}
        new_config = {"mcpServers": {"new-server": {"command": "npx"}}}
        
        changes = watcher._compute_changes(old_config, new_config)
        
        assert len(changes) == 1
        assert changes[0].action == "added"
        assert changes[0].server_name == "new-server"
    
    @pytest.mark.asyncio
    async def test_compute_changes_removed(self, temp_config_file, mock_reload_callback):
        """Test computing changes - server removed."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        old_config = {"mcpServers": {"old-server": {"command": "npx"}}}
        new_config = {"mcpServers": {}}
        
        changes = watcher._compute_changes(old_config, new_config)
        
        assert len(changes) == 1
        assert changes[0].action == "removed"
        assert changes[0].server_name == "old-server"
    
    @pytest.mark.asyncio
    async def test_compute_changes_modified(self, temp_config_file, mock_reload_callback):
        """Test computing changes - server modified."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        old_config = {"mcpServers": {"server": {"command": "npx"}}}
        new_config = {"mcpServers": {"server": {"command": "uvx"}}}
        
        changes = watcher._compute_changes(old_config, new_config)
        
        assert len(changes) == 1
        assert changes[0].action == "modified"
        assert changes[0].server_name == "server"
    
    @pytest.mark.asyncio
    async def test_compute_changes_no_changes(self, temp_config_file, mock_reload_callback):
        """Test computing changes - no changes."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        config = {"mcpServers": {"server": {"command": "npx"}}}
        
        changes = watcher._compute_changes(config, config)
        
        assert len(changes) == 0
    
    def test_configs_differ_true(self, temp_config_file, mock_reload_callback):
        """Test _configs_differ when configs are different."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        old = {"command": "npx", "args": ["old"]}
        new = {"command": "npx", "args": ["new"]}
        
        assert watcher._configs_differ(old, new) is True
    
    def test_configs_differ_false(self, temp_config_file, mock_reload_callback):
        """Test _configs_differ when configs are the same."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        config = {"command": "npx", "args": ["test"]}
        
        assert watcher._configs_differ(config, config) is False
    
    def test_normalize_args_none(self, temp_config_file, mock_reload_callback):
        """Test normalizing None args."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        result = watcher._normalize_args(None)
        
        assert result == ()
    
    def test_normalize_args_list(self, temp_config_file, mock_reload_callback):
        """Test normalizing list args."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        result = watcher._normalize_args(["arg1", "arg2"])
        
        assert result == ("arg1", "arg2")
    
    def test_normalize_args_string(self, temp_config_file, mock_reload_callback):
        """Test normalizing string args."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        result = watcher._normalize_args("arg1 arg2")
        
        assert result == ("arg1", "arg2")
    
    @pytest.mark.asyncio
    async def test_on_config_changed_invalid_json(self, temp_config_file, mock_reload_callback):
        """Test handling invalid JSON in config file."""
        watcher = ConfigWatcher(temp_config_file, mock_reload_callback)
        
        # Write invalid JSON
        with open(temp_config_file, 'w') as f:
            f.write("not valid json")
        
        await watcher._on_config_changed()
        
        # Should not raise, but log error
        mock_reload_callback.assert_not_called()


class TestHotReloadManager:
    """Tests for HotReloadManager class."""
    
    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "gateway": {"host": "127.0.0.1"},
                "mcpServers": {}
            }
            json.dump(config, f)
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.fixture
    def mock_backend_manager(self):
        """Create a mock backend manager."""
        bm = MagicMock()
        bm.disconnect_all = AsyncMock()
        return bm
    
    @pytest.fixture
    def mock_config_loader(self):
        """Create a mock config loader."""
        return MagicMock(return_value=MagicMock())
    
    @pytest.fixture
    def mock_reconnect_callback(self):
        """Create a mock reconnect callback."""
        return AsyncMock()
    
    @pytest.fixture
    def reload_manager(self, temp_config_file, mock_backend_manager, mock_config_loader, mock_reconnect_callback):
        """Create a HotReloadManager instance."""
        return HotReloadManager(
            config_path=temp_config_file,
            backend_manager=mock_backend_manager,
            config_loader=mock_config_loader,
            reconnect_callback=mock_reconnect_callback,
        )
    
    def test_initialization(self, temp_config_file, mock_backend_manager, mock_config_loader, mock_reconnect_callback):
        """Test HotReloadManager initialization."""
        manager = HotReloadManager(
            config_path=temp_config_file,
            backend_manager=mock_backend_manager,
            config_loader=mock_config_loader,
            reconnect_callback=mock_reconnect_callback,
        )
        
        assert manager.config_path == Path(temp_config_file)
        assert manager.backend_manager == mock_backend_manager
        assert manager.config_loader == mock_config_loader
        assert manager.reconnect_callback == mock_reconnect_callback
        assert manager.watcher is None
        assert manager._reload_count == 0
    
    @pytest.mark.asyncio
    async def test_reload_config_success(self, reload_manager):
        """Test successful config reload."""
        await reload_manager._reload_config()
        
        reload_manager.backend_manager.disconnect_all.assert_called_once()
        reload_manager.reconnect_callback.assert_called_once()
        assert reload_manager._reload_count == 1
        assert reload_manager._last_reload_time is not None
    
    @pytest.mark.asyncio
    async def test_reload_config_failure(self, reload_manager, mock_reconnect_callback):
        """Test config reload failure handling."""
        mock_reconnect_callback.side_effect = Exception("Reload failed")
        
        await reload_manager._reload_config()
        
        # Should not raise, but keep running
        assert reload_manager._reload_count == 0
    
    @pytest.mark.asyncio
    async def test_start_stop(self, reload_manager):
        """Test starting and stopping hot reload."""
        with patch.object(reload_manager, '_reload_config', AsyncMock()):
            await reload_manager.start(use_polling=True)
            assert reload_manager.watcher is not None
            
            await reload_manager.stop()
            assert reload_manager.watcher is None
    
    def test_reload_count_property(self, reload_manager):
        """Test reload_count property."""
        reload_manager._reload_count = 5
        assert reload_manager.reload_count == 5
    
    def test_last_reload_time_property(self, reload_manager):
        """Test last_reload_time property."""
        reload_manager._last_reload_time = 12345.0
        assert reload_manager.last_reload_time == 12345.0
