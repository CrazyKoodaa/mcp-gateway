"""Test to reproduce the exact bug where args are lost.

The bug appears to be in the admin dashboard JavaScript where:
1. When editing a filesystem server, paths are filtered out from args display
2. When saving, if toolsSectionVisible is false, folders aren't added back
3. This results in paths being lost

This test simulates what the backend receives when this bug occurs.
"""

import json
import pytest
from pathlib import Path

from mcp_gateway.admin import ConfigManager
from mcp_gateway.config import load_config


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temp config with filesystem server that has path args."""
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
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"],
                "disabledTools": [],
            }
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config, indent=2))
    return config_file


@pytest.mark.asyncio
async def test_bug_losing_path_args(temp_config_file):
    """Simulate the bug: dashboard sends update without path args.
    
    This mimics what happens when the JavaScript bug causes paths to be lost.
    """
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # Original has path args
    original = config_manager.gateway_config.servers["filesystem"]
    print(f"Original args: {original.args}")
    assert "/home/user/projects" in original.args
    
    # BUG: Dashboard sends update WITHOUT the path because tools section wasn't visible
    # This is what the buggy JavaScript sends
    buggy_update = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],  # Missing /home/user/projects!
        "disabledTools": [],
    }
    
    # Apply the buggy update
    await config_manager.update_server("filesystem", buggy_update)
    await config_manager.save()
    
    # Reload
    reloaded = load_config(temp_config_file)
    updated = reloaded.servers["filesystem"]
    print(f"Updated args (BUG): {updated.args}")
    
    # The path is lost - this demonstrates the bug
    # NOTE: The backend correctly saves what it receives. The bug is in the dashboard
    # not sending the complete args when tools section isn't visible.
    assert "/home/user/projects" not in updated.args, \
        "This demonstrates the bug - path was lost"


@pytest.mark.asyncio
async def test_correct_update_keeps_path_args(temp_config_file):
    """Show that correct update preserves path args."""
    gateway_config = load_config(temp_config_file)
    config_manager = ConfigManager(temp_config_file, gateway_config)
    
    # CORRECT: Dashboard sends update WITH the path
    correct_update = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects", "/tmp"],
        "disabledTools": [],
    }
    
    await config_manager.update_server("filesystem", correct_update)
    await config_manager.save()
    
    # Reload
    reloaded = load_config(temp_config_file)
    updated = reloaded.servers["filesystem"]
    print(f"Updated args (CORRECT): {updated.args}")
    
    # Both paths preserved
    assert "/home/user/projects" in updated.args
    assert "/tmp" in updated.args


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
