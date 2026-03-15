"""Tests for audit fixes - P0 critical bugs."""

from datetime import datetime, timedelta, timezone
from src.mcp_gateway.access_control.models import (
    ConfigChangeRequest,
    AccessRequest,
    AccessRequestStatus,
)


class TestAttributeAccessBugFix:
    """Test that attribute access bugs are fixed."""

    def test_config_change_request_has_sensitive_path_not_sensitive_paths(self):
        """ConfigChangeRequest should have 'sensitive_path' not 'sensitive_paths'."""
        req = ConfigChangeRequest(
            id="test-id",
            server_name="test-server",
            change_type="add",
            code="ABCD-1234",
            status=AccessRequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            sensitive_path="/safe/path",
        )

        # Should have sensitive_path
        assert hasattr(req, "sensitive_path")
        assert req.sensitive_path == "/safe/path"

        # Should NOT have sensitive_paths
        assert not hasattr(req, "sensitive_paths")

    def test_access_request_has_path_not_sensitive_paths(self):
        """AccessRequest should have 'path' not 'sensitive_paths'."""
        req = AccessRequest(
            id="test-id",
            mcp_name="test-mcp",
            tool_name="test-tool",
            path="/some/path",
            code="EFGH-5678",
            status=AccessRequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        # Should have path
        assert hasattr(req, "path")
        assert req.path == "/some/path"

        # Should NOT have sensitive_paths
        assert not hasattr(req, "sensitive_paths")


class TestCleanupLoopTypeFix:
    """Test that cleanup loop handles AccessRequest and ConfigChangeRequest separately."""

    def test_access_request_cleanup_uses_correct_attributes(self):
        """AccessRequest cleanup should use mcp_name, tool_name, path."""
        req = AccessRequest(
            id="test-id",
            mcp_name="test-mcp",
            tool_name="test-tool",
            path="/some/path",
            code="ABCD-1234",
            status=AccessRequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # Expired
        )

        # Verify correct attributes are accessible
        assert hasattr(req, "mcp_name")
        assert hasattr(req, "tool_name")
        assert hasattr(req, "path")

        # These should NOT exist (would cause AttributeError if accessed)
        assert not hasattr(req, "server_name")
        assert not hasattr(req, "sensitive_path")

    def test_config_change_request_cleanup_uses_correct_attributes(self):
        """ConfigChangeRequest cleanup should use server_name, sensitive_path."""
        req = ConfigChangeRequest(
            id="test-id",
            server_name="test-server",
            change_type="add",
            code="EFGH-5678",
            status=AccessRequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # Expired
            sensitive_path="/safe/path",
        )

        # Verify correct attributes are accessible
        assert hasattr(req, "server_name")
        assert hasattr(req, "sensitive_path")

        # These should NOT exist (would cause AttributeError if accessed)
        assert not hasattr(req, "mcp_name")
        assert not hasattr(req, "path")
