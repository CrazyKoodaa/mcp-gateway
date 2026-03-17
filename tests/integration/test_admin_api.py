"""Integration tests for Admin API endpoints."""

from __future__ import annotations

import json

# Fixtures moved to conftest.py for sharing across test files


class TestListServers:
    """Tests for GET /api/servers endpoint."""

    def test_list_servers_success(self, client):
        """Test successful server listing."""
        response = client.get("/api/servers")

        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        assert len(data["servers"]) == 2

        # Check server names
        names = [s["name"] for s in data["servers"]]
        assert "memory" in names
        assert "time" in names

    def test_list_servers_returns_correct_fields(self, client):
        """Test that server objects have expected fields."""
        response = client.get("/api/servers")

        assert response.status_code == 200
        data = response.json()

        for server in data["servers"]:
            assert "name" in server
            assert "command" in server
            assert "args" in server
            assert "url" in server
            assert "type" in server
            assert "disabledTools" in server
            assert "availableTools" in server


class TestCreateServer:
    """Tests for POST /api/servers endpoint."""

    def test_create_stdio_server(self, client, test_app):
        """Test creating a new stdio server."""
        _, config_manager, _, config_path = test_app

        response = client.post(
            "/api/servers",
            json={
                "name": "filesystem",
                "config": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "disabledTools": [],
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server"]["name"] == "filesystem"

        # Verify config was saved to disk
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "filesystem" in saved_config["mcpServers"]
        assert saved_config["mcpServers"]["filesystem"]["command"] == "npx"
        assert saved_config["mcpServers"]["filesystem"]["args"] == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/tmp",
        ]

    def test_create_remote_server(self, client, test_app):
        """Test creating a new remote server."""
        _, _, _, config_path = test_app

        response = client.post(
            "/api/servers",
            json={
                "name": "remote-mcp",
                "config": {
                    "url": "https://example.com/mcp",
                    "type": "streamable-http",
                    "headers": {"Authorization": "Bearer token123"},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify saved config
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "remote-mcp" in saved_config["mcpServers"]
        assert saved_config["mcpServers"]["remote-mcp"]["url"] == "https://example.com/mcp"

    def test_create_server_with_env_vars(self, client, test_app):
        """Test creating server with environment variables."""
        _, _, _, config_path = test_app

        response = client.post(
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

        # Verify env vars saved correctly
        with open(config_path) as f:
            saved_config = json.load(f)

        assert (
            saved_config["mcpServers"]["searxng"]["env"]["SEARXNG_URL"]
            == "http://192.168.2.109:8888"
        )

    def test_create_duplicate_server_fails(self, client):
        """Test that creating duplicate server fails."""
        response = client.post(
            "/api/servers",
            json={
                "name": "memory",  # Already exists
                "config": {"command": "npx", "args": ["-y", "some-package"]},
            },
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_create_server_missing_name(self, client):
        """Test that server creation fails without name."""
        response = client.post(
            "/api/servers", json={"config": {"command": "npx", "args": ["-y", "some-package"]}}
        )

        assert response.status_code == 400
        assert "name is required" in response.json()["detail"].lower()

    def test_create_server_invalid_config(self, client):
        """Test that server creation fails with invalid config."""
        response = client.post(
            "/api/servers",
            json={
                "name": "invalid-server",
                "config": {
                    # Missing both command and url
                    "disabledTools": []
                },
            },
        )

        assert response.status_code == 400


class TestUpdateServer:
    """Tests for PUT /api/servers/{name} endpoint."""

    def test_update_server_args(self, client, test_app):
        """Test updating server arguments."""
        _, _, _, config_path = test_app

        response = client.put(
            "/api/servers/time",
            json={
                "command": "uvx",
                "args": ["mcp-server-time", "--local-timezone=America/New_York"],
                "disabledTools": ["convert_time"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify config updated
        with open(config_path) as f:
            saved_config = json.load(f)

        assert saved_config["mcpServers"]["time"]["args"] == [
            "mcp-server-time",
            "--local-timezone=America/New_York",
        ]

    def test_update_server_disabled_tools(self, client, test_app):
        """Test updating disabled tools."""
        _, _, _, config_path = test_app

        response = client.put(
            "/api/servers/memory",
            json={
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
                "disabledTools": ["add", "search"],
            },
        )

        assert response.status_code == 200

        # Verify disabled tools updated
        with open(config_path) as f:
            saved_config = json.load(f)

        assert saved_config["mcpServers"]["memory"]["disabledTools"] == ["add", "search"]

    def test_update_nonexistent_server(self, client):
        """Test updating non-existent server fails."""
        response = client.put(
            "/api/servers/nonexistent", json={"command": "npx", "args": ["-y", "some-package"]}
        )

        assert response.status_code == 404

    def test_update_server_invalid_config(self, client):
        """Test that invalid config fails validation."""
        response = client.put(
            "/api/servers/time",
            json={
                # Invalid: empty command
                "command": "",
                "args": [],
            },
        )

        assert response.status_code == 400


class TestDeleteServer:
    """Tests for DELETE /api/servers/{name} endpoint."""

    def test_delete_server(self, client, test_app):
        """Test deleting a server."""
        _, _, _, config_path = test_app

        response = client.delete("/api/servers/time")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "time" in data["message"]

        # Verify server removed from config
        with open(config_path) as f:
            saved_config = json.load(f)

        assert "time" not in saved_config["mcpServers"]
        assert "memory" in saved_config["mcpServers"]  # Other server still there

    def test_delete_nonexistent_server(self, client):
        """Test deleting non-existent server fails."""
        response = client.delete("/api/servers/nonexistent")

        assert response.status_code == 404


class TestReloadConfig:
    """Tests for POST /api/reload endpoint."""

    def test_reload_config(self, client):
        """Test config reload endpoint."""
        response = client.post("/api/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "reloaded" in data["message"].lower()


class TestServerTools:
    """Tests for GET /api/servers/{name}/tools endpoint."""

    def test_get_server_tools(self, client):
        """Test getting tools for a server."""
        response = client.get("/api/servers/memory/tools")

        # Backend may not be connected, so 404 is valid
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert "tools" in data
            assert "disabledTools" in data

    def test_get_tools_nonexistent_server(self, client):
        """Test getting tools for non-existent server."""
        response = client.get("/api/servers/nonexistent/tools")

        assert response.status_code == 404
