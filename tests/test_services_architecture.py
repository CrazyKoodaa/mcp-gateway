"""Tests for the refactored service-based architecture.

These tests demonstrate proper testing of the new service layer:
- PathSecurityService with platform detection
- ConfigApprovalService with race condition tests
- AuditService with structured logging
- Integration between services
"""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Import new services
from mcp_gateway.services import (
    AuditService,
    ConfigApprovalService,
    PathSecurityService,
)
from mcp_gateway.services.config_approval_service import (
    ApprovalResult,
    ApprovalStatus,
    ConfigChangeGrant,
    ConfigChangeRequest,
    PendingRequestInfo,
)
from mcp_gateway.services.path_security_service import PathCheckResult
from mcp_gateway.rate_limiter import MemoryRateLimiter, RateLimitResult


# =============================================================================
# PathSecurityService Tests
# =============================================================================

class TestPathSecurityService:
    """Tests for PathSecurityService with platform awareness."""
    
    def test_linux_platform_detection(self):
        """Service should detect Linux platform."""
        with patch("sys.platform", "linux"):
            service = PathSecurityService()
            assert service.platform == "linux"
            assert "/etc" in service._patterns
    
    def test_windows_platform_detection(self):
        """Service should detect Windows platform."""
        with patch("sys.platform", "win32"):
            service = PathSecurityService()
            assert service.platform == "windows"
            # Raw strings are stored with escaped backslashes
            assert r"C:\\Windows" in service._patterns
    
    def test_macos_platform_detection(self):
        """Service should detect macOS platform."""
        with patch("sys.platform", "darwin"):
            service = PathSecurityService()
            assert service.platform == "darwin"
            assert "/System" in service._patterns
    
    def test_explicit_platform_override(self):
        """Platform can be explicitly set."""
        service = PathSecurityService(platform="windows")
        assert service.platform == "windows"
        # Even if running on Linux
    
    def test_check_path_returns_result_object(self):
        """check_path returns PathCheckResult with full info."""
        service = PathSecurityService(platform="linux")
        result = service.check_path("/etc/passwd")
        
        assert isinstance(result, PathCheckResult)
        assert result.path == "/etc/passwd"
        assert result.is_sensitive is True
        assert result.matched_pattern == "/etc"
        assert result.platform == "linux"
    
    def test_check_path_safe_path(self):
        """check_path returns False for safe paths."""
        service = PathSecurityService(platform="linux")
        result = service.check_path("/home/user/projects")
        
        assert result.is_sensitive is False
        assert result.matched_pattern is None
    
    def test_check_paths_batch(self):
        """check_paths processes multiple paths."""
        service = PathSecurityService(platform="linux")
        paths = ["/etc", "/home/user", "/sys", "/tmp/work"]
        results = service.check_paths(paths)
        
        assert len(results) == 4
        assert results[0].is_sensitive is True  # /etc
        assert results[1].is_sensitive is False  # /home/user
        assert results[2].is_sensitive is True  # /sys
        assert results[3].is_sensitive is True  # /tmp/work
    
    def test_get_sensitive_paths_filter(self):
        """get_sensitive_paths returns only sensitive paths."""
        service = PathSecurityService(platform="linux")
        paths = ["/etc", "/home/user", "/sys", "/home/user/work"]
        sensitive = service.get_sensitive_paths(paths)
        
        assert "/etc" in sensitive
        assert "/sys" in sensitive
        assert "/home/user" not in sensitive
        assert "/home/user/work" not in sensitive
    
    def test_windows_path_format(self):
        """Windows paths with backslashes are handled."""
        service = PathSecurityService(platform="windows")
        result = service.check_path(r"C:\Windows\System32")
        assert result.is_sensitive is True
    
    def test_root_path_special_handling(self):
        """Root path is handled specially."""
        service = PathSecurityService(platform="linux")
        result = service.check_path("/")
        assert result.is_sensitive is True
        # But /home should not match root
        result2 = service.check_path("/home")
        assert result2.is_sensitive is False


