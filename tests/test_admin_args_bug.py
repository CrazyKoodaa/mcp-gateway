"""Test to reproduce the bug where args are not saved when updating via admin API."""

import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from mcp_gateway.admin import ConfigManager, validate_server_config
from mcp_gateway.config import load_config


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config = {
        "gateway": {
            "host": "127.0.0.1",
            "port": 3000,
            "logLevel": "INFO",
            "enableNamespacing": True,
            "namespaceSeparator": "__",
        },
        "mcpServers": {
            "test_server": {
                "command": "npx",
                "args": ["-y", "original-package"],
                "disabledTools": [],
            }
        },
    }
    config_file = tmp_path / "test_config.json"
    config_file.write_text(json.dumps(config, indent=2))
    return config_file


@pytest.mark.asyncio
async def test_update_server_args_persisted(temp_config_file):
    """Test that args are persisted when updating a server via admin API.
    
    This reproduces the bug where adding an arg to a server via the admin dashboard
    doesn't get saved.
    """
    # Load the config
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # Verify original args
    original_server = config_manager.gateway_config.servers.get("test_server")
    assert original_server is not None
    assert original_server.args == ["-y", "original-package"]
    
    # Simulate what the admin API does when updating args
    new_config = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "disabledTools": [],
    }
    
    # Validate the config
    is_valid, error = validate_server_config(new_config)
    assert is_valid, f"Config validation failed: {error}"
    
    # Update the server (this is what the admin API calls)
    await config_manager.update_server("test_server", new_config)
    await config_manager.save()
    
    # Reload the config to verify persistence
    gateway_config2 = load_config(temp_config_file)
    config_manager2 = ConfigManager(temp_config_file, gateway_config2)
    
    updated_server = config_manager2.gateway_config.servers.get("test_server")
    assert updated_server is not None
    
    # THIS IS THE BUG: args should be updated but they might not be
    print(f"Original args: {original_server.args}")
    print(f"Expected args: {new_config['args']}")
    print(f"Actual args: {updated_server.args}")
    
    assert updated_server.args == new_config["args"], (
        f"Args not persisted! Expected {new_config['args']}, got {updated_server.args}"
    )


@pytest.mark.asyncio
async def test_update_server_adds_new_arg(temp_config_file):
    """Test that adding a new arg to an existing server works."""
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # Add a new arg
    new_config = {
        "command": "npx",
        "args": ["-y", "original-package", "--new-flag"],
        "disabledTools": [],
    }
    
    await config_manager.update_server("test_server", new_config)
    await config_manager.save()
    
    # Reload and verify
    gateway_config2 = load_config(temp_config_file)
    config_manager2 = ConfigManager(temp_config_file, gateway_config2)
    
    updated_server = config_manager2.gateway_config.servers.get("test_server")
    print(f"Args after adding new arg: {updated_server.args}")
    
    assert "--new-flag" in updated_server.args, (
        f"New arg not added! Args: {updated_server.args}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
