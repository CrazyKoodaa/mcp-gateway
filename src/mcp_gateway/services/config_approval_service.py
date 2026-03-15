"""Config approval service for managing time-bound configuration changes.

Provides granular approval workflow for sensitive path additions with
auto-revert and race condition protection.
"""

import asyncio
import hashlib
import json
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, TypeAlias

from .audit_service import AuditService
from .path_security_service import PathSecurityService


class ApprovalStatus(Enum):
    """Status of a config change approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PendingRequestInfo:
    """Information about a pending approval request.

    Attributes:
        code: The approval code (e.g., "ABCD-1234")
        path: The specific sensitive path requiring approval
    """
    code: str
    path: str


@dataclass
class ApprovalResult:
    """Result of a config change check.

    Attributes:
        requires_approval: True if any paths need approval
        pending_requests: List of pending requests for sensitive paths
        safe_paths: List of safe paths that were applied immediately
        error: Error message if validation failed
    """
    requires_approval: bool
    pending_requests: list[PendingRequestInfo] = field(default_factory=list)
    safe_paths: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ConfigChangeRequest:
    """A pending configuration change request.

    Each sensitive path gets its own request for granular approval.
    """
    id: str
    server_name: str
    change_type: str
    code: str
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    sensitive_path: str
    path_index: int
    target_args: list[str]
    original_config: dict[str, Any]
    original_config_checksum: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigChangeGrant:
    """An approved time-bound config change."""
    id: str
    request_id: str
    server_name: str
    granted_at: datetime
    expires_at: datetime
    duration_minutes: int
    approved_by: str
    sensitive_path: str
    path_index: int
    target_args: list[str]
    original_args: list[str]


# Type aliases for callbacks
ConfigRevertCallback: TypeAlias = Callable[[str, dict[str, Any]], asyncio.Future[None]]
BackendRestartCallback: TypeAlias = Callable[[str], asyncio.Future[None]]


class ConfigValidator(Protocol):
    """Protocol for config validation.

    Allows pluggable validation (admin validation, custom rules).
    """

    def validate(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Validate a configuration.

        Returns:
            Tuple of (is_valid, error_message)
        """
        ...