# =============================================================================
# AuditService Tests
# =============================================================================

class TestAuditService:
    """Tests for AuditService with structured logging."""
    
    def test_audit_event_creation(self, tmp_path: Path):
        """Audit events are written to file."""
        log_file = tmp_path / "audit.log"
        service = AuditService.with_file_handler(log_file)
        
        service.log_config_change_requested(
            server_name="filesystem",
            sensitive_path="/etc",
            approval_code="ABCD-1234",
            actor="web",
        )
        
        # Flush and check
        service.close()
        
        content = log_file.read_text()
        event = json.loads(content.strip())
        
        assert event["event_type"] == "config_change.requested"
        assert event["actor"] == "web"
        assert event["data"]["server_name"] == "filesystem"
        assert event["data"]["approval_code"] == "ABCD-1234"
        assert "chain_hash" in event
        assert "timestamp" in event
    
    def test_chain_hash_integrity(self, tmp_path: Path):
        """Chain hashes form a chain for tamper detection."""
        log_file = tmp_path / "audit.log"
        service = AuditService.with_file_handler(log_file)
        
        # Log two events
        service.log_config_change_requested("s1", "/etc", "CODE1", "web")
        service.log_config_change_requested("s2", "/sys", "CODE2", "web")
        service.close()
        
        # Read events
        lines = log_file.read_text().strip().split("\n")
        event1 = json.loads(lines[0])
        event2 = json.loads(lines[1])
        
        # Chain hashes should be different
        assert event1["chain_hash"] != event2["chain_hash"]
        # Both should have hashes
        assert len(event1["chain_hash"]) == 32
        assert len(event2["chain_hash"]) == 32


# =============================================================================
# ConfigApprovalService Tests
# =============================================================================

@pytest.fixture
def mock_audit():
    """Mock audit service."""
    return MagicMock(spec=AuditService)


@pytest.fixture
def approval_service(mock_audit):
    """Configured approval service."""
    service = ConfigApprovalService(
        audit_service=mock_audit,
        request_timeout_minutes=10,
        default_grant_duration=1,
    )
    yield service
    # Cleanup is handled automatically


class TestConfigApprovalService:
    """Tests for ConfigApprovalService."""
    
    @pytest.mark.asyncio
    async def test_safe_path_no_approval_needed(self, approval_service, mock_audit):
        """Safe paths don't require approval."""
        result = await approval_service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": ["/home/user"]},
            new_config={"args": ["/home/user", "/home/user/work"]},
        )
        
        assert isinstance(result, ApprovalResult)
        assert result.requires_approval is False
        assert result.error is None
        assert "/home/user/work" in result.safe_paths
    
    @pytest.mark.asyncio
    async def test_sensitive_path_requires_approval(self, approval_service, mock_audit):
        """Sensitive paths require approval."""
        result = await approval_service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": ["/home/user"]},
            new_config={"args": ["/home/user", "/etc"]},
        )
        
        assert result.requires_approval is True
        assert len(result.pending_requests) == 1
        assert result.pending_requests[0].path == "/etc"
        # safe_paths only contains newly added safe paths (not existing ones)
    
    @pytest.mark.asyncio
    async def test_multiple_sensitive_paths_multiple_requests(self, approval_service):
        """Each sensitive path gets its own approval code."""
        result = await approval_service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": []},
            new_config={"args": ["/etc", "/sys", "/home/user"]},
        )
        
        assert result.requires_approval is True
        assert len(result.pending_requests) == 2  # /etc and /sys
        paths = [r.path for r in result.pending_requests]
        assert "/etc" in paths
        assert "/sys" in paths
        assert "/home/user" in result.safe_paths
    
    @pytest.mark.asyncio
    async def test_invalid_config_returns_error(self, approval_service):
        """Invalid config returns error without creating request."""
        # Create a mock validator that always fails
        class FailingValidator:
            def validate(self, config):
                return (False, "Invalid config")
        
        approval_service._config_validator = FailingValidator()
        
        result = await approval_service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": []},
            new_config={"args": ["/etc"]},
        )
        
        assert result.requires_approval is False
        assert result.error == "Invalid config"
        assert len(approval_service.get_pending_requests()) == 0


