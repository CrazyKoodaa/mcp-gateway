"""Integration tests for Hot Reload functionality."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.admin import ConfigManager
from mcp_gateway.config import load_config
from mcp_gateway.hot_reload import HotReloadManager
from mcp_gateway.server import McpGatewayServer, ServerDependencies


@pytest.fixture
def test_app_with_hot_reload(temp_config_file):
    """Create test app with hot reload enabled."""
    config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, config)

    backend_manager = MagicMock()
    backend_manager.backends = {}
    backend_manager.connect_all = MagicMock()
    backend_manager.disconnect_all = MagicMock()

    deps = ServerDependencies(
        config=config,
        backend_manager=backend_manager,
        config_manager=config_manager,
    )

    server = McpGatewayServer(dependencies=deps)
    app = server.create_app(enable_access_control=False)

    return app, config_manager, backend_manager, temp_config_file


@pytest.fixture
def client_with_hot_reload(test_app_with_hot_reload):
    """Create test client with hot reload."""
    app, _, _, _ = test_app_with_hot_reload
    return TestClient(app)


class TestManualReload:
    """Tests for manual reload via API."""

    def test_manual_reload_endpoint(self, client_with_hot_reload):
        """Test the manual reload endpoint."""
        response = client_with_hot_reload.post("/api/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "reloaded" in data["message"].lower()

    def test_reload_detects_config_changes(self, client_with_hot_reload, test_app_with_hot_reload):
        """Test that reload detects config file changes."""
        _, config_manager, _, config_path = test_app_with_hot_reload

        # Modify config directly
        with open(config_path) as f:
            config = json.load(f)

        config["gateway"]["logLevel"] = "DEBUG"

        with open(config_path, "w") as f:
            json.dump(config, f)

        # Trigger reload
        response = client_with_hot_reload.post("/api/reload")

        assert response.status_code == 200

        # Verify config was reloaded
        assert config_manager.gateway_config.log_level == "DEBUG"


class TestConfigPersistence:
    """Tests for config persistence through various operations."""

    def test_config_persists_after_server_add(
        self, client_with_hot_reload, test_app_with_hot_reload
    ):
        """Test that config is saved after adding server."""
        _, _, _, config_path = test_app_with_hot_reload

        # Add a new server
        response = client_with_hot_reload.post(
            "/api/servers",
            json={
                "name": "new-server",
                "config": {"command": "npx", "args": ["-y", "test-package"]},
            },
        )

        assert response.status_code == 200

        # Verify immediately
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "new-server" in saved_config["mcpServers"]

    def test_config_persists_after_server_update(
        self, client_with_hot_reload, test_app_with_hot_reload
    ):
        """Test that config is saved after updating server."""
        _, _, _, config_path = test_app_with_hot_reload

        # Update server
        response = client_with_hot_reload.put(
            "/api/servers/time",
            json={"command": "uvx", "args": ["mcp-server-time", "--new-flag"], "disabledTools": []},
        )

        assert response.status_code == 200

        # Verify immediately
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "--new-flag" in saved_config["mcpServers"]["time"]["args"]

    def test_config_persists_after_server_delete(
        self, client_with_hot_reload, test_app_with_hot_reload
    ):
        """Test that config is saved after deleting server."""
        _, _, _, config_path = test_app_with_hot_reload

        # Delete server
        response = client_with_hot_reload.delete("/api/servers/time")

        assert response.status_code == 200

        # Verify immediately
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "time" not in saved_config["mcpServers"]
        assert "memory" in saved_config["mcpServers"]


class TestAtomicWrites:
    """Tests for atomic config file writes."""

    def test_no_temp_files_left_behind(
        self, client_with_hot_reload, test_app_with_hot_reload, tmp_path
    ):
        """Test that temporary files are cleaned up after write."""
        _, _, _, config_path = test_app_with_hot_reload
        config_dir = config_path.parent

        # Perform multiple operations
        for i in range(5):
            client_with_hot_reload.post(
                "/api/servers",
                json={"name": f"temp-server-{i}", "config": {"command": "echo", "args": ["test"]}},
            )

        # Check for temp files
        temp_files = list(config_dir.glob("*.tmp"))
        assert len(temp_files) == 0, f"Temp files left behind: {temp_files}"

    def test_config_valid_json_after_write(self, client_with_hot_reload, test_app_with_hot_reload):
        """Test that config file is always valid JSON."""
        _, _, _, config_path = test_app_with_hot_reload

        # Perform rapid operations
        for i in range(10):
            client_with_hot_reload.post(
                "/api/servers",
                json={"name": f"rapid-server-{i}", "config": {"command": "echo", "args": [str(i)]}},
            )

            # Verify valid JSON after each write
            with open(config_path) as f:
                content = f.read()
                # Should be valid JSON
                config = json.loads(content)
                assert "gateway" in config
                assert "mcpServers" in config


class TestSearxngHotReload:
    """Tests specifically for searxng backend addition workflow."""

    def test_add_searxng_and_reload(self, client_with_hot_reload, test_app_with_hot_reload):
        """Test complete workflow of adding searxng and reloading."""
        _, _, backend_manager, config_path = test_app_with_hot_reload

        # Add searxng server
        response = client_with_hot_reload.post(
            "/api/servers",
            json={
                "name": "searxng",
                "config": {
                    "command": "npx",
                    "args": ["-y", "mcp-searxng"],
                    "env": {"SEARXNG_URL": "http://192.168.2.109:8888"},
                },
            },
        )

        assert response.status_code == 200

        # Trigger reload
        response = client_with_hot_reload.post("/api/reload")
        assert response.status_code == 200

        # Verify config contains searxng
        with open(config_path) as f:
            config = json.load(f)

        assert "searxng" in config["mcpServers"]
        assert config["mcpServers"]["searxng"]["env"]["SEARXNG_URL"] == "http://192.168.2.109:8888"

    def test_searxng_env_vars_preserved(self, client_with_hot_reload, test_app_with_hot_reload):
        """Test that searxng environment variables are preserved through reload."""
        _, _, _, config_path = test_app_with_hot_reload

        # Add server with env vars
        client_with_hot_reload.post(
            "/api/servers",
            json={
                "name": "searxng",
                "config": {
                    "command": "npx",
                    "args": ["-y", "mcp-searxng"],
                    "env": {
                        "SEARXNG_URL": "http://192.168.2.109:8888",
                        "CUSTOM_VAR": "custom_value",
                    },
                },
            },
        )

        # Modify something else
        client_with_hot_reload.put(
            "/api/servers/memory",
            json={
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
                "disabledTools": ["search"],
            },
        )

        # Reload
        client_with_hot_reload.post("/api/reload")

        # Verify env vars still present
        with open(config_path) as f:
            config = json.load(f)

        assert config["mcpServers"]["searxng"]["env"]["SEARXNG_URL"] == "http://192.168.2.109:8888"
        assert config["mcpServers"]["searxng"]["env"]["CUSTOM_VAR"] == "custom_value"


class TestHotReloadManager:
    """Tests for HotReloadManager class."""

    @pytest.mark.asyncio
    async def test_hot_reload_manager_start_stop(self, temp_config_file):
        """Test hot reload manager lifecycle."""
        backend_manager = MagicMock()
        config_loader = MagicMock()
        reconnect_callback = MagicMock()

        manager = HotReloadManager(
            config_path=temp_config_file,
            backend_manager=backend_manager,
            config_loader=config_loader,
            reconnect_callback=reconnect_callback,
        )

        # Start
        await manager.start(use_polling=True)
        assert manager.watcher is not None

        # Stop
        await manager.stop()
        assert manager.watcher is None

    @pytest.mark.asyncio
    async def test_hot_reload_triggers_callback(self, temp_config_file):
        """Test that file changes trigger reload callback."""
        callback_called = False

        async def mock_reconnect(config):
            nonlocal callback_called
            callback_called = True

        backend_manager = MagicMock()
        backend_manager.disconnect_all = MagicMock()

        manager = HotReloadManager(
            config_path=temp_config_file,
            backend_manager=backend_manager,
            config_loader=lambda p: {"gateway": {}, "mcpServers": {}},
            reconnect_callback=mock_reconnect,
        )

        # Manually trigger reload
        await manager._reload_config()

        assert callback_called or backend_manager.disconnect_all.called
