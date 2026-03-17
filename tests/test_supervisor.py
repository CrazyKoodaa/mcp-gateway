"""Tests for mcp_gateway.supervisor module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.config import ServerConfig
from mcp_gateway.supervisor import (
    BackendState,
    BackendStats,
    ProcessSupervisor,
    SupervisedBackend,
    SupervisionConfig,
    supervise_backends,
)


class TestBackendState:
    """Tests for BackendState enum."""

    def test_states(self):
        """Test all backend states."""
        assert BackendState.STOPPED.value == "stopped"
        assert BackendState.STARTING.value == "starting"
        assert BackendState.RUNNING.value == "running"
        assert BackendState.CRASHED.value == "crashed"
        assert BackendState.BACKING_OFF.value == "backing_off"
        assert BackendState.FAILED.value == "failed"


class TestBackendStats:
    """Tests for BackendStats dataclass."""

    def test_default_values(self):
        """Test BackendStats default values."""
        stats = BackendStats()
        assert stats.start_count == 0
        assert stats.crash_count == 0
        assert stats.last_start_time is None
        assert stats.last_crash_time is None
        assert stats.consecutive_crashes == 0
        assert stats.total_uptime_seconds == 0.0

    def test_custom_values(self):
        """Test BackendStats with custom values."""
        stats = BackendStats(
            start_count=5,
            crash_count=2,
            last_start_time=1000.0,
            last_crash_time=2000.0,
            consecutive_crashes=1,
            total_uptime_seconds=500.0,
        )
        assert stats.start_count == 5
        assert stats.crash_count == 2
        assert stats.last_start_time == 1000.0


class TestSupervisionConfig:
    """Tests for SupervisionConfig dataclass."""

    def test_default_values(self):
        """Test SupervisionConfig default values."""
        config = SupervisionConfig()
        assert config.auto_restart is True
        assert config.max_restarts == 10
        assert config.restart_window_seconds == 60.0
        assert config.initial_backoff_seconds == 1.0
        assert config.max_backoff_seconds == 60.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter is True
        assert config.health_check_interval == 30.0
        assert config.health_check_timeout == 10.0
        assert config.max_consecutive_crashes == 5

    def test_custom_values(self):
        """Test SupervisionConfig with custom values."""
        config = SupervisionConfig(
            auto_restart=False,
            max_restarts=5,
            initial_backoff_seconds=2.0,
            max_backoff_seconds=30.0,
            jitter=False,
        )
        assert config.auto_restart is False
        assert config.max_restarts == 5
        assert config.initial_backoff_seconds == 2.0


class TestSupervisedBackend:
    """Tests for SupervisedBackend class."""

    @pytest.fixture
    def server_config(self):
        """Create a test server config."""
        return ServerConfig(name="test-server", command="npx", args=["test"])

    @pytest.fixture
    def supervision_config(self):
        """Create a test supervision config."""
        return SupervisionConfig(
            auto_restart=True, max_consecutive_crashes=3, health_check_interval=1.0
        )

    @pytest.fixture
    def supervised_backend(self, server_config, supervision_config):
        """Create a SupervisedBackend instance."""
        return SupervisedBackend(server_config, supervision_config)

    def test_initialization(self, server_config, supervision_config):
        """Test SupervisedBackend initialization."""
        sb = SupervisedBackend(server_config, supervision_config)

        assert sb.config == server_config
        assert sb.supervision_config == supervision_config
        assert sb.backend is None
        assert sb.state == BackendState.STOPPED
        assert sb.stats.start_count == 0
        assert sb._current_backoff == supervision_config.initial_backoff_seconds

    def test_name_property(self, supervised_backend):
        """Test name property."""
        assert supervised_backend.name == "test-server"

    def test_is_running_stopped(self, supervised_backend):
        """Test is_running when stopped."""
        assert supervised_backend.is_running is False

    @pytest.mark.asyncio
    async def test_start_success(self, supervised_backend):
        """Test successful backend start."""
        with patch.object(supervised_backend, "_health_check_loop", AsyncMock()):
            with patch("mcp_gateway.supervisor.BackendConnection") as mock_conn_class:
                mock_backend = MagicMock()
                mock_backend.connect = AsyncMock()
                mock_backend.is_connected = True
                mock_conn_class.return_value = mock_backend

                result = await supervised_backend.start()

                assert result is True
                assert supervised_backend.state == BackendState.RUNNING
                assert supervised_backend.stats.start_count == 1
                assert supervised_backend.stats.consecutive_crashes == 0

    @pytest.mark.asyncio
    async def test_start_already_running(self, supervised_backend):
        """Test starting when already running."""
        supervised_backend.state = BackendState.RUNNING

        result = await supervised_backend.start()

        assert result is True  # Returns True if already running

    @pytest.mark.asyncio
    async def test_start_failure(self, supervised_backend):
        """Test backend start failure."""
        with patch("mcp_gateway.supervisor.BackendConnection") as mock_conn_class:
            mock_backend = MagicMock()
            mock_backend.connect = AsyncMock(side_effect=Exception("Connection failed"))
            mock_conn_class.return_value = mock_backend

            result = await supervised_backend.start()

            assert result is False
            # State may be CRASHED or BACKING_OFF depending on auto-restart behavior
            assert supervised_backend.state in (BackendState.CRASHED, BackendState.BACKING_OFF)
            assert supervised_backend.stats.crash_count == 1

    @pytest.mark.asyncio
    async def test_stop(self, supervised_backend):
        """Test stopping backend."""
        # Setup a running backend
        supervised_backend.state = BackendState.RUNNING
        mock_backend = MagicMock()
        mock_backend.disconnect = AsyncMock()
        supervised_backend.backend = mock_backend
        supervised_backend._stop_event = asyncio.Event()

        await supervised_backend.stop()

        assert supervised_backend.state == BackendState.STOPPED
        assert supervised_backend.backend is None

    @pytest.mark.asyncio
    async def test_restart(self, supervised_backend):
        """Test restarting backend."""
        with patch.object(supervised_backend, "stop", AsyncMock()) as mock_stop:
            with patch.object(
                supervised_backend, "start", AsyncMock(return_value=True)
            ) as mock_start:
                result = await supervised_backend.restart()

                mock_stop.assert_called_once()
                mock_start.assert_called_once()
                assert result is True

    @pytest.mark.asyncio
    async def test_handle_crash_auto_restart_disabled(self, supervised_backend):
        """Test crash handling when auto-restart is disabled."""
        supervised_backend.supervision_config.auto_restart = False

        await supervised_backend._handle_crash(Exception("Test crash"))

        assert supervised_backend.state == BackendState.FAILED

    @pytest.mark.asyncio
    async def test_handle_crash_max_consecutive_crashes(self, supervised_backend):
        """Test crash handling when max consecutive crashes reached."""
        supervised_backend.stats.consecutive_crashes = 5
        supervised_backend.supervision_config.max_consecutive_crashes = 5

        await supervised_backend._handle_crash(Exception("Test crash"))

        assert supervised_backend.state == BackendState.FAILED

    @pytest.mark.asyncio
    async def test_schedule_restart(self, supervised_backend):
        """Test scheduling a restart."""
        supervised_backend._schedule_restart(backoff=1.0)

        assert supervised_backend.state == BackendState.BACKING_OFF
        assert supervised_backend._restart_task is not None

        # Cancel the task to clean up
        supervised_backend._restart_task.cancel()
        try:
            await supervised_backend._restart_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_restart_after_delay(self, supervised_backend):
        """Test restart after delay."""
        with patch.object(supervised_backend, "start", AsyncMock()) as mock_start:
            # Start in background and cancel quickly
            task = asyncio.create_task(supervised_backend._restart_after_delay(0.01))
            await asyncio.sleep(0.02)

            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class TestProcessSupervisor:
    """Tests for ProcessSupervisor class."""

    @pytest.fixture
    def mock_backend_manager(self):
        """Create a mock backend manager."""
        return MagicMock()

    @pytest.fixture
    def supervisor(self, mock_backend_manager):
        """Create a ProcessSupervisor instance."""
        return ProcessSupervisor(mock_backend_manager)

    @pytest.fixture
    def server_configs(self):
        """Create test server configs."""
        return {
            "server1": ServerConfig(name="server1", command="npx", args=["pkg1"]),
            "server2": ServerConfig(name="server2", command="uvx", args=["pkg2"]),
        }

    def test_initialization(self, mock_backend_manager):
        """Test ProcessSupervisor initialization."""
        ps = ProcessSupervisor(mock_backend_manager)

        assert ps.backend_manager == mock_backend_manager
        assert ps._running is False
        assert len(ps._supervised) == 0

    @pytest.mark.asyncio
    async def test_start_supervision(self, supervisor, server_configs):
        """Test starting supervision."""
        with patch.object(SupervisedBackend, "start", AsyncMock(return_value=True)):
            await supervisor.start_supervision(server_configs)

            assert supervisor._running is True
            assert len(supervisor._supervised) == 2
            assert "server1" in supervisor._supervised
            assert "server2" in supervisor._supervised

    @pytest.mark.asyncio
    async def test_stop_supervision(self, supervisor, server_configs):
        """Test stopping supervision."""
        with patch.object(SupervisedBackend, "start", AsyncMock(return_value=True)):
            await supervisor.start_supervision(server_configs)

        with patch.object(SupervisedBackend, "stop", AsyncMock()):
            await supervisor.stop_supervision()

            assert supervisor._running is False
            assert len(supervisor._supervised) == 0

    @pytest.mark.asyncio
    async def test_restart_backend(self, supervisor, server_configs):
        """Test restarting a specific backend."""
        with patch.object(SupervisedBackend, "start", AsyncMock(return_value=True)):
            await supervisor.start_supervision(server_configs)

        with patch.object(
            SupervisedBackend, "restart", AsyncMock(return_value=True)
        ) as mock_restart:
            result = await supervisor.restart_backend("server1")

            assert result is True

    @pytest.mark.asyncio
    async def test_restart_backend_unknown(self, supervisor):
        """Test restarting an unknown backend."""
        result = await supervisor.restart_backend("nonexistent")

        assert result is False

    def test_get_stats(self, supervisor, server_configs):
        """Test getting supervision statistics."""
        # Setup supervised backends with stats
        sb1 = MagicMock()
        sb1.state = BackendState.RUNNING
        sb1.stats.start_count = 5
        sb1.stats.crash_count = 1
        sb1.stats.consecutive_crashes = 0
        sb1.stats.total_uptime_seconds = 100.0
        sb1.is_running = True

        sb2 = MagicMock()
        sb2.state = BackendState.CRASHED
        sb2.stats.start_count = 3
        sb2.stats.crash_count = 3
        sb2.stats.consecutive_crashes = 3
        sb2.stats.total_uptime_seconds = 50.0
        sb2.is_running = False

        supervisor._supervised = {"server1": sb1, "server2": sb2}

        stats = supervisor.get_stats()

        assert "server1" in stats
        assert "server2" in stats
        assert stats["server1"]["state"] == "running"
        assert stats["server1"]["starts"] == 5
        assert stats["server2"]["state"] == "crashed"
        assert stats["server2"]["crashes"] == 3


class TestSuperviseBackends:
    """Tests for supervise_backends convenience function."""

    @pytest.mark.asyncio
    async def test_supervise_backends(self):
        """Test the supervise_backends convenience function."""
        mock_backend_manager = MagicMock()
        configs = {"server1": ServerConfig(name="server1", command="npx", args=["pkg"])}

        with patch.object(SupervisedBackend, "start", AsyncMock(return_value=True)):
            supervisor = await supervise_backends(mock_backend_manager, configs)

            assert isinstance(supervisor, ProcessSupervisor)
            assert supervisor._running is True

            # Cleanup
            with patch.object(SupervisedBackend, "stop", AsyncMock()):
                await supervisor.stop_supervision()
