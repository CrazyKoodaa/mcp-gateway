"""Dynamic path access control for MCP Gateway.

Provides time-bound access grants with approval workflow.
Also supports time-bound configuration changes for sensitive paths.
"""

from .manager import AccessControlManager
from .models import (
    AccessGrant,
    AccessRequest,
    AccessRequestApprove,
    AccessRequestCreate,
    AccessRequestStatus,
    ConfigChangeGrant,
    ConfigChangeRequest,
)
from .patterns import SENSITIVE_PATH_PATTERNS
from .utils import (
    _normalize_path_for_comparison,
    compute_config_checksum,
    extract_paths_from_args,
    get_sensitive_paths_in_config,
    is_sensitive_path,
)

# Global access control instance
access_control: AccessControlManager | None = None


def init_access_control(
    request_timeout_minutes: int = 10,
    default_grant_duration: int = 1,
    cleanup_interval_seconds: int = 60,
) -> AccessControlManager:
    """Initialize global access control manager.

    Args:
        request_timeout_minutes: How long pending requests remain valid
        default_grant_duration: Default approval duration in minutes
        cleanup_interval_seconds: How often to cleanup expired items

    Returns:
        Initialized AccessControlManager
    """
    global access_control
    access_control = AccessControlManager(
        request_timeout_minutes=request_timeout_minutes,
        default_grant_duration=default_grant_duration,
        cleanup_interval_seconds=cleanup_interval_seconds,
    )
    access_control.start()
    return access_control


__all__ = [
    "AccessControlManager",
    "AccessRequest",
    "AccessGrant",
    "AccessRequestStatus",
    "AccessRequestCreate",
    "AccessRequestApprove",
    "ConfigChangeRequest",
    "ConfigChangeGrant",
    "SENSITIVE_PATH_PATTERNS",
    "is_sensitive_path",
    "extract_paths_from_args",
    "get_sensitive_paths_in_config",
    "compute_config_checksum",
    "_normalize_path_for_comparison",
    "init_access_control",
    "access_control",
]
