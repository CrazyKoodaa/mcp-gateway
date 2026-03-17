"""Access control manager for MCP Gateway."""

from __future__ import annotations

import asyncio
import inspect
import logging
import secrets
import string
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import TypeVar

    T = TypeVar("T")

from .models import (
    AccessGrant,
    AccessRequest,
    AccessRequestStatus,
    ConfigChangeGrant,
    ConfigChangeRequest,
)
from .utils import compute_config_checksum, is_sensitive_path

logger = logging.getLogger(__name__)


class AccessControlManager:
    """Manages dynamic path access control and config change approval.

    - Tracks pending access requests with approval codes
    - Manages time-bound access grants
    - Validates path access against grants and allowed paths
    - Manages time-bound config changes for sensitive paths
    - Provides notifications for admin UI
    """

    def __init__(
        self,
        request_timeout_minutes: int = 10,
        default_grant_duration: int = 1,
        cleanup_interval_seconds: int = 60,
    ):
        self._pending_requests: dict[str, AccessRequest] = {}  # code -> request
        self._grants: dict[str, AccessGrant] = {}  # grant_id -> grant
        self._path_grants: dict[str, set[str]] = {}  # path -> set of grant_ids
        self._mcp_grants: dict[str, set[str]] = {}  # mcp_name -> set of grant_ids

        # Config change tracking
        self._pending_config_changes: dict[str, ConfigChangeRequest] = {}  # code -> request
        self._config_grants: dict[str, ConfigChangeGrant] = {}  # grant_id -> grant

        self.request_timeout_minutes = request_timeout_minutes
        self.default_grant_duration = default_grant_duration
        self.cleanup_interval_seconds = cleanup_interval_seconds

        self._cleanup_task: asyncio.Task[None] | None = None
        self._notification_callbacks: list[Callable[[str, dict[str, Any]], Awaitable[None]]] = []

        # Config revert callback
        self._config_revert_callback: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None

        # Backend restart callback for auto-revert
        self._backend_restart_callback: Callable[[str], Awaitable[None]] | None = None

        # Lock for thread-safe grant creation
        self._grant_lock = asyncio.Lock()

        logger.info("AccessControlManager initialized")

    def set_config_revert_callback(
        self, callback: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Set callback for config reversion.

        Args:
            callback: async function(server_name, original_config) -> None
        """
        self._config_revert_callback = callback

    def set_backend_restart_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Set callback for backend restart during auto-revert.

        Args:
            callback: async function(server_name) -> None
        """
        self._backend_restart_callback = callback

    def start(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None:
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                logger.info("Access control cleanup task started")
            except RuntimeError:
                # No event loop running yet, cleanup will start on first access
                logger.debug("No event loop available, cleanup task deferred")

    def stop(self) -> None:
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
            logger.info("Access control cleanup task stopped")

    def register_notification_callback(
        self, callback: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Register a callback for access request notifications.

        Callback receives (event_type: str, data: dict) where event_type is:
        - "request_created": New pending request
        - "request_approved": Request was approved
        - "request_denied": Request was denied
        - "request_expired": Request or grant expired
        - "config_request_created": New pending config change
        - "config_request_approved": Config change approved
        - "config_request_denied": Config change denied
        - "config_reverted": Config change reverted after expiration
        """
        self._notification_callbacks.append(callback)

    def _notify(self, event_type: str, data: dict[str, Any]) -> None:
        """Notify all registered callbacks."""
        for callback in self._notification_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event_type, data))
                else:
                    callback(event_type, data)
            except Exception as e:
                logger.error(f"Notification callback failed: {e}")

    def _generate_code(self) -> str:
        """Generate a human-readable 8-char approval code like 'ABCD-1234'."""
        # Generate 4 letters and 4 numbers for readability
        letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
        numbers = "".join(secrets.choice(string.digits) for _ in range(4))
        return f"{letters}-{numbers}"

    def _generate_id(self) -> str:
        """Generate a unique ID."""
        return secrets.token_urlsafe(16)

    def _normalize_path(self, path: str) -> str:
        """Normalize a path for comparison."""
        from pathlib import Path

        try:
            # Expand home directory
            expanded = Path(path).expanduser()
            # Resolve to absolute path
            absolute = expanded.resolve()
            return str(absolute)
        except (OSError, RuntimeError):
            # Filesystem errors (e.g., path doesn't exist, permissions)
            return path

    def _is_path_allowed(
        self,
        requested_path: str,
        allowed_paths: list[str],
    ) -> bool:
        """Check if a path is within allowed paths.

        Args:
            requested_path: The path being accessed
            allowed_paths: List of allowed base paths

        Returns:
            True if the path is within any allowed path
        """
        from pathlib import Path

        try:
            requested = Path(requested_path).expanduser().resolve()

            for allowed in allowed_paths:
                try:
                    allowed_base = Path(allowed).expanduser().resolve()
                    # Check if requested path is the same as or within allowed path
                    if requested == allowed_base or allowed_base in requested.parents:
                        return True
                except (OSError, RuntimeError):
                    # Filesystem errors for specific allowed path
                    continue

            return False
        except (OSError, RuntimeError) as e:
            logger.warning(f"Path validation error for '{requested_path}': {e}")
            return False

    def _has_active_grant(self, mcp_name: str, path: str) -> AccessGrant | None:
        """Check if there's an active grant for this MCP and path."""
        now = datetime.now(UTC)

        # Check MCP-specific grants
        grant_ids = self._mcp_grants.get(mcp_name, set())
        for grant_id in grant_ids:
            grant = self._grants.get(grant_id)
            if grant and grant.expires_at > now:
                # Check if path matches or is within granted path
                try:
                    from pathlib import Path

                    requested = Path(path).expanduser().resolve()
                    granted = Path(grant.path).expanduser().resolve()
                    if requested == granted or granted in requested.parents:
                        return grant
                except (OSError, RuntimeError):
                    # Filesystem errors during path resolution
                    continue

        return None

    # ==================== Config Change Methods ====================

    async def check_config_change(
        self,
        server_name: str,
        change_type: str,
        original_config: dict[str, Any],
        new_config: dict[str, Any],
    ) -> tuple[bool, list[dict], list[str]]:
        """Check if a config change requires approval.

        GRANULAR: Creates separate approval requests for EACH sensitive path.
        Safe paths are applied immediately.

        Args:
            server_name: Name of the server being modified
            change_type: 'add', 'modify', or 'remove'
            original_config: Current configuration
            new_config: Proposed new configuration

        Returns:
            Tuple of (requires_approval, pending_requests_info, safe_paths)
            - requires_approval: True if any approval is needed
            - pending_requests_info: List of dicts with 'code', 'path' for each sensitive path
            - safe_paths: List of safe paths that were applied immediately
        """
        # Validate config before processing
        from ..admin import validate_server_config

        is_valid, error_msg = validate_server_config(new_config)
        if not is_valid:
            # Return a special marker that this is a validation error
            return False, [{"error": error_msg}], []

        new_args = new_config.get("args", [])
        original_args = original_config.get("args", [])

        # Find paths that were added (in new but not in original)
        added_paths = [arg for arg in new_args if arg not in original_args]

        # Categorize paths
        sensitive_paths = []
        safe_paths = []

        for path in added_paths:
            if is_sensitive_path(path):
                sensitive_paths.append(path)
            else:
                safe_paths.append(path)

        # If no sensitive paths, proceed immediately
        if not sensitive_paths:
            return False, [], safe_paths

        # Compute checksum of original config for race condition detection
        original_checksum = compute_config_checksum(original_config)

        # Create separate pending requests for EACH sensitive path
        pending_info = []

        for path in sensitive_paths:
            # Check if there's already a pending request for this specific path
            existing_req = None
            for req in self._pending_config_changes.values():
                if (
                    req.server_name == server_name
                    and req.sensitive_path == path
                    and req.status == AccessRequestStatus.PENDING
                    and req.expires_at > datetime.now(UTC)
                ):
                    existing_req = req
                    break

            if existing_req:
                # Update existing request
                existing_req.target_args = new_args
                existing_req.original_config_checksum = original_checksum
                pending_info.append({"code": existing_req.code, "path": path})
                logger.debug(f"Config change pending for {server_name} path {path} (existing)")
            else:
                # Create new pending request for this specific path
                path_index = new_args.index(path) if path in new_args else -1

                request = ConfigChangeRequest(
                    id=self._generate_id(),
                    server_name=server_name,
                    change_type=change_type,
                    code=self._generate_code(),
                    status=AccessRequestStatus.PENDING,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=self.request_timeout_minutes),
                    sensitive_path=path,
                    path_index=path_index,
                    target_args=new_args,
                    original_config=original_config,
                    original_config_checksum=original_checksum,
                )

                self._pending_config_changes[request.code] = request
                pending_info.append({"code": request.code, "path": path})

                logger.info(
                    f"Config change request: {server_name} wants {path} (code: {request.code})"
                )

                # Notify admin UI
                self._notify(
                    "config_request_created",
                    {
                        "code": request.code,
                        "server_name": server_name,
                        "change_type": change_type,
                        "sensitive_path": path,
                        "created_at": request.created_at.isoformat(),
                        "expires_at": request.expires_at.isoformat(),
                    },
                )

                # Audit log
                from ..audit import log_config_change_requested

                log_config_change_requested(server_name, path, request.code, actor="web")

        return True, pending_info, safe_paths

    async def approve_config_change(
        self,
        code: str,
        duration_minutes: int = 1,
        approved_by: str = "web",
        current_config: dict[str, Any] | None = None,
    ) -> tuple[bool, str, ConfigChangeGrant | None]:
        """Approve a config change request.

        Args:
            code: The approval code
            duration_minutes: How long to allow the change
            approved_by: "cli" or "web"
            current_config: Current server config to verify no drift occurred

        Returns:
            (success, message, grant)
        """
        code = code.upper().strip()

        request = self._pending_config_changes.get(code)
        if not request:
            return False, f"Invalid approval code: {code}", None

        if request.status != AccessRequestStatus.PENDING:
            return False, f"Request already {request.status.value}", None

        if request.expires_at < datetime.now(UTC):
            request.status = AccessRequestStatus.EXPIRED
            return False, "Request has expired", None

        # Verify config hasn't drifted (race condition check)
        if current_config is not None and request.original_config_checksum:
            current_checksum = compute_config_checksum(current_config)
            if current_checksum != request.original_config_checksum:
                # Config changed since request was created
                request.status = AccessRequestStatus.EXPIRED
                return (
                    False,
                    "Config changed since request. Please create a new request.",
                    None,
                )

        # Create the grant
        # Extract original_args from original_config for revert capability
        original_args = request.original_config.get("args", [])

        grant = ConfigChangeGrant(
            id=self._generate_id(),
            request_id=request.id,
            server_name=request.server_name,
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=duration_minutes),
            duration_minutes=duration_minutes,
            approved_by=approved_by,
            sensitive_path=request.sensitive_path,
            path_index=request.path_index,
            target_args=request.target_args,
            original_args=original_args,
        )

        self._config_grants[grant.id] = grant

        # Update request status
        request.status = AccessRequestStatus.APPROVED

        logger.info(
            f"Config change approved: {grant.server_name} can use "
            f"{grant.sensitive_path} for {duration_minutes}min (grant: {grant.id})"
        )

        # Notify admin UI
        self._notify(
            "config_request_approved",
            {
                "code": code,
                "grant_id": grant.id,
                "server_name": grant.server_name,
                "sensitive_path": grant.sensitive_path,
                "duration_minutes": duration_minutes,
                "expires_at": grant.expires_at.isoformat(),
                "approved_by": approved_by,
            },
        )

        # Audit log
        from ..audit import log_config_change_approved

        log_config_change_approved(
            grant.server_name,
            grant.sensitive_path,
            code,
            grant.id,
            duration_minutes,
            actor=approved_by,
        )

        return True, f"Config change approved for {duration_minutes} minutes", grant

    async def deny_config_change(self, code: str, denied_by: str = "web") -> tuple[bool, str]:
        """Deny a config change request."""
        code = code.upper().strip()

        request = self._pending_config_changes.get(code)
        if not request:
            return False, f"Invalid approval code: {code}"

        if request.status != AccessRequestStatus.PENDING:
            return False, f"Request already {request.status.value}"

        request.status = AccessRequestStatus.DENIED

        logger.info(f"Config change denied: {request.server_name} (by {denied_by})")

        # Notify admin UI
        self._notify(
            "config_request_denied",
            {
                "code": code,
                "server_name": request.server_name,
                "sensitive_path": request.sensitive_path,
                "denied_by": denied_by,
            },
        )

        return True, "Config change request denied"

    async def revert_config_change(self, grant_id: str) -> tuple[bool, str]:
        """Manually revert an approved config change.

        Args:
            grant_id: The grant ID to revert

        Returns:
            (success, message)
        """
        grant = self._config_grants.get(grant_id)
        if not grant:
            return False, "Grant not found"

        # Mark as expired
        grant.expires_at = datetime.now(UTC)

        # Trigger revert via callback
        if self._config_revert_callback:
            try:
                await self._config_revert_callback(grant.server_name, grant.original_config)
                logger.info(f"Config change manually reverted for {grant.server_name}")
            except Exception as e:
                logger.error(f"Failed to revert config: {e}")
                return False, f"Failed to revert: {e}"

        # Remove from grants
        del self._config_grants[grant_id]

        # Notify
        self._notify(
            "config_reverted",
            {
                "grant_id": grant_id,
                "server_name": grant.server_name,
                "reason": "manual",
            },
        )

        return True, "Config change reverted"

    def get_pending_config_changes(self) -> list[ConfigChangeRequest]:
        """Get all pending config change requests."""
        now = datetime.now(UTC)
        return [
            req
            for req in self._pending_config_changes.values()
            if req.status == AccessRequestStatus.PENDING and req.expires_at > now
        ]

    def get_active_config_grants(self) -> list[ConfigChangeGrant]:
        """Get all active config change grants."""
        now = datetime.now(UTC)
        return [grant for grant in self._config_grants.values() if grant.expires_at > now]

    def get_config_request_by_code(self, code: str) -> ConfigChangeRequest | None:
        """Get a config change request by code."""
        return self._pending_config_changes.get(code.upper().strip())

    async def _revert_expired_config_grant(self, grant: ConfigChangeGrant) -> None:
        """Revert a config change grant after expiration."""
        if self._config_revert_callback:
            try:
                # For granular revert, we need to reconstruct original args
                # The callback expects full config, but we stored original_args
                original_config = {"args": grant.original_args}
                await self._config_revert_callback(grant.server_name, original_config)
                logger.info(f"Config change auto-reverted for {grant.server_name} after expiration")
            except Exception as e:
                logger.error(f"Failed to auto-revert config: {e}")

        # RESTART BACKEND after revert to remove access to sensitive path
        if self._backend_restart_callback:
            try:
                await self._backend_restart_callback(grant.server_name)
                logger.info(f"Backend {grant.server_name} restarted after auto-revert")
            except Exception as e:
                logger.error(f"Failed to restart backend after auto-revert: {e}")

        # Notify
        self._notify(
            "config_reverted",
            {
                "grant_id": grant.id,
                "server_name": grant.server_name,
                "reason": "expired",
                "sensitive_path": grant.sensitive_path,
            },
        )

        # Audit log
        from ..audit import log_config_change_reverted

        log_config_change_reverted(
            grant.server_name, grant.sensitive_path, grant.id, reason="expired"
        )

        # Notify that backend was restarted after revert
        self._notify(
            "backend_restarted",
            {
                "server_name": grant.server_name,
                "reason": "config_change_reverted",
                "sensitive_path": grant.sensitive_path,
            },
        )

    # ==================== Original Access Control Methods ====================

    async def check_access(
        self,
        mcp_name: str,
        tool_name: str,
        path: str,
        allowed_paths: list[str],
    ) -> tuple[bool, str | None]:
        """Check if access to a path is allowed.

        Returns:
            (allowed: bool, request_code: Optional[str])
            - allowed=True: Access granted (either by allowed_paths or active grant)
            - allowed=False, request_code=None: Access denied permanently
            - allowed=False, request_code=str: Pending approval, use code to approve
        """
        # First check allowed paths
        if self._is_path_allowed(path, allowed_paths):
            logger.debug(f"Access allowed for {mcp_name} to {path} (in allowed paths)")
            return True, None

        # Check for active time-bound grant
        grant = self._has_active_grant(mcp_name, path)
        if grant:
            logger.debug(f"Access allowed for {mcp_name} to {path} (active grant {grant.id})")
            return True, None

        # Check if there's already a pending request for this
        for req in self._pending_requests.values():
            if (
                req.mcp_name == mcp_name
                and req.tool_name == tool_name
                and req.path == path
                and req.status == AccessRequestStatus.PENDING
                and req.expires_at > datetime.now(UTC)
            ):
                logger.debug(f"Access pending for {mcp_name} to {path} (existing request)")
                return False, req.code

        # Create a new pending request
        request = AccessRequest(
            id=self._generate_id(),
            mcp_name=mcp_name,
            tool_name=tool_name,
            path=path,
            code=self._generate_code(),
            status=AccessRequestStatus.PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=self.request_timeout_minutes),
            metadata={},
        )

        self._pending_requests[request.code] = request

        logger.info(f"Access request: {mcp_name} wants {path} (code: {request.code})")

        # Notify admin UI
        self._notify(
            "request_created",
            {
                "code": request.code,
                "mcp_name": mcp_name,
                "tool_name": tool_name,
                "path": path,
                "created_at": request.created_at.isoformat(),
                "expires_at": request.expires_at.isoformat(),
            },
        )

        return False, request.code

    async def approve_request(
        self,
        code: str,
        duration_minutes: int = 1,
        approved_by: str = "cli",
    ) -> tuple[bool, str, AccessGrant | None]:
        """Approve an access request by code.

        Args:
            code: The approval code (e.g., "ABCD-1234")
            duration_minutes: How long to grant access (default 1 minute)
            approved_by: "cli" or "web"

        Returns:
            (success: bool, message: str, grant: Optional[AccessGrant])
        """
        code = code.upper().strip()

        request = self._pending_requests.get(code)
        if not request:
            return False, f"Invalid approval code: {code}", None

        if request.status != AccessRequestStatus.PENDING:
            return False, f"Request already {request.status.value}", None

        if request.expires_at < datetime.now(UTC):
            request.status = AccessRequestStatus.EXPIRED
            return False, "Request has expired", None

        # Create the grant
        grant = AccessGrant(
            id=self._generate_id(),
            request_id=request.id,
            mcp_name=request.mcp_name,
            tool_name=request.tool_name,
            path=request.path,
            granted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=duration_minutes),
            duration_minutes=duration_minutes,
            approved_by=approved_by,
        )

        # Store the grant
        self._grants[grant.id] = grant

        # Index by MCP and path
        if grant.mcp_name not in self._mcp_grants:
            self._mcp_grants[grant.mcp_name] = set()
        self._mcp_grants[grant.mcp_name].add(grant.id)

        path_key = self._normalize_path(grant.path)
        if path_key not in self._path_grants:
            self._path_grants[path_key] = set()
        self._path_grants[path_key].add(grant.id)

        # Update request status
        request.status = AccessRequestStatus.APPROVED

        logger.info(
            f"Access granted: {grant.mcp_name} can access {grant.path} "
            f"for {duration_minutes}min (grant: {grant.id})"
        )

        # Notify admin UI
        self._notify(
            "request_approved",
            {
                "code": code,
                "grant_id": grant.id,
                "mcp_name": grant.mcp_name,
                "tool_name": grant.tool_name,
                "path": grant.path,
                "duration_minutes": duration_minutes,
                "expires_at": grant.expires_at.isoformat(),
                "approved_by": approved_by,
            },
        )

        return True, f"Access granted for {duration_minutes} minutes", grant

    async def deny_request(self, code: str, denied_by: str = "cli") -> tuple[bool, str]:
        """Deny an access request by code."""
        code = code.upper().strip()

        request = self._pending_requests.get(code)
        if not request:
            return False, f"Invalid approval code: {code}"

        if request.status != AccessRequestStatus.PENDING:
            return False, f"Request already {request.status.value}"

        request.status = AccessRequestStatus.DENIED

        logger.info(f"Access denied: {request.mcp_name} to {request.path} (by {denied_by})")

        # Notify admin UI
        self._notify(
            "request_denied",
            {
                "code": code,
                "mcp_name": request.mcp_name,
                "tool_name": request.tool_name,
                "path": request.path,
                "denied_by": denied_by,
            },
        )

        return True, "Access request denied"

    def get_pending_requests(self) -> list[AccessRequest]:
        """Get all pending access requests."""
        now = datetime.now(UTC)
        return [
            req
            for req in self._pending_requests.values()
            if req.status == AccessRequestStatus.PENDING and req.expires_at > now
        ]

    async def get_active_grants(self, server_name: str | None = None) -> list[AccessGrant]:
        """Get all active (non-expired) access grants.

        Args:
            server_name: Optional filter by server name (mcp_name)

        Returns:
            List of active grants, optionally filtered by server
        """
        now = datetime.now(UTC)
        grants = [grant for grant in self._grants.values() if grant.expires_at > now]
        if server_name:
            grants = [g for g in grants if g.mcp_name == server_name]
        return grants

    async def grant_access(
        self,
        server_name: str,
        user_id: str,
        tool_name: str,
        path: str,
        duration_minutes: float = 1,
    ) -> AccessGrant:
        """Directly grant access without approval process.

        This creates an access grant immediately without requiring
        a prior access request. Used for admin/CLI grants.

        If a grant for the same (server_name, tool_name, path) already exists,
        the existing grant is returned (idempotent behavior).

        Args:
            server_name: Name of the MCP server
            user_id: ID of the user being granted access
            tool_name: Name of the tool being granted
            path: Path being granted access to
            duration_minutes: How long the grant is valid (default 1 minute)

        Returns:
            The created or existing AccessGrant
        """
        async with self._grant_lock:
            now = datetime.now(UTC)

            # Check if an active grant already exists for this combination
            existing_grant = self._find_active_grant(server_name, tool_name, path)
            if existing_grant:
                logger.debug(f"Returning existing grant for {server_name}/{tool_name}/{path}")
                return existing_grant

            # Create the grant directly
            grant = AccessGrant(
                id=self._generate_id(),
                request_id=self._generate_id(),  # Generate a dummy request ID
                mcp_name=server_name,
                tool_name=tool_name,
                path=path,
                granted_at=now,
                expires_at=now + timedelta(minutes=duration_minutes),
                duration_minutes=int(duration_minutes),
                approved_by=user_id,
            )

            # Store the grant
            self._grants[grant.id] = grant

            # Index by MCP and path
            if grant.mcp_name not in self._mcp_grants:
                self._mcp_grants[grant.mcp_name] = set()
            self._mcp_grants[grant.mcp_name].add(grant.id)

            path_key = self._normalize_path(grant.path)
            if path_key not in self._path_grants:
                self._path_grants[path_key] = set()
            self._path_grants[path_key].add(grant.id)

            logger.info(
                f"Direct access granted: {grant.mcp_name} can access {grant.path} "
                f"for {duration_minutes}min (grant: {grant.id}, by: {user_id})"
            )

            # Notify admin UI
            self._notify(
                "request_approved",
                {
                    "grant_id": grant.id,
                    "mcp_name": grant.mcp_name,
                    "tool_name": grant.tool_name,
                    "path": grant.path,
                    "duration_minutes": duration_minutes,
                    "expires_at": grant.expires_at.isoformat(),
                    "approved_by": user_id,
                    "direct_grant": True,
                },
            )

            return grant

    def _find_active_grant(self, server_name: str, tool_name: str, path: str) -> AccessGrant | None:
        """Find an active grant for the given combination.

        Args:
            server_name: MCP server name
            tool_name: Tool name
            path: Path

        Returns:
            Active grant if found, None otherwise
        """
        now = datetime.now(UTC)
        path_key = self._normalize_path(path)

        # Check grants for this server
        grant_ids = self._mcp_grants.get(server_name, set())
        for grant_id in grant_ids:
            grant = self._grants.get(grant_id)
            if grant and grant.expires_at > now:
                if grant.tool_name == tool_name and self._normalize_path(grant.path) == path_key:
                    return grant
        return None

    def get_request_by_code(self, code: str) -> AccessRequest | None:
        """Get a request by its approval code."""
        return self._pending_requests.get(code.upper().strip())

    async def revoke_grant(self, grant_id: str) -> bool:
        """Revoke an active grant."""
        grant = self._grants.get(grant_id)
        if not grant:
            return False

        # Mark as expired immediately
        grant.expires_at = datetime.now(UTC)

        # Remove from indexes
        if grant.mcp_name in self._mcp_grants:
            self._mcp_grants[grant.mcp_name].discard(grant_id)

        path_key = self._normalize_path(grant.path)
        if path_key in self._path_grants:
            self._path_grants[path_key].discard(grant_id)

        logger.info(f"Grant revoked: {grant_id}")

        # Notify admin UI
        self._notify(
            "request_expired",
            {
                "grant_id": grant_id,
                "mcp_name": grant.mcp_name,
                "path": grant.path,
                "reason": "revoked",
            },
        )

        return True

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired requests and grants."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in access control cleanup: {e}")

    async def _cleanup_expired(self) -> None:
        """Clean up expired requests and grants."""
        now = datetime.now(UTC)

        # Clean up expired pending requests
        expired_codes = [
            code
            for code, req in self._pending_requests.items()
            if req.status == AccessRequestStatus.PENDING and req.expires_at < now
        ]
        for code in expired_codes:
            req = self._pending_requests[code]
            req.status = AccessRequestStatus.EXPIRED
            logger.debug(f"Request expired: {code}")
            self._notify(
                "request_expired",
                {
                    "code": code,
                    "mcp_name": req.mcp_name,
                    "path": req.path,
                    "reason": "timeout",
                },
            )

        # Clean up expired grants (with lock for thread safety)
        async with self._grant_lock:
            expired_grants = [
                grant_id for grant_id, grant in self._grants.items() if grant.expires_at < now
            ]
            for grant_id in expired_grants:
                grant = self._grants[grant_id]

                # Remove from indexes
                if grant.mcp_name in self._mcp_grants:
                    self._mcp_grants[grant.mcp_name].discard(grant_id)
                    # Clean up empty sets
                    if not self._mcp_grants[grant.mcp_name]:
                        del self._mcp_grants[grant.mcp_name]

                path_key = self._normalize_path(grant.path)
                if path_key in self._path_grants:
                    self._path_grants[path_key].discard(grant_id)
                    # Clean up empty sets
                    if not self._path_grants[path_key]:
                        del self._path_grants[path_key]

                # Remove the grant itself
                del self._grants[grant_id]

                logger.debug(f"Grant expired and removed: {grant_id}")
                self._notify(
                    "request_expired",
                    {
                        "grant_id": grant_id,
                        "mcp_name": grant.mcp_name,
                        "path": grant.path,
                        "reason": "expired",
                    },
                )

        # Clean up expired config change requests
        expired_config_codes = [
            code
            for code, config_req in self._pending_config_changes.items()
            if config_req.status == AccessRequestStatus.PENDING and config_req.expires_at < now
        ]
        for code in expired_config_codes:
            config_req: ConfigChangeRequest = self._pending_config_changes[code]
            config_req.status = AccessRequestStatus.EXPIRED
            logger.debug(f"Config change request expired: {code}")
            self._notify(
                "config_request_expired",
                {
                    "code": code,
                    "server_name": config_req.server_name,
                    "sensitive_path": config_req.sensitive_path,
                    "reason": "timeout",
                },
            )

        # Clean up expired config grants and revert configs
        expired_config_grants = [
            grant_id
            for grant_id, config_grant in self._config_grants.items()
            if config_grant.expires_at < now
        ]
        for grant_id in expired_config_grants:
            config_grant: ConfigChangeGrant = self._config_grants[grant_id]

            # Revert the config change
            await self._revert_expired_config_grant(config_grant)

            # Remove from grants
            del self._config_grants[grant_id]

            logger.debug(f"Config grant expired and reverted: {grant_id}")


__all__ = ["AccessControlManager"]
