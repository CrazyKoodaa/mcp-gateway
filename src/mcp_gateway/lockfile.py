"""PID-based lockfile management for MCP Gateway.

Prevents multiple gateway instances from running simultaneously
and provides helpful error messages when conflicts occur.
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType


class LockfileManager:
    """Manages a PID-based lockfile to prevent multiple gateway instances.
    
    The lockfile stores the PID of the running gateway process. When a new
    instance starts, it checks if the lockfile exists and if the process
    is still running. If the process is dead (stale lock), the lockfile
    is removed and the new instance can acquire the lock.
    
    Args:
        lock_path: Path to the lockfile. Defaults to /tmp/mcp-gateway.lock
                   or MCP_GATEWAY_LOCKFILE env var.
    
    Example:
        >>> lock = LockfileManager()
        >>> acquired, existing_pid = lock.acquire()
        >>> if not acquired:
        ...     print(f"Gateway already running on PID {existing_pid}")
        ...     sys.exit(1)
        >>> # Lock acquired, run gateway...
        >>> lock.release()  # Or use context manager
    """

    def __init__(self, lock_path: str | None = None) -> None:
        """Initialize lockfile manager.
        
        Args:
            lock_path: Custom lockfile path. If None, uses env var
                      MCP_GATEWAY_LOCKFILE or default /tmp/mcp-gateway.lock
        """
        if lock_path:
            self.lock_path = Path(lock_path)
        else:
            # Use env var or default
            default_path = "/tmp/mcp-gateway.lock"
            self.lock_path = Path(os.environ.get("MCP_GATEWAY_LOCKFILE", default_path))
        
        self._pid: int | None = None
        self._atexit_registered: bool = False

    def acquire(self) -> tuple[bool, int | None]:
        """Try to acquire the lock.
        
        Returns:
            Tuple of (success, existing_pid). If success is False,
            existing_pid contains the PID of the running gateway (or None
            if we couldn't determine it).
        """
        # Check if lockfile exists
        if self.lock_path.exists():
            existing_pid = self._read_pid()
            
            if existing_pid is not None:
                # Check if process is actually running
                if self._is_process_running(existing_pid):
                    # Another instance is running
                    return False, existing_pid
                else:
                    # Stale lockfile - process died without cleanup
                    self._remove_lock()
            else:
                # Invalid lockfile - remove it
                self._remove_lock()
        
        # Try to acquire lock
        try:
            self._write_pid()
            self._pid = os.getpid()
            
            # Register cleanup on exit
            if not self._atexit_registered:
                atexit.register(self.release)
                self._register_signal_handlers()
                self._atexit_registered = True
            
            return True, None
            
        except OSError as e:
            # Failed to write lockfile
            return False, None

    def release(self) -> None:
        """Release the lock by removing the lockfile.
        
        This is called automatically on normal exit via atexit.
        It's safe to call multiple times.
        """
        if self._pid is not None and self._pid != os.getpid():
            # We forked, don't remove parent's lock
            return
        
        self._remove_lock()
        self._pid = None

    def _read_pid(self) -> int | None:
        """Read PID from lockfile.
        
        Returns:
            PID as integer, or None if file is corrupted.
        """
        try:
            content = self.lock_path.read_text().strip()
            return int(content)
        except (ValueError, OSError):
            return None

    def _write_pid(self) -> None:
        """Write current PID to lockfile atomically."""
        # Write to temp file then rename for atomicity
        temp_path = self.lock_path.with_suffix(".tmp")
        temp_path.write_text(str(os.getpid()))
        temp_path.rename(self.lock_path)

    def _remove_lock(self) -> None:
        """Remove the lockfile if it exists."""
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID exists.
        
        Args:
            pid: Process ID to check.
            
        Returns:
            True if process exists, False otherwise.
        """
        try:
            # Signal 0 is special - it performs error checking without sending signal
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _register_signal_handlers(self) -> None:
        """Register signal handlers to ensure cleanup on SIGTERM/SIGINT."""
        def signal_handler(signum: int, frame: FrameType | None) -> None:
            self.release()
            # Re-raise default handler
            signal.default_int_handler(signum, frame)
        
        # Only register if not already registered
        old_term = signal.signal(signal.SIGTERM, signal_handler)
        old_int = signal.signal(signal.SIGINT, signal_handler)
        
        # Store old handlers to chain them if needed
        self._old_sigterm = old_term
        self._old_sigint = old_int

    def get_lock_info(self) -> dict[str, str | int | None]:
        """Get information about current lock state.
        
        Returns:
            Dict with lock_path, lock_exists, pid keys.
        """
        pid = None
        if self.lock_path.exists():
            pid = self._read_pid()
        
        return {
            "lock_path": str(self.lock_path),
            "lock_exists": self.lock_path.exists(),
            "pid": pid,
            "our_pid": os.getpid(),
            "we_own_lock": self._pid == os.getpid() if self._pid else False,
        }


def format_lock_error(port: int, existing_pid: int | None, lock_path: Path) -> str:
    """Format a user-friendly error message when lock cannot be acquired.
    
    Args:
        port: The port the gateway was trying to bind to.
        existing_pid: PID of the running gateway instance, or None.
        lock_path: Path to the lockfile.
        
    Returns:
        Formatted error message with actionable solutions.
    """
    lines = [
        "",
        "❌ MCP Gateway is already running!",
        "",
    ]
    
    if existing_pid:
        lines.extend([
            f"   PID:      {existing_pid}",
            f"   Port:     {port}",
            f"   Lockfile: {lock_path}",
            "",
            "Options:",
            f"  1. Stop existing instance:  kill {existing_pid}",
            f"  2. Use different port:      mcp-gateway --port {port + 1}",
        ])
    else:
        lines.extend([
            f"   Port:     {port}",
            f"   Lockfile: {lock_path}",
            "",
            "A lockfile exists but the process appears to have died.",
            "",
            "Options:",
            f"  1. Remove stale lockfile:   rm {lock_path}",
            f"  2. Use different port:      mcp-gateway --port {port + 1}",
        ])
    
    lines.append("")
    return "\n".join(lines)


def format_port_error(port: int) -> str:
    """Format a user-friendly error message when port is in use.
    
    This is used when we get OSError [Errno 98] but no lockfile exists
    (e.g., another service is using the port).
    
    Args:
        port: The port that is in use.
        
    Returns:
        Formatted error message with actionable solutions.
    """
    return """
❌ Port {} is already in use!

This could mean:
  - Another MCP Gateway instance is running (without lockfile)
  - Another service is using port {}

Options:
  1. Find and stop the process:  lsof -ti:{} | xargs kill -9
  2. Use a different port:       mcp-gateway --port {}
  3. Check what's using it:      lsof -i:{}

""".format(port, port, port, port + 1, port)
