"""Sensitive path patterns for access control.

Platform-specific patterns that require approval for config changes.
"""

import sys

if sys.platform == "win32":
    # Windows sensitive paths
    SENSITIVE_PATH_PATTERNS = [
        r"C:\\",  # Root of C: drive
        r"C:\\Windows",
        r"C:\\Windows\\System32",
        r"C:\\Program Files",
        r"C:\\Program Files (x86)",
        r"C:\\ProgramData",
        r"C:\\Users\\*\\AppData",  # User app data
        r"C:\\Users\\*\\.ssh",
        r"C:\\Users\\Administrator",
        r"C:\\inetpub",  # IIS
        r"C:\\inetpub\\wwwroot",
        "*.pem",
        "*.key",
        "*.pfx",  # Windows certificates
        "*password*",
        "*secret*",
        "*credential*",
        "NTUSER.DAT",
        "SAM",  # Security Account Manager
        "SECURITY",
        "SYSTEM",
    ]
elif sys.platform == "darwin":
    # macOS sensitive paths
    SENSITIVE_PATH_PATTERNS = [
        "/",  # Root directory
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
        "*.p12",  # macOS certificates
        "*password*",
        "*secret*",
        "*credential*",
        ".DS_Store",  # Not sensitive but system file
    ]
else:
    # Linux and other Unix-like systems (default)
    SENSITIVE_PATH_PATTERNS = [
        "/",  # Root directory - ultimate sensitive path
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


__all__ = ["SENSITIVE_PATH_PATTERNS"]
