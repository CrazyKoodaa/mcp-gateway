"""Utility functions for access control."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .patterns import SENSITIVE_PATH_PATTERNS


def _normalize_path_for_comparison(path: str) -> str:
    """Normalize path for cross-platform comparison.

    Converts Windows paths to lowercase and normalizes separators.
    """
    # Normalize backslashes to forward slashes for comparison
    normalized = path.replace('\\', '/')
    # Remove trailing slash except for root "/"
    if len(normalized) > 1:
        normalized = normalized.rstrip('/')
    return normalized.lower()


def is_sensitive_path(path: str) -> bool:
    """Check if a path is considered sensitive and requires approval.

    Args:
        path: The path to check

    Returns:
        True if the path is sensitive
    """
    import sys

    original_path = path
    path_normalized = _normalize_path_for_comparison(path)

    for pattern in SENSITIVE_PATH_PATTERNS:
        pattern_normalized = _normalize_path_for_comparison(pattern)

        # Special case: root path "/" or "C:\\" only matches exactly, not any path
        if pattern_normalized == '/' or pattern_normalized == 'c:/':
            if sys.platform == "win32":
                # On Windows, check for drive root like C:\ or C:/*
                if re.match(r'^[a-zA-Z]:[/\\]?$', original_path.strip()) or \
                   re.match(r'^[a-zA-Z]:[/\\].*', original_path.strip()):
                    # Check if it's just the drive root
                    drive_root = original_path.strip().rstrip('/\\')
                    if len(drive_root) <= 2:  # "C:" or "C:\"
                        return True
            else:
                # Unix root
                if original_path == '/' or original_path.rstrip('/') == '':
                    return True
            continue

        # Direct match
        if path_normalized == pattern_normalized:
            return True

        # Pattern with wildcards
        if '*' in pattern or '?' in pattern:
            # Convert pattern to use forward slashes for fnmatch
            pattern_for_match = pattern_normalized
            if fnmatch.fnmatch(path_normalized, pattern_for_match):
                return True
            # Also check if any parent matches
            try:
                path_obj = Path(path.replace('\\', '/'))
                parts = path_obj.parts
                for i in range(len(parts)):
                    # Reconstruct path properly handling absolute paths
                    partial_path = Path(*parts[:i+1])
                    # For absolute paths, ensure leading slash
                    if parts[0] == '/':
                        partial = '/' + '/'.join(parts[1:i+1]).lower()
                    else:
                        partial = str(partial_path).lower()
                    if fnmatch.fnmatch(partial, pattern_for_match):
                        return True
            except (ValueError, OSError):
                # Path parsing or filesystem error
                pass
        else:
            # Check if path is within or equals the sensitive path
            try:
                # Normalize both paths for comparison
                sensitive_str = pattern.replace('\\', '/')
                target_str = path.replace('\\', '/')

                sensitive_path = Path(sensitive_str)
                target_path = Path(target_str)

                # Try to resolve if exists
                try:
                    sensitive_resolved = (
                        sensitive_path.resolve() if sensitive_path.exists()
                        else sensitive_path
                    )
                    target_resolved = (
                        target_path.resolve() if target_path.exists()
                        else target_path
                    )

                    if target_resolved == sensitive_resolved:
                        return True

                    # Check if target is inside sensitive
                    try:
                        target_resolved.relative_to(sensitive_resolved)
                        return True
                    except ValueError:
                        pass
                except (OSError, RuntimeError):
                    # Filesystem errors during resolve/exists checks
                    pass

            except (ValueError, OSError):
                # Path parsing errors
                pass

            # Fallback: string prefix check with normalized separators
            if (path_normalized.startswith(pattern_normalized + '/') or
                path_normalized == pattern_normalized):
                return True
            # Windows-style check
            if path_normalized.startswith(pattern_normalized + '\\'):
                return True

    return False


def extract_paths_from_args(args: list[str]) -> list[str]:
    """Extract filesystem paths from server arguments.

    Args:
        args: Server command arguments

    Returns:
        List of potential paths
    """
    paths = []
    for arg in args:
        # Skip flags and options
        if arg.startswith('-') or arg.startswith('--'):
            continue
        # Check if it looks like a path
        if arg.startswith('/') or arg.startswith('~/') or arg.startswith('./'):
            paths.append(arg)
        # Check for home directory expansion
        if arg.startswith('~'):
            paths.append(arg)
    return paths


def get_sensitive_paths_in_config(config: dict[str, Any]) -> list[str]:
    """Get all sensitive paths in a server configuration.

    Args:
        config: Server configuration dict

    Returns:
        List of sensitive paths found
    """
    sensitive = []
    args = config.get('args', [])
    paths = extract_paths_from_args(args)

    for path in paths:
        if is_sensitive_path(path):
            sensitive.append(path)

    return sensitive


def compute_config_checksum(config: dict[str, Any]) -> str:
    """Compute a checksum of the config for version tracking.

    Args:
        config: Server configuration dict

    Returns:
        SHA256 hex digest of serialized config
    """
    # Sort keys for consistent serialization
    config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(config_str.encode()).hexdigest()[:16]  # First 16 chars sufficient


__all__ = [
    "_normalize_path_for_comparison",
    "is_sensitive_path",
    "extract_paths_from_args",
    "get_sensitive_paths_in_config",
    "compute_config_checksum",
]
