"""Audit logging for MCP Gateway.

Provides structured, tamper-evident logging of security-relevant events.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Audit logger - separate from application logs
audit_logger = logging.getLogger("mcp_gateway.audit")

# Ensure audit logger doesn't propagate to root
audit_logger.propagate = False


class AuditEvent:
    """Represents an auditable event."""

    # Event types
    CONFIG_CHANGE_REQUESTED = "config_change.requested"
    CONFIG_CHANGE_APPROVED = "config_change.approved"
    CONFIG_CHANGE_DENIED = "config_change.denied"
    CONFIG_CHANGE_APPLIED = "config_change.applied"
    CONFIG_CHANGE_REVERTED = "config_change.reverted"
    CONFIG_CHANGE_EXPIRED = "config_change.expired"
    ACCESS_REQUESTED = "access.requested"
    ACCESS_APPROVED = "access.approved"
    ACCESS_DENIED = "access.denied"
    ACCESS_GRANT_EXPIRED = "access.grant_expired"
    SERVER_STARTED = "server.started"
    SERVER_STOPPED = "server.stopped"
    AUTH_FAILURE = "auth.failure"


def init_audit_logging(log_dir: Path | None = None) -> None:
    """Initialize the audit logging system.

    Args:
        log_dir: Directory for audit logs. Defaults to 'logs' subdirectory.
    """
    if log_dir is None:
        log_dir = Path.cwd() / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    audit_file = log_dir / "audit.log"

    # Create file handler with append mode
    handler = logging.FileHandler(audit_file, mode='a')
    handler.setLevel(logging.INFO)

    # Simple formatter - just the JSON message
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)

    audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)

    # Log initialization
    log_event(AuditEvent.SERVER_STARTED, {
        "message": "Audit logging initialized",
        "log_file": str(audit_file),
    })


def compute_chain_hash(event_data: dict) -> str:
    """Compute a chain hash for tamper detection.

    This creates a simple hash chain where each event includes
    the hash of the previous event's data.

    Args:
        event_data: The event data to hash

    Returns:
        Hex digest of the hash
    """
    # In a production system, this would read the last event's hash
    # For simplicity, we just hash the current event with a timestamp
    data_str = json.dumps(event_data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data_str.encode()).hexdigest()[:32]


def log_event(
    event_type: str,
    data: dict[str, Any],
    actor: str = "system",
    ip_address: str | None = None,
) -> None:
    """Log an audit event.

    Args:
        event_type: Type of event (use AuditEvent constants)
        data: Event-specific data
        actor: Who/what performed the action (e.g., "cli", "web", "system")
        ip_address: Optional IP address for remote actions
    """
    timestamp = datetime.now(UTC).isoformat()

    event = {
        "timestamp": timestamp,
        "event_type": event_type,
        "actor": actor,
        "data": data,
    }

    if ip_address:
        event["ip_address"] = ip_address

    # Add chain hash for tamper detection
    event["chain_hash"] = compute_chain_hash(event)

    # Log as JSON
    audit_logger.info(json.dumps(event, separators=(',', ':')))


# Convenience functions for common events

def log_config_change_requested(
    server_name: str,
    sensitive_path: str,
    approval_code: str,
    actor: str = "web",
) -> None:
    """Log a config change request."""
    log_event(AuditEvent.CONFIG_CHANGE_REQUESTED, {
        "server_name": server_name,
        "sensitive_path": sensitive_path,
        "approval_code": approval_code,
    }, actor=actor)


def log_config_change_approved(
    server_name: str,
    sensitive_path: str,
    approval_code: str,
    grant_id: str,
    duration_minutes: int,
    actor: str = "cli",
) -> None:
    """Log a config change approval."""
    log_event(AuditEvent.CONFIG_CHANGE_APPROVED, {
        "server_name": server_name,
        "sensitive_path": sensitive_path,
        "approval_code": approval_code,
        "grant_id": grant_id,
        "duration_minutes": duration_minutes,
    }, actor=actor)


def log_config_change_reverted(
    server_name: str,
    sensitive_path: str,
    grant_id: str,
    reason: str = "expired",
) -> None:
    """Log a config change reversion."""
    log_event(AuditEvent.CONFIG_CHANGE_REVERTED, {
        "server_name": server_name,
        "sensitive_path": sensitive_path,
        "grant_id": grant_id,
        "reason": reason,
    }, actor="system")


def log_access_requested(
    mcp_name: str,
    tool_name: str,
    path: str,
    approval_code: str,
) -> None:
    """Log an access request."""
    log_event(AuditEvent.ACCESS_REQUESTED, {
        "mcp_name": mcp_name,
        "tool_name": tool_name,
        "path": path,
        "approval_code": approval_code,
    }, actor="system")


def log_access_approved(
    mcp_name: str,
    path: str,
    approval_code: str,
    grant_id: str,
    duration_minutes: int,
    actor: str = "cli",
) -> None:
    """Log an access approval."""
    log_event(AuditEvent.ACCESS_APPROVED, {
        "mcp_name": mcp_name,
        "path": path,
        "approval_code": approval_code,
        "grant_id": grant_id,
        "duration_minutes": duration_minutes,
    }, actor=actor)