class TestConfigApprovalRaceConditions:
    """Tests for race condition protection."""
    
    @pytest.mark.asyncio
    async def test_approve_with_checksum_mismatch_fails(self, mock_audit):
        """Approval fails if config changed since request."""
        service = ConfigApprovalService(audit_service=mock_audit)
        
        # Create request
        original = {"args": ["/home/user"]}
        new = {"args": ["/home/user", "/etc"]}
        
        await service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config=original,
            new_config=new,
        )
        
        requests = service.get_pending_requests()
        assert len(requests) == 1
        code = requests[0].code
        
        # Try to approve with different current config
        modified_config = {"args": ["/home/user", "/other"]}  # Different!
        
        success, message, grant = await service.approve(
            code=code,
            duration_minutes=5,
            current_config=modified_config,
        )
        
        assert success is False
        assert "changed" in message.lower()
        assert grant is None
        await service.stop()
    
    @pytest.mark.asyncio
    async def test_approve_with_matching_checksum_succeeds(self, mock_audit):
        """Approval succeeds if config matches checksum."""
        service = ConfigApprovalService(audit_service=mock_audit)
        
        original = {"args": ["/home/user"]}
        new = {"args": ["/home/user", "/etc"]}
        
        await service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config=original,
            new_config=new,
        )
        
        requests = service.get_pending_requests()
        code = requests[0].code
        
        # Approve with same config
        success, message, grant = await service.approve(
            code=code,
            duration_minutes=5,
            current_config=original,  # Same as when request created
        )
        
        assert success is True
        assert grant is not None
        await service.stop()


class TestConfigApprovalCleanup:
    """Tests for cleanup of expired requests and grants."""
    
    @pytest.mark.asyncio
    async def test_expired_requests_marked_expired(self, mock_audit):
        """Expired pending requests are marked EXPIRED."""
        service = ConfigApprovalService(
            audit_service=mock_audit,
            request_timeout_minutes=10,  # Normal timeout
        )
        
        # Create request
        await service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": []},
            new_config={"args": ["/etc"]},
        )
        
        # Get the request before expiring it
        request = service.get_pending_requests()[0]
        
        # Force expiration by setting expires_at to the past
        request.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        # Run cleanup
        await service._cleanup_expired()
        
        # After cleanup, the request status should be EXPIRED
        assert request.status == ApprovalStatus.EXPIRED
        await service.stop()
    
    @pytest.mark.asyncio
    async def test_expired_grants_trigger_callbacks(self, mock_audit):
        """Expired grants trigger revert and restart callbacks."""
        service = ConfigApprovalService(audit_service=mock_audit)
        
        revert_mock = AsyncMock()
        restart_mock = AsyncMock()
        service.set_revert_callback(revert_mock)
        service.set_restart_callback(restart_mock)
        
        # Create and approve
        await service.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": ["/home/user"]},
            new_config={"args": ["/home/user", "/etc"]},
        )
        
        request = service.get_pending_requests()[0]
        await service.approve(request.code, duration_minutes=5)
        
        # Force expiration
        grant = service.get_active_grants()[0]
        grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        # Run cleanup
        await service._cleanup_expired()
        
        # Callbacks should be called
        revert_mock.assert_called_once()
        restart_mock.assert_called_once()
        await service.stop()


# =============================================================================
# Rate Limiter Tests
# =============================================================================

