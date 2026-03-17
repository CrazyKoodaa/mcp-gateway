"""Tests for lockfile management."""

import os

import pytest

from mcp_gateway.lockfile import (
    LockfileManager,
    format_lock_error,
    format_port_error,
)


class TestLockfileManager:
    """Tests for LockfileManager class."""

    def test_acquire_lock_success(self, tmp_path):
        """Test acquiring a lock when no lock exists."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        acquired, existing_pid = lock.acquire()

        assert acquired is True
        assert existing_pid is None
        assert lock_path.exists()
        assert lock_path.read_text().strip() == str(os.getpid())

        # Cleanup
        lock.release()

    def test_acquire_lock_already_held_by_self(self, tmp_path):
        """Test acquiring lock when we already hold it."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        # First acquire
        acquired, _ = lock.acquire()
        assert acquired is True

        # Second acquire should fail (we already hold it)
        lock2 = LockfileManager(str(lock_path))
        acquired2, existing_pid = lock2.acquire()

        # Should detect our own PID as holding the lock
        assert acquired2 is False
        assert existing_pid == os.getpid()

        # Cleanup
        lock.release()

    def test_acquire_stale_lock(self, tmp_path):
        """Test acquiring lock when previous process died."""
        lock_path = tmp_path / "test.lock"

        # Create a lockfile with a non-existent PID
        fake_pid = 99999
        lock_path.write_text(str(fake_pid))

        lock = LockfileManager(str(lock_path))
        acquired, existing_pid = lock.acquire()

        # Should succeed because the process is not running
        assert acquired is True
        assert existing_pid is None

        # Cleanup
        lock.release()

    def test_release_lock(self, tmp_path):
        """Test releasing a lock."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        # Acquire and release
        lock.acquire()
        assert lock_path.exists()

        lock.release()
        assert not lock_path.exists()

    def test_release_nonexistent_lock(self, tmp_path):
        """Test releasing a lock that doesn't exist (should not error)."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        # Should not raise
        lock.release()

    def test_get_lock_info_no_lock(self, tmp_path):
        """Test get_lock_info when no lock exists."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        info = lock.get_lock_info()

        assert info["lock_path"] == str(lock_path)
        assert info["lock_exists"] is False
        assert info["pid"] is None
        assert info["our_pid"] == os.getpid()
        assert info["we_own_lock"] is False

    def test_get_lock_info_with_lock(self, tmp_path):
        """Test get_lock_info when lock exists."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        lock.acquire()
        info = lock.get_lock_info()

        assert info["lock_path"] == str(lock_path)
        assert info["lock_exists"] is True
        assert info["pid"] == os.getpid()
        assert info["our_pid"] == os.getpid()
        assert info["we_own_lock"] is True

        lock.release()

    def test_custom_lock_path_via_env(self, tmp_path, monkeypatch):
        """Test custom lock path via environment variable."""
        custom_path = str(tmp_path / "custom.lock")
        monkeypatch.setenv("MCP_GATEWAY_LOCKFILE", custom_path)

        lock = LockfileManager()

        assert str(lock.lock_path) == custom_path

    def test_is_process_running(self):
        """Test _is_process_running helper."""
        lock = LockfileManager()

        # Current process should be running
        assert lock._is_process_running(os.getpid()) is True

        # Non-existent process should not be running
        assert lock._is_process_running(99999) is False


class TestFormatFunctions:
    """Tests for error message formatting functions."""

    def test_format_lock_error_with_pid(self, tmp_path):
        """Test format_lock_error when PID is known."""
        lock_path = tmp_path / "test.lock"
        message = format_lock_error(3000, 12345, lock_path)

        assert "MCP Gateway is already running" in message
        assert "12345" in message
        assert "3000" in message
        assert str(lock_path) in message
        assert "kill 12345" in message
        assert "--port 3001" in message

    def test_format_lock_error_without_pid(self, tmp_path):
        """Test format_lock_error when PID is unknown."""
        lock_path = tmp_path / "test.lock"
        message = format_lock_error(3000, None, lock_path)

        assert "MCP Gateway is already running" in message
        assert "stale lockfile" in message
        assert str(lock_path) in message
        assert "rm" in message

    def test_format_port_error(self):
        """Test format_port_error."""
        message = format_port_error(3000)

        assert "Port 3000 is already in use" in message
        assert "lsof" in message
        assert "--port 3001" in message


class TestLockfileIntegration:
    """Integration tests for lockfile behavior."""

    def test_concurrent_access_simulation(self, tmp_path):
        """Test that two managers properly detect each other."""
        lock_path = tmp_path / "test.lock"

        # First instance acquires lock
        lock1 = LockfileManager(str(lock_path))
        acquired1, _ = lock1.acquire()
        assert acquired1 is True

        # Second instance should fail
        lock2 = LockfileManager(str(lock_path))
        acquired2, pid2 = lock2.acquire()
        assert acquired2 is False
        assert pid2 == os.getpid()

        # First instance releases
        lock1.release()

        # Now second instance can acquire (after process exits simulation)
        # We simulate by just removing the file since we're the same process
        lock_path.unlink(missing_ok=True)
        acquired3, _ = lock2.acquire()
        assert acquired3 is True

        lock2.release()

    def test_signal_handlers_registered(self, tmp_path):
        """Test that signal handlers are registered on acquire."""
        lock_path = tmp_path / "test.lock"
        lock = LockfileManager(str(lock_path))

        # Before acquire, no handlers registered
        assert lock._atexit_registered is False

        # After acquire, handlers registered
        lock.acquire()
        assert lock._atexit_registered is True

        lock.release()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