class ConfigApprovalService:
    """Service for managing configuration change approvals.

    Provides:
    - Granular path-level approval (each sensitive path separately)
    - Config validation before creating requests
    - Race condition protection via checksums
    - Time-bound grants with auto-revert
    - Audit logging

    Example:
        >>> service = ConfigApprovalService(audit_service=audit)
        >>> result = await service.check_config_change(
        ...     server_name="filesystem",
        ...     original_config={"args": ["/home/user"]},
        ...     new_config={"args": ["/home/user", "/etc"]},
        ... )
        >>> result.requires_approval
        True
        >>> result.pending_requests[0].path
        '/etc'
    """

    def __init__(
        self,
        audit_service: AuditService,
        path_security: PathSecurityService | None = None,
        config_validator: ConfigValidator | None = None,
        request_timeout_minutes: int = 10,
        default_grant_duration: int = 1,
        cleanup_interval_seconds: int = 60,
    ) -> None:
        """Initialize the config approval service.

        Args:
            audit_service: Service for logging audit events
            path_security: Service for detecting sensitive paths (auto-created if None)
            config_validator: Optional config validator
            request_timeout_minutes: How long pending requests remain valid
            default_grant_duration: Default approval duration in minutes
            cleanup_interval_seconds: How often to clean up expired items
        """
        self._audit = audit_service
        self._path_security = path_security or PathSecurityService()
        self._config_validator = config_validator

        self._request_timeout_minutes = request_timeout_minutes
        self._default_grant_duration = default_grant_duration
        self._cleanup_interval_seconds = cleanup_interval_seconds

        # Storage
        self._pending: dict[str, ConfigChangeRequest] = {}
        self._grants: dict[str, ConfigChangeGrant] = {}

        # Callbacks
        self._revert_callback: ConfigRevertCallback | None = None
        self._restart_callback: BackendRestartCallback | None = None

        # Cleanup task (started on first use)
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_started = False

    def _ensure_cleanup_started(self) -> None:
        """Start cleanup task if not already started."""
        if not self._cleanup_started:
            self._start_cleanup()
            self._cleanup_started = True

    def set_revert_callback(self, callback: ConfigRevertCallback) -> None:
        """Set callback for config reversion on expiration."""
        self._revert_callback = callback

    def set_restart_callback(self, callback: BackendRestartCallback) -> None:
        """Set callback for backend restart after revert."""
        self._restart_callback = callback

    def _start_cleanup(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the service and cleanup tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    @staticmethod
    def _compute_config_checksum(config: dict[str, Any]) -> str:
        """Compute SHA256 checksum of config for race detection."""
        config_str = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    @staticmethod
    def _generate_code() -> str:
        """Generate human-readable approval code (e.g., 'ABCD-1234')."""
        letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
        numbers = "".join(secrets.choice(string.digits) for _ in range(4))
        return f"{letters}-{numbers}"

    @staticmethod
    def _generate_id() -> str:
        """Generate unique ID."""
        return secrets.token_urlsafe(16)

    async def check_config_change(
        self,
        server_name: str,
        change_type: str,
        original_config: dict[str, Any],
        new_config: dict[str, Any],
    ) -> ApprovalResult:
        """Check if a config change requires approval."""
        self._ensure_cleanup_started()
        """Check if a config change requires approval.

        Validates the config, detects sensitive paths, and creates
        individual approval requests for each sensitive path.

        Args:
            server_name: Name of the server being modified
            change_type: Type of change (add, modify, remove)
            original_config: Current configuration
            new_config: Proposed new configuration

        Returns:
            ApprovalResult with pending requests and safe paths
        """
        # Validate config first
        if self._config_validator:
            is_valid, error_msg = self._config_validator.validate(new_config)
            if not is_valid:
                return ApprovalResult(
                    requires_approval=False,
                    error=error_msg,
                )

        new_args = new_config.get("args", [])
        original_args = original_config.get("args", [])

        # Find added paths
        added_paths = [arg for arg in new_args if arg not in original_args]

        # Categorize paths
        sensitive_results = self._path_security.check_paths(added_paths)
        sensitive_paths = [r.path for r in sensitive_results if r.is_sensitive]
        safe_paths = [r.path for r in sensitive_results if not r.is_sensitive]

        # No sensitive paths = immediate approval
        if not sensitive_paths:
            return ApprovalResult(
                requires_approval=False,
                safe_paths=safe_paths,
            )

        # Compute checksum for race condition detection
        checksum = self._compute_config_checksum(original_config)

        # Create individual requests for each sensitive path
        pending_info: list[PendingRequestInfo] = []

        for path in sensitive_paths:
            # Check for existing pending request
            existing = self._find_existing_request(server_name, path)

            if existing:
                # Update existing request
                existing.target_args = new_args
                existing.original_config_checksum = checksum
                pending_info.append(PendingRequestInfo(existing.code, path))
            else:
                # Create new request
                path_index = new_args.index(path) if path in new_args else -1
                request = ConfigChangeRequest(
                    id=self._generate_id(),
                    server_name=server_name,
                    change_type=change_type,
                    code=self._generate_code(),
                    status=ApprovalStatus.PENDING,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC)
                    + timedelta(minutes=self._request_timeout_minutes),
                    sensitive_path=path,
                    path_index=path_index,
                    target_args=new_args,
                    original_config=original_config,
                    original_config_checksum=checksum,
                )

                self._pending[request.code] = request
                pending_info.append(PendingRequestInfo(request.code, path))

                # Audit log
                self._audit.log_config_change_requested(
                    server_name=server_name,
                    sensitive_path=path,
                    approval_code=request.code,
                    actor="web",
                )

        return ApprovalResult(
            requires_approval=True,
            pending_requests=pending_info,
            safe_paths=safe_paths,
        )

    def _find_existing_request(
        self, server_name: str, path: str
    ) -> ConfigChangeRequest | None:
        """Find existing pending request for server/path combination."""
        for req in self._pending.values():
            if (
                req.server_name == server_name
                and req.sensitive_path == path
                and req.status == ApprovalStatus.PENDING
                and req.expires_at > datetime.now(UTC)
            ):
                return req
        return None

    async def approve(
        self,
        code: str,
        duration_minutes: int,
        approved_by: str = "cli",
        current_config: dict[str, Any] | None = None,
    ) -> tuple[bool, str, ConfigChangeGrant | None]:
        """Approve a config change request."""
        self._ensure_cleanup_started()
        """Approve a config change request.

        Args:
            code: The approval code
            duration_minutes: How long to allow the change
            approved_by: Who approved (cli, web)
            current_config: Current config to verify no drift

        Returns:
            Tuple of (success, message, grant)
        """
        code = code.upper().strip()

        request = self._pending.get(code)
        if not request:
            return False, f"Invalid approval code: {code}", None

        if request.status != ApprovalStatus.PENDING:
            return False, f"Request already {request.status.value}", None

        if request.expires_at < datetime.now(UTC):
            request.status = ApprovalStatus.EXPIRED
            return False, "Request has expired", None

        # Race condition check
        if current_config is not None and request.original_config_checksum:
            current_checksum = self._compute_config_checksum(current_config)
            if current_checksum != request.original_config_checksum:
                request.status = ApprovalStatus.EXPIRED
                return (
                    False,
                    "Server configuration has changed since request was created. "
                    "Please create a new request.",
                    None,
                )

        # Create grant
        original_args = request.original_config.get("args", [])
        grant = ConfigChangeGrant(
            id=self._generate_id(),
            request_id=request.id,
            server_name=request.server_name,
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=duration_minutes),
            duration_minutes=duration_minutes,
            approved_by=approved_by,
            sensitive_path=request.sensitive_path,
            path_index=request.path_index,
            target_args=request.target_args,
            original_args=original_args,
        )

        self._grants[grant.id] = grant
        request.status = ApprovalStatus.APPROVED

        # Audit log
        self._audit.log_config_change_approved(
            server_name=grant.server_name,
            sensitive_path=grant.sensitive_path,
            approval_code=code,
            grant_id=grant.id,
            duration_minutes=duration_minutes,
            actor=approved_by,
        )

        return True, f"Config change approved for {duration_minutes} minutes", grant

    async def deny(self, code: str, denied_by: str = "web") -> tuple[bool, str]:
        """Deny a config change request."""
        code = code.upper().strip()

        request = self._pending.get(code)
        if not request:
            return False, f"Invalid approval code: {code}"

        if request.status != ApprovalStatus.PENDING:
            return False, f"Request already {request.status.value}"

        request.status = ApprovalStatus.DENIED
        return True, "Config change request denied"

    async def revert_grant(self, grant_id: str) -> tuple[bool, str]:
        """Manually revert an approved grant."""
        grant = self._grants.get(grant_id)
        if not grant:
            return False, "Grant not found"

        # Mark as expired
        grant.expires_at = datetime.now(UTC)

        # Trigger revert
        if self._revert_callback:
            try:
                await self._revert_callback(
                    grant.server_name, {"args": grant.original_args}
                )
            except Exception as e:
                return False, f"Failed to revert: {e}"

        # Trigger restart
        if self._restart_callback:
            try:
                await self._restart_callback(grant.server_name)
            except Exception as e:
                return False, f"Reverted but restart failed: {e}"

        # Remove grant
        del self._grants[grant_id]

        # Audit log
        self._audit.log_config_change_reverted(
            server_name=grant.server_name,
            sensitive_path=grant.sensitive_path,
            grant_id=grant.id,
            reason="manual",
        )

        return True, "Config change reverted"

    def get_pending_requests(self) -> list[ConfigChangeRequest]:
        """Get all pending (non-expired) requests."""
        now = datetime.now(UTC)
        return [
            req
            for req in self._pending.values()
            if req.status == ApprovalStatus.PENDING and req.expires_at > now
        ]

    def get_active_grants(self) -> list[ConfigChangeGrant]:
        """Get all active (non-expired) grants."""
        now = datetime.now(UTC)
        return [grant for grant in self._grants.values() if grant.expires_at > now]

    def get_request_by_code(self, code: str) -> ConfigChangeRequest | None:
        """Get a request by its approval code."""
        return self._pending.get(code.upper().strip())

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired requests and grants."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval_seconds)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Cleanup error: {e}")

    async def _cleanup_expired(self) -> None:
        """Clean up expired requests and grants."""
        now = datetime.now(UTC)

        # Expire pending requests
        expired_codes = [
            code
            for code, req in self._pending.items()
            if req.status == ApprovalStatus.PENDING and req.expires_at < now
        ]
        for code in expired_codes:
            self._pending[code].status = ApprovalStatus.EXPIRED

        # Handle expired grants
        expired_grants = [
            grant_id
            for grant_id, grant in self._grants.items()
            if grant.expires_at < now
        ]
        for grant_id in expired_grants:
            grant = self._grants[grant_id]

            # Revert config
            if self._revert_callback:
                try:
                    await self._revert_callback(
                        grant.server_name, {"args": grant.original_args}
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Revert failed: {e}")

            # Restart backend
            if self._restart_callback:
                try:
                    await self._restart_callback(grant.server_name)
                    self._audit.log_backend_restarted(
                        server_name=grant.server_name,
                        reason="config_change_reverted",
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Restart failed: {e}")

            # Audit log
            self._audit.log_config_change_reverted(
                server_name=grant.server_name,
                sensitive_path=grant.sensitive_path,
                grant_id=grant.id,
                reason="expired",
            )

            # Remove grant
            del self._grants[grant_id]
