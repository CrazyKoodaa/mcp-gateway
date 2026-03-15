"""Test to reproduce BackendManager get_backend_diagnostics bug."""

import pytest
import asyncio
from pathlib import Path

from mcp_gateway.backends import BackendManager


@pytest.mark.asyncio
async def test_backend_manager_has_backends():
    """Test that BackendManager has _backends attribute."""
    manager = BackendManager()
    
    # This should not raise AttributeError
    assert hasattr(manager, '_backends'), "BackendManager missing _backends attribute"
    assert isinstance(manager._backends, dict), "_backends should be a dict"


@pytest.mark.asyncio
async def test_get_backend_diagnostics_exists():
    """Test that get_backend_diagnostics method works without AttributeError."""
    manager = BackendManager()
    
    # This should not raise AttributeError (was the bug)
    diagnostics = manager.get_backend_diagnostics()
    assert isinstance(diagnostics, list), "get_backend_diagnostics should return a list"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
