"""Data models for access control."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class AccessRequestStatus(str, Enum):  # noqa: UP042
    """Status of an access request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class AccessRequest:
    """A pending access request."""

    id: str
    mcp_name: str
    tool_name: str
    path: str
    code: str  # 8-char approval code like "ABCD-1234"
    status: AccessRequestStatus
    created_at: datetime
    expires_at: datetime  # Request expires if not approved
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccessGrant:
    """A time-bound access grant."""

    id: str
    request_id: str
    mcp_name: str
    tool_name: str
    path: str
    granted_at: datetime
    expires_at: datetime
    duration_minutes: int
    approved_by: str  # "cli" or "web"

    @property
    def server_name(self) -> str:
        """Alias for mcp_name for backward compatibility."""
        return self.mcp_name


@dataclass
class ConfigChangeRequest:
    """A pending configuration change request for sensitive paths.

    Granular: Each sensitive path gets its own approval code.
    Safe paths are applied immediately.
    """

    id: str
    server_name: str  # Name of the MCP server being modified
    change_type: str  # 'add', 'modify', 'remove'
    code: str  # 8-char approval code
    status: AccessRequestStatus
    created_at: datetime
    expires_at: datetime  # Request expires if not approved
    # Specific sensitive path being approved (granular)
    sensitive_path: str = ""  # The specific path requiring approval
    # The path index in the args array (for precise replacement)
    path_index: int = -1
    # Complete args array with the sensitive path included
    target_args: list[str] = field(default_factory=list)
    # Original config before any changes
    original_config: dict[str, Any] = field(default_factory=dict)
    # Config version/checksum for race condition detection
    original_config_checksum: str = ""  # SHA256 of serialized original config
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigChangeGrant:
    """An approved time-bound config change for a specific path."""

    id: str
    request_id: str
    server_name: str
    granted_at: datetime
    expires_at: datetime
    duration_minutes: int
    approved_by: str
    # The specific sensitive path that was approved
    sensitive_path: str = ""
    # Path index in args for precise revert
    path_index: int = -1
    # Complete args array with approved path
    target_args: list[str] = field(default_factory=list)
    # Original args before this change (for revert)
    original_args: list[str] = field(default_factory=list)


class AccessRequestCreate(BaseModel):
    """Model for creating an access request."""

    mcp_name: str
    tool_name: str
    path: str
    metadata: dict[str, Any] = {}


class AccessRequestApprove(BaseModel):
    """Model for approving an access request."""

    code: str
    duration_minutes: int = 1  # Default 1 minute
    approved_by: str = "cli"  # or "web"


__all__ = [
    "AccessRequestStatus",
    "AccessRequest",
    "AccessGrant",
    "ConfigChangeRequest",
    "ConfigChangeGrant",
    "AccessRequestCreate",
    "AccessRequestApprove",
]