class TestRateLimiter:
    """Tests for rate limiting."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_limit(self):
        """Requests under limit are allowed."""
        limiter = MemoryRateLimiter(requests_per_minute=10)
        
        # First 10 requests should be allowed
        for i in range(10):
            result = await limiter.check("key1")
            assert result.allowed is True
        
        await limiter.stop()
    
    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self):
        """Requests over limit are blocked."""
        limiter = MemoryRateLimiter(
            requests_per_minute=60,  # 1 per second
            burst_size=2,
        )
        
        # Use up burst
        await limiter.check("key1")
        await limiter.check("key1")
        
        # Next should be blocked
        result = await limiter.check("key1")
        assert result.allowed is False
        assert result.retry_after > 0
        
        await limiter.stop()
    
    @pytest.mark.asyncio
    async def test_different_keys_have_separate_limits(self):
        """Each key has its own rate limit bucket."""
        limiter = MemoryRateLimiter(requests_per_minute=1, burst_size=1)
        
        # Exhaust key1
        await limiter.check("key1")
        result = await limiter.check("key1")
        assert result.allowed is False
        
        # key2 should still work
        result2 = await limiter.check("key2")
        assert result2.allowed is True
        
        await limiter.stop()
    
    @pytest.mark.asyncio
    async def test_reset_clears_limit(self):
        """Reset clears rate limit for a key."""
        limiter = MemoryRateLimiter(requests_per_minute=1, burst_size=1)
        
        # Exhaust limit
        await limiter.check("key1")
        result = await limiter.check("key1")
        assert result.allowed is False
        
        # Reset
        await limiter.reset("key1")
        
        # Should work again
        result = await limiter.check("key1")
        assert result.allowed is True
        
        await limiter.stop()


# =============================================================================
# Integration Tests
# =============================================================================

class TestServiceIntegration:
    """Integration tests between services."""
    
    @pytest.mark.asyncio
    async def test_full_approval_flow(self, tmp_path: Path):
        """Complete flow from request to approval to expiration."""
        # Setup services
        audit = AuditService.with_file_handler(tmp_path / "audit.log")
        approval = ConfigApprovalService(audit_service=audit)
        
        # Mock callbacks
        revert_mock = AsyncMock()
        restart_mock = AsyncMock()
        approval.set_revert_callback(revert_mock)
        approval.set_restart_callback(restart_mock)
        
        # 1. Create request
        result = await approval.check_config_change(
            server_name="filesystem",
            change_type="modify",
            original_config={"args": ["/home/user"]},
            new_config={"args": ["/home/user", "/etc"]},
        )
        
        assert result.requires_approval is True
        code = result.pending_requests[0].code
        
        # 2. Approve
        success, message, grant = await approval.approve(
            code=code,
            duration_minutes=5,
        )
        assert success is True
        assert grant is not None
        
        # 3. Verify audit logged
        audit.close()
        audit_content = (tmp_path / "audit.log").read_text()
        events = [json.loads(line) for line in audit_content.strip().split("\n")]
        
        assert any(e["event_type"] == "config_change.requested" for e in events)
        assert any(e["event_type"] == "config_change.approved" for e in events)
        
        # 4. Force expiration and cleanup
        grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await approval._cleanup_expired()
        
        # 5. Verify callbacks called
        revert_mock.assert_called_once()
        restart_mock.assert_called_once()
        
        await approval.stop()


# =============================================================================
# Type Safety Tests
# =============================================================================

class TestTypeSafety:
    """Tests verifying type hints are correct."""
    
    def test_path_check_result_is_frozen(self):
        """PathCheckResult is immutable."""
        result = PathCheckResult(
            path="/etc",
            is_sensitive=True,
            matched_pattern="/etc",
            platform="linux",
        )
        
        # Should not be able to modify
        with pytest.raises(AttributeError):
            result.is_sensitive = False
    
    def test_approval_result_defaults(self):
        """ApprovalResult has proper defaults."""
        result = ApprovalResult(requires_approval=True)
        
        assert result.pending_requests == []
        assert result.safe_paths == []
        assert result.error is None
