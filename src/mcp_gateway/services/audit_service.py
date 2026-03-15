"""Audit logging service for security-relevant events.

Provides structured, tamper-evident logging with chain hashes.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class AuditEventType(Enum):
    """Types of auditable events."""

    # Config change events
    CONFIG_CHANGE_REQUESTED = "config_change.requested"
    CONFIG_CHANGE_APPROVED = "config_change.approved"
    CONFIG_CHANGE_DENIED = "config_change.denied"
    CONFIG_CHANGE_APPLIED = "config_change.applied"
    CONFIG_CHANGE_REVERTED = "config_change.reverted"
    CONFIG_CHANGE_EXPIRED = "config_change.expired"

    # Access events
    ACCESS_REQUESTED = "access.requested"
    ACCESS_APPROVED = "access.approved"
    ACCESS_DENIED = "access.denied"
    ACCESS_GRANT_EXPIRED = "access.grant_expired"

    # System events
    SERVER_STARTED = "server.started"
    SERVER_STOPPED = "server.stopped"
    BACKEND_RESTARTED = "backend.restarted"

    # Security events
    AUTH_FAILURE = "auth.failure"
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"


@dataclass(frozen=True)
class AuditEvent:
    """A single audit event.

    Attributes:
        timestamp: ISO format UTC timestamp
        event_type: Type of event
        actor: Who performed the action (e.g., "cli", "web", "system")
        data: Event-specific data
        chain_hash: Hash chain for tamper detection
        ip_address: Optional IP address for remote actions
    """
    timestamp: str
    event_type: str
    actor: str
    data: dict[str, Any]
    chain_hash: str
    ip_address: str | None = None


class AuditLogHandler(Protocol):
    """Protocol for audit log handlers.

    Allows pluggable audit logging (file, database, external service).
    """

    def write(self, event: AuditEvent) -> None:
        """Write an audit event."""
        ...

    def close(self) -> None:
        """Close the handler and release resources."""
        ...


class FileAuditHandler:
    """File-based audit log handler.

    Writes JSON lines to a file with automatic rotation.
    """

    def __init__(self, log_path: Path) -> None:
        """Initialize file audit handler.

        Args:
            log_path: Path to the audit log file
        """
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        # Set up logger
        self._logger = logging.getLogger("mcp_gateway.audit.file")
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)

        # Remove existing handlers
        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)

        # Add file handler
        file_handler = logging.FileHandler(log_path, mode="a")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(file_handler)

        self._previous_hash: str = ""

    def write(self, event: AuditEvent) -> None:
        """Write event as JSON line."""
        event_dict = asdict(event)
        json_line = json.dumps(event_dict, separators=(",", ":"))
        self._logger.info(json_line)

    def compute_chain_hash(self, event_data: dict[str, Any]) -> str:
        """Compute hash chain for tamper detection.

        Creates a hash based on current event data plus previous hash,
        forming a simple blockchain for audit integrity.
        """
        data_str = json.dumps(event_data, sort_keys=True, separators=(",", ":"))
        combined = self._previous_hash + data_str
        new_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
        self._previous_hash = new_hash
        return new_hash

    def close(self) -> None:
        """Close the handler."""
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)


class AuditService:
    """Service for recording auditable security events.

    Provides structured logging with tamper detection through
    hash chaining. Supports multiple handlers for redundancy.

    Example:
        >>> audit = AuditService([FileAuditHandler(Path("audit.log"))])
        >>> audit.log_config_change_requested(
        ...     server_name="filesystem",
        ...     sensitive_path="/etc",
        ...     approval_code="ABCD-1234",
        ...     actor="web"
        ... )
    """

    def __init__(self, handlers: list[AuditLogHandler]) -> None:
        """Initialize audit service with handlers.

        Args:
            handlers: List of audit log handlers
        """
        self._handlers = handlers
        self._initialized = True
        self._running = False

    async def start(self) -> None:
        """Start the audit service."""
        self._running = True

    async def stop(self) -> None:
        """Stop the audit service."""
        self._running = False
        # Close all handlers
        for handler in self._handlers:
            if hasattr(handler, 'close'):
                handler.close()

    @classmethod
    def with_file_handler(cls, log_path: Path) -> "AuditService":
        """Create audit service with file handler.

        Convenience factory method for common use case.

        Args:
            log_path: Path to audit log file

        Returns:
            Configured AuditService
        """
        return cls([FileAuditHandler(log_path)])

    def _log_event(
        self,
        event_type: AuditEventType,
        data: dict[str, Any],
        actor: str = "system",
        ip_address: str | None = None,
    ) -> None:
        """Log an audit event to all handlers.

        Args:
            event_type: Type of event
            data: Event-specific data
            actor: Who performed the action
            ip_address: Optional IP address
        """
        timestamp = datetime.now(UTC).isoformat()

        # Build event data for hashing
        event_data = {
            "timestamp": timestamp,
            "event_type": event_type.value,
            "actor": actor,
            "data": data,
        }
        if ip_address:
            event_data["ip_address"] = ip_address

        # Compute chain hash (using first handler)
        chain_hash = ""
        if self._handlers:
            if isinstance(self._handlers[0], FileAuditHandler):
                chain_hash = self._handlers[0].compute_chain_hash(event_data)

        event = AuditEvent(
            timestamp=timestamp,
            event_type=event_type.value,
            actor=actor,
            data=data,
            chain_hash=chain_hash,
            ip_address=ip_address,
        )

        # Write to all handlers
        for handler in self._handlers:
            try:
                handler.write(event)
            except Exception as e:
                # Don't let audit failures break the application
                logging.getLogger(__name__).error(f"Audit handler failed: {e}")

    # Convenience methods for specific event types

    def log_config_change_requested(
        self,
        server_name: str,
        sensitive_path: str,
        approval_code: str,
        actor: str = "web",
        ip_address: str | None = None,
    ) -> None:
        """Log a config change request."""
        self._log_event(
            AuditEventType.CONFIG_CHANGE_REQUESTED,
            {
                "server_name": server_name,
                "sensitive_path": sensitive_path,
                "approval_code": approval_code,
            },
            actor=actor,
            ip_address=ip_address,
        )

    def log_config_change_approved(
        self,
        server_name: str,
        sensitive_path: str,
        approval_code: str,
        grant_id: str,
        duration_minutes: int,
        actor: str = "cli",
        ip_address: str | None = None,
    ) -> None:
        """Log a config change approval."""
        self._log_event(
            AuditEventType.CONFIG_CHANGE_APPROVED,
            {
                "server_name": server_name,
                "sensitive_path": sensitive_path,
                "approval_code": approval_code,
                "grant_id": grant_id,
                "duration_minutes": duration_minutes,
            },
            actor=actor,
            ip_address=ip_address,
        )

    def log_config_change_reverted(
        self,
        server_name: str,
        sensitive_path: str,
        grant_id: str,
        reason: str = "expired",
    ) -> None:
        """Log a config change reversion."""
        self._log_event(
            AuditEventType.CONFIG_CHANGE_REVERTED,
            {
                "server_name": server_name,
                "sensitive_path": sensitive_path,
                "grant_id": grant_id,
                "reason": reason,
            },
            actor="system",
        )

    def log_backend_restarted(
        self,
        server_name: str,
        reason: str,
    ) -> None:
        """Log a backend restart."""
        self._log_event(
            AuditEventType.BACKEND_RESTARTED,
            {
                "server_name": server_name,
                "reason": reason,
            },
            actor="system",
        )

    def log_access_requested(
        self,
        mcp_name: str,
        tool_name: str,
        path: str,
        approval_code: str,
    ) -> None:
        """Log an access request."""
        self._log_event(
            AuditEventType.ACCESS_REQUESTED,
            {
                "mcp_name": mcp_name,
                "tool_name": tool_name,
                "path": path,
                "approval_code": approval_code,
            },
            actor="system",
        )

    def log_access_approved(
        self,
        mcp_name: str,
        path: str,
        approval_code: str,
        grant_id: str,
        duration_minutes: int,
        actor: str = "cli",
    ) -> None:
        """Log an access approval."""
        self._log_event(
            AuditEventType.ACCESS_APPROVED,
            {
                "mcp_name": mcp_name,
                "path": path,
                "approval_code": approval_code,
                "grant_id": grant_id,
                "duration_minutes": duration_minutes,
            },
            actor=actor,
        )

    def log_auth_failure(
        self,
        reason: str,
        actor: str = "unknown",
        ip_address: str | None = None,
    ) -> None:
        """Log an authentication failure."""
        self._log_event(
            AuditEventType.AUTH_FAILURE,
            {"reason": reason},
            actor=actor,
            ip_address=ip_address,
        )

    def log_rate_limit_exceeded(
        self,
        resource: str,
        actor: str,
        ip_address: str | None = None,
    ) -> None:
        """Log a rate limit violation."""
        self._log_event(
            AuditEventType.RATE_LIMIT_EXCEEDED,
            {"resource": resource},
            actor=actor,
            ip_address=ip_address,
        )

    def close(self) -> None:
        """Close all handlers."""
        for handler in self._handlers:
            try:
                handler.close()
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to close audit handler: {e}")
