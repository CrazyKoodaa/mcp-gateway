"""Integration test for admin API args persistence bug."""

import json
import pytest
import asyncio
from pathlib import Path

from mcp_gateway.admin import ConfigManager, validate_server_config
from mcp_gateway.config import load_config


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file with a filesystem server."""
    config = {
        "gateway": {
            "host": "127.0.0.1",
            "port": 3000,
            "logLevel": "INFO",
            "enableNamespacing": True,
            "namespaceSeparator": "__",
        },
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "disabledTools": [],
            }
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config, indent=2))
    return config_file


@pytest.mark.asyncio
async def test_update_filesystem_server_args(temp_config_file):
    """Test updating a filesystem server args via admin API flow.
    
    This mimics what happens when user edits a server in the admin dashboard
    and adds/modifies arguments.
    """
    # Initial load (like gateway startup)
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # Verify initial state
    server = config_manager.gateway_config.servers.get("filesystem")
    assert server.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    
    # Simulate admin API receiving update request
    # User adds a new folder path and keeps existing args
    update_config = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp", "/home"],
        "disabledTools": [],
    }
    
    # Validate (like admin API does)
    is_valid, error = validate_server_config(update_config)
    assert is_valid, f"Validation failed: {error}"
    
    # Update server (like admin API does)
    await config_manager.update_server("filesystem", update_config)
    await config_manager.save()
    
    # Reload config (like hot reload would do)
    reloaded_config = load_config(temp_config_file)
    
    # Verify args were persisted
    updated_server = reloaded_config.servers.get("filesystem")
    print(f"Original args: {server.args}")
    print(f"Updated args: {updated_server.args}")
    
    assert updated_server.args == update_config["args"], (
        f"Args not persisted! Expected {update_config['args']}, got {updated_server.args}"
    )


@pytest.mark.asyncio
async def test_update_removes_all_args(temp_config_file):
    """Test that removing all args works correctly."""
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # Update with empty args
    update_config = {
        "command": "npx",
        "args": [],
        "disabledTools": [],
    }
    
    await config_manager.update_server("filesystem", update_config)
    await config_manager.save()
    
    # Reload and verify
    reloaded_config = load_config(temp_config_file)
    updated_server = reloaded_config.servers.get("filesystem")
    
    assert updated_server.args == [], f"Expected empty args, got {updated_server.args}"


@pytest.mark.asyncio
async def test_update_preserves_env_vars(temp_config_file):
    """Test that updating args doesn't affect env vars."""
    # First add env vars
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    update_config = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {"NODE_ENV": "production"},
        "disabledTools": [],
    }
    
    await config_manager.update_server("filesystem", update_config)
    await config_manager.save()
    
    # Now update args only
    update_config2 = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp", "/var"],
        "env": {"NODE_ENV": "production"},  # Keep same env
        "disabledTools": [],
    }
    
    await config_manager.update_server("filesystem", update_config2)
    await config_manager.save()
    
    # Reload and verify both args and env
    reloaded_config = load_config(temp_config_file)
    updated_server = reloaded_config.servers.get("filesystem")
    
    assert updated_server.args == update_config2["args"]
    assert updated_server.env == {"NODE_ENV": "production"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
