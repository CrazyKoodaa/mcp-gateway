"""Path security service for detecting sensitive filesystem paths.

Provides platform-aware detection of system paths that require approval.
"""

import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal


@dataclass(frozen=True)
class PathCheckResult:
    """Result of a path security check.

    Attributes:
        path: The original path checked
        is_sensitive: Whether the path requires approval
        matched_pattern: The pattern that matched (if sensitive)
        platform: The platform this check was performed on
    """

    path: str
    is_sensitive: bool
    matched_pattern: str | None = None
    platform: Literal["windows", "darwin", "linux"] = "linux"


class PathSecurityService:
    """Service for detecting sensitive filesystem paths.

    This service is platform-aware and uses different sensitivity
    patterns based on the operating system.

    Example:
        >>> service = PathSecurityService()
        >>> result = service.check_path("/etc/passwd")
        >>> result.is_sensitive
        True
    """

    # Platform-specific sensitive path patterns
    _WINDOWS_PATTERNS: Final[list[str]] = [
        r"C:\\",  # Root of C: drive
        r"C:\\Windows",
        r"C:\\Windows\\System32",
        r"C:\\Program Files",
        r"C:\\Program Files (x86)",
        r"C:\\ProgramData",
        r"C:\\Users\\*\\AppData",
        r"C:\\Users\\*\\.ssh",
        r"C:\\Users\\Administrator",
        r"C:\\inetpub",
        r"C:\\inetpub\\wwwroot",
        "*.pem",
        "*.key",
        "*.pfx",
        "*password*",
        "*secret*",
        "*credential*",
        "NTUSER.DAT",
        "SAM",
        "SECURITY",
        "SYSTEM",
    ]

    _MACOS_PATTERNS: Final[list[str]] = [
        "/",
        "/etc",
        "/System",
        "/System/Library",
        "/System/Library/CoreServices",
        "/usr",
        "/usr/bin",
        "/usr/sbin",
        "/bin",
        "/sbin",
        "/var",
        "/var/log",
        "/private",
        "/private/etc",
        "/private/var",
        "/Library",
        "/Library/Keychains",
        "/Users/*/.ssh",
        "/Users/*/Library/Keychains",
        "/Users/*/Library/Passwords",
        "*.pem",
        "*.key",
        "*.p12",
        "*password*",
        "*secret*",
        "*credential*",
    ]

    _LINUX_PATTERNS: Final[list[str]] = [
        "/",
        "/etc",
        "/sys",
        "/proc",
        "/dev",
        "/boot",
        "/root",
        "/var",
        "/var/log",
        "/var/spool",
        "/var/mail",
        "/var/lib",
        "/usr",
        "/usr/bin",
        "/usr/sbin",
        "/usr/local",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/opt",
        "/snap",
        "/home/*/.ssh",
        "/home/*/.gnupg",
        "/home/*/.local/share/keyrings",
        "*.pem",
        "*.key",
        "*password*",
        "*secret*",
        "*credential*",
        "*shadow*",
        "/tmp",
        "/run",
        "/srv",
    ]

    def __init__(self, platform: Literal["windows", "darwin", "linux"] | None = None) -> None:
        """Initialize the path security service.

        Args:
            platform: Override platform detection. If None, auto-detects.
        """
        if platform is None:
            platform = self._detect_platform()
        self._platform = platform
        self._patterns = self._get_patterns_for_platform(platform)

    @property
    def platform(self) -> Literal["windows", "darwin", "linux"]:
        """The platform this service is configured for."""
        return self._platform

    @staticmethod
    def _detect_platform() -> Literal["windows", "darwin", "linux"]:
        """Detect the current operating system."""
        if sys.platform == "win32":
            return "windows"
        elif sys.platform == "darwin":
            return "darwin"
        else:
            return "linux"

    def _get_patterns_for_platform(
        self, platform: Literal["windows", "darwin", "linux"]
    ) -> list[str]:
        """Get the sensitivity patterns for a platform."""
        patterns = {
            "windows": self._WINDOWS_PATTERNS,
            "darwin": self._MACOS_PATTERNS,
            "linux": self._LINUX_PATTERNS,
        }
        return patterns.get(platform, self._LINUX_PATTERNS)

    def check_path(self, path: str) -> PathCheckResult:
        """Check if a path is sensitive and requires approval.

        Args:
            path: The filesystem path to check

        Returns:
            PathCheckResult with sensitivity information

        Example:
            >>> service = PathSecurityService()
            >>> result = service.check_path("/etc/passwd")
            >>> result.is_sensitive
            True
            >>> result.matched_pattern
            '/etc'
        """
        normalized_path = self._normalize_path(path)

        for pattern in self._patterns:
            if self._path_matches_pattern(normalized_path, path, pattern):
                return PathCheckResult(
                    path=path,
                    is_sensitive=True,
                    matched_pattern=pattern,
                    platform=self._platform,
                )

        return PathCheckResult(
            path=path,
            is_sensitive=False,
            matched_pattern=None,
            platform=self._platform,
        )

    def check_paths(self, paths: list[str]) -> list[PathCheckResult]:
        """Check multiple paths for sensitivity.

        Args:
            paths: List of filesystem paths to check

        Returns:
            List of PathCheckResult for each path
        """
        return [self.check_path(p) for p in paths]

    def get_sensitive_paths(self, paths: list[str]) -> list[str]:
        """Filter a list to return only sensitive paths.

        Args:
            paths: List of filesystem paths

        Returns:
            Sublist containing only sensitive paths
        """
        results = self.check_paths(paths)
        return [r.path for r in results if r.is_sensitive]

    def is_sensitive_path(self, path: str) -> bool:
        """Check if a single path is sensitive.

        Convenience method for backward compatibility.

        Args:
            path: The filesystem path to check

        Returns:
            True if the path is sensitive
        """
        result = self.check_path(path)
        return result.is_sensitive

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize path for cross-platform comparison.

        Converts backslashes to forward slashes and lowercases.
        """
        normalized = path.replace("\\", "/")
        if len(normalized) > 1:
            normalized = normalized.rstrip("/")
        return normalized.lower()

    def _path_matches_pattern(self, normalized_path: str, original_path: str, pattern: str) -> bool:
        """Check if a path matches a sensitivity pattern.

        Args:
            normalized_path: Lowercase, forward-slash normalized path
            original_path: Original path for special cases
            pattern: The sensitivity pattern to match against

        Returns:
            True if the path matches the pattern
        """
        normalized_pattern = self._normalize_path(pattern)

        # Special case: root path matching
        if self._is_root_pattern(normalized_pattern):
            return self._matches_root(original_path)

        # Direct match
        if normalized_path == normalized_pattern:
            return True

        # Pattern with wildcards
        if "*" in pattern or "?" in pattern:
            return self._matches_wildcard(normalized_path, pattern, normalized_pattern)

        # Path containment check
        return self._matches_containment(normalized_path, pattern, normalized_pattern)

    def _is_root_pattern(self, normalized_pattern: str) -> bool:
        """Check if pattern represents a root directory."""
        return normalized_pattern == "/" or normalized_pattern == "c:/"

    def _matches_root(self, original_path: str) -> bool:
        """Check if path is a root directory."""
        if self._platform == "windows":
            # Check for drive root like C:\ or C:/*
            drive_pattern = r"^[a-zA-Z]:[/\\]?$"
            return bool(re.match(drive_pattern, original_path.strip()))
        else:
            # Unix root
            return original_path == "/" or original_path.rstrip("/") == ""

    def _matches_wildcard(
        self, normalized_path: str, pattern: str, normalized_pattern: str
    ) -> bool:
        """Check if path matches a wildcard pattern."""
        # Direct wildcard match
        if fnmatch.fnmatch(normalized_path, normalized_pattern):
            return True

        # Check if any parent directory matches
        try:
            parts = Path(normalized_path.replace("/", "/")).parts
            for i in range(len(parts)):
                partial = "/".join(parts[: i + 1]).lower()
                if fnmatch.fnmatch(partial, normalized_pattern):
                    return True
        except (ValueError, OSError):
            pass

        return False

    def _matches_containment(
        self, normalized_path: str, pattern: str, normalized_pattern: str
    ) -> bool:
        """Check if path is within or equals a sensitive directory."""
        # Try filesystem-based containment check
        try:
            sensitive_str = pattern.replace("\\", "/")
            target_str = normalized_path

            sensitive_p = Path(sensitive_str)
            target_p = Path(target_str)

            # Resolve if exists
            try:
                if sensitive_p.exists():
                    sensitive_resolved = sensitive_p.resolve()
                else:
                    sensitive_resolved = sensitive_p

                if target_p.exists():
                    target_resolved = target_p.resolve()
                else:
                    target_resolved = target_p

                # Direct match
                if target_resolved == sensitive_resolved:
                    return True

                # Containment check
                try:
                    target_resolved.relative_to(sensitive_resolved)
                    return True
                except ValueError:
                    pass
            except (OSError, RuntimeError):
                pass
        except (ValueError, OSError):
            pass

        # Fallback: string prefix check
        if normalized_path.startswith(normalized_pattern + "/"):
            return True
        if normalized_path.startswith(normalized_pattern + "\\"):
            return True

        return False
