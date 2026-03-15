"""Tests for mcp_gateway.access_control module."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.access_control import (
    AccessControlManager,
    AccessGrant,
    AccessRequest,
    AccessRequestApprove,
    AccessRequestCreate,
    AccessRequestStatus,
    init_access_control,
)


class TestAccessRequestStatus:
    """Tests for AccessRequestStatus enum."""
    
    def test_status_values(self):
        """Test all status values."""
        assert AccessRequestStatus.PENDING.value == "pending"
        assert AccessRequestStatus.APPROVED.value == "approved"
        assert AccessRequestStatus.DENIED.value == "denied"
        assert AccessRequestStatus.EXPIRED.value == "expired"


class TestAccessRequest:
    """Tests for AccessRequest dataclass."""
    
    def test_request_creation(self):
        """Test creating an access request."""
        now = datetime.now(timezone.utc)
        req = AccessRequest(
            id="req-123",
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            code="ABCD-1234",
            status=AccessRequestStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            metadata={"reason": "Configure SSH"},
        )
        
        assert req.id == "req-123"
        assert req.mcp_name == "filesystem"
        assert req.tool_name == "read_file"
        assert req.path == "/etc/ssh/sshd_config"
        assert req.code == "ABCD-1234"
        assert req.status == AccessRequestStatus.PENDING
        assert req.metadata == {"reason": "Configure SSH"}


class TestAccessGrant:
    """Tests for AccessGrant dataclass."""
    
    def test_grant_creation(self):
        """Test creating an access grant."""
        now = datetime.now(timezone.utc)
        grant = AccessGrant(
            id="grant-123",
            request_id="req-123",
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh",
            granted_at=now,
            expires_at=now + timedelta(minutes=5),
            duration_minutes=5,
            approved_by="cli",
        )
        
        assert grant.id == "grant-123"
        assert grant.mcp_name == "filesystem"
        assert grant.path == "/etc/ssh"
        assert grant.duration_minutes == 5
        assert grant.approved_by == "cli"


class TestAccessControlManager:
    """Tests for AccessControlManager class."""
    
    @pytest.fixture
    def manager(self):
        """Create an AccessControlManager instance."""
        return AccessControlManager(
            request_timeout_minutes=10,
            default_grant_duration=1,
            cleanup_interval_seconds=60,
        )
    
    def test_initialization(self, manager):
        """Test AccessControlManager initialization."""
        assert manager.request_timeout_minutes == 10
        assert manager.default_grant_duration == 1
        assert manager.cleanup_interval_seconds == 60
        assert manager._pending_requests == {}
        assert manager._grants == {}
    
    @pytest.mark.asyncio
    async def test_start_stop(self, manager):
        """Test starting and stopping the manager."""
        manager.start()
        assert manager._cleanup_task is not None
        
        manager.stop()
        assert manager._cleanup_task is None
    
    def test_generate_code_format(self, manager):
        """Test approval code format."""
        code = manager._generate_code()
        
        # Should be like "ABCD-1234"
        assert len(code) == 9
        assert code[4] == "-"
        assert code[:4].isalpha()
        assert code[:4].isupper()
        assert code[5:].isdigit()
    
    def test_generate_id(self, manager):
        """Test ID generation."""
        id1 = manager._generate_id()
        id2 = manager._generate_id()
        
        assert id1 != id2
        assert len(id1) > 0
    
    def test_normalize_path(self, manager):
        """Test path normalization."""
        # These tests depend on the filesystem
        # Just verify it doesn't crash
        normalized = manager._normalize_path("/tmp/test")
        assert isinstance(normalized, str)
        assert len(normalized) > 0
    
    def test_is_path_allowed_exact_match(self, manager):
        """Test path check with exact match."""
        allowed = ["/home/user/projects"]
        requested = "/home/user/projects"
        
        result = manager._is_path_allowed(requested, allowed)
        assert result is True
    
    def test_is_path_allowed_subdirectory(self, manager):
        """Test path check with subdirectory."""
        allowed = ["/home/user"]
        requested = "/home/user/projects/myfile.txt"
        
        result = manager._is_path_allowed(requested, allowed)
        assert result is True
    
    def test_is_path_allowed_not_allowed(self, manager):
        """Test path check with disallowed path."""
        allowed = ["/home/user"]
        requested = "/etc/passwd"
        
        result = manager._is_path_allowed(requested, allowed)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_access_allowed_path(self, manager):
        """Test access check with allowed path."""
        allowed_paths = ["/home/user"]
        
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/home/user/file.txt",
            allowed_paths=allowed_paths,
        )
        
        assert allowed is True
        assert code is None
    
    @pytest.mark.asyncio
    async def test_check_access_not_allowed_creates_request(self, manager):
        """Test access check creates request for non-allowed path."""
        allowed_paths = ["/home/user"]
        
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=allowed_paths,
        )
        
        assert allowed is False
        assert code is not None
        assert code in manager._pending_requests
    
    @pytest.mark.asyncio
    async def test_check_access_existing_pending_request(self, manager):
        """Test access check returns existing pending request."""
        allowed_paths = ["/home/user"]
        
        # First request
        allowed1, code1 = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=allowed_paths,
        )
        
        # Second request for same path
        allowed2, code2 = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=allowed_paths,
        )
        
        assert code1 == code2  # Same request returned
    
    @pytest.mark.asyncio
    async def test_approve_request_success(self, manager):
        """Test approving a request."""
        # Create a request first
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=[],
        )
        
        success, message, grant = await manager.approve_request(
            code=code,
            duration_minutes=5,
            approved_by="cli",
        )
        
        assert success is True
        assert grant is not None
        assert grant.mcp_name == "filesystem"
        assert grant.duration_minutes == 5
        assert grant.approved_by == "cli"
    
    @pytest.mark.asyncio
    async def test_approve_request_invalid_code(self, manager):
        """Test approving with invalid code."""
        success, message, grant = await manager.approve_request(
            code="INVALID",
            duration_minutes=5,
        )
        
        assert success is False
        assert grant is None
        assert "Invalid" in message
    
    @pytest.mark.asyncio
    async def test_deny_request_success(self, manager):
        """Test denying a request."""
        # Create a request
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=[],
        )
        
        success, message = await manager.deny_request(code, denied_by="cli")
        
        assert success is True
        assert manager._pending_requests[code].status == AccessRequestStatus.DENIED
    
    @pytest.mark.asyncio
    async def test_get_pending_requests(self, manager):
        """Test getting pending requests."""
        # Create some requests
        await manager.check_access("fs1", "read", "/etc/a", [])
        await manager.check_access("fs2", "read", "/etc/b", [])
        
        pending = manager.get_pending_requests()
        
        assert len(pending) == 2
    
    @pytest.mark.asyncio
    async def test_get_active_grants(self, manager):
        """Test getting active grants."""
        # Create and approve a request
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=[],
        )
        
        await manager.approve_request(code, duration_minutes=5)
        
        active = await manager.get_active_grants()
        
        assert len(active) == 1
    
    @pytest.mark.asyncio
    async def test_revoke_grant(self, manager):
        """Test revoking a grant."""
        # Create and approve
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=[],
        )
        
        success, message, grant = await manager.approve_request(code, duration_minutes=5)
        
        # Revoke
        result = await manager.revoke_grant(grant.id)
        assert result is True
        
        # Should be expired now
        assert grant.expires_at <= datetime.now(timezone.utc)
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_requests(self, manager):
        """Test cleanup of expired requests."""
        # Create a request
        allowed, code = await manager.check_access(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            allowed_paths=[],
        )
        
        # Manually expire it
        request = manager._pending_requests[code]
        request.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        # Run cleanup
        await manager._cleanup_expired()
        
        # Should be marked as expired
        assert request.status == AccessRequestStatus.EXPIRED
    
    def test_notification_callback(self, manager):
        """Test notification callback registration and triggering."""
        callback = MagicMock()
        
        manager.register_notification_callback(callback)
        manager._notify("test_event", {"key": "value"})
        
        callback.assert_called_once_with("test_event", {"key": "value"})
    
    @pytest.mark.asyncio
    async def test_async_notification_callback(self, manager):
        """Test async notification callback."""
        callback = AsyncMock()
        
        manager.register_notification_callback(callback)
        manager._notify("test_event", {"key": "value"})
        
        # Give async task time to run
        await asyncio.sleep(0.1)
        
        callback.assert_called_once_with("test_event", {"key": "value"})


class TestInitAccessControl:
    """Tests for init_access_control function."""
    
    @pytest.mark.asyncio
    async def test_init_access_control(self):
        """Test initialization of global access control."""
        from mcp_gateway import access_control as ac_module
        
        # Reset global
        ac_module.access_control = None
        
        manager = init_access_control(
            request_timeout_minutes=5,
            default_grant_duration=2,
        )
        
        assert manager is not None
        assert ac_module.access_control is manager
        assert manager.request_timeout_minutes == 5
        assert manager.default_grant_duration == 2
        
        manager.stop()  # Cleanup


class TestAccessRequestModels:
    """Tests for Pydantic models."""
    
    def test_access_request_create(self):
        """Test AccessRequestCreate model."""
        req = AccessRequestCreate(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/ssh/sshd_config",
            metadata={"reason": "Configure SSH"},
        )
        
        assert req.mcp_name == "filesystem"
        assert req.path == "/etc/ssh/sshd_config"
        assert req.metadata == {"reason": "Configure SSH"}
    
    def test_access_request_create_defaults(self):
        """Test AccessRequestCreate with defaults."""
        req = AccessRequestCreate(
            mcp_name="filesystem",
            tool_name="read_file",
            path="/etc/config",
        )
        
        assert req.metadata == {}
    
    def test_access_request_approve(self):
        """Test AccessRequestApprove model."""
        req = AccessRequestApprove(
            code="ABCD-1234",
            duration_minutes=5,
            approved_by="web",
        )
        
        assert req.code == "ABCD-1234"
        assert req.duration_minutes == 5
        assert req.approved_by == "web"
    
    def test_access_request_approve_defaults(self):
        """Test AccessRequestApprove with defaults."""
        req = AccessRequestApprove(code="ABCD-1234")
        
        assert req.code == "ABCD-1234"
        assert req.duration_minutes == 1
        assert req.approved_by == "cli"
