"""Process supervision for auto-restarting crashed stdio servers."""

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum

from .backends import BackendConnection, BackendManager
from .config import ServerConfig

logger = logging.getLogger(__name__)


class BackendState(Enum):
    """State of a supervised backend."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CRASHED = "crashed"
    BACKING_OFF = "backing_off"
    FAILED = "failed"


@dataclass
class BackendStats:
    """Statistics for a supervised backend."""

    start_count: int = 0
    crash_count: int = 0
    last_start_time: float | None = None
    last_crash_time: float | None = None
    consecutive_crashes: int = 0
    total_uptime_seconds: float = 0.0


@dataclass
class SupervisionConfig:
    """Configuration for process supervision."""

    # Restart settings
    auto_restart: bool = True
    max_restarts: int = 10
    restart_window_seconds: float = 60.0

    # Backoff settings
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True

    # Health check settings
    health_check_interval: float = 30.0
    health_check_timeout: float = 10.0

    # Failure threshold
    max_consecutive_crashes: int = 5


class SupervisedBackend:
    """A backend with supervision capabilities."""

    def __init__(
        self,
        config: ServerConfig,
        supervision_config: SupervisionConfig,
    ):
        self.config = config
        self.supervision_config = supervision_config

        self.backend: BackendConnection | None = None
        self.state = BackendState.STOPPED
        self.stats = BackendStats()

        self._restart_task: asyncio.Task | None = None
        self._health_check_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Restart tracking
        self._restart_times: list[float] = []
        self._current_backoff = supervision_config.initial_backoff_seconds

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_running(self) -> bool:
        return self.state == BackendState.RUNNING and self.backend is not None

    async def start(self) -> bool:
        """Start the supervised backend."""
        if self.state in (BackendState.STARTING, BackendState.RUNNING):
            logger.warning(f"Backend {self.name} is already starting/running")
            return True

        self._stop_event.clear()
        self.state = BackendState.STARTING

        try:
            # Create and connect backend with proper timeout configuration
            from .backends import DEFAULT_CONNECTION_TIMEOUT, DEFAULT_REQUEST_TIMEOUT

            self.backend = BackendConnection(
                self.config,
                connection_timeout=DEFAULT_CONNECTION_TIMEOUT,
                request_timeout=DEFAULT_REQUEST_TIMEOUT,
            )
            await self.backend.connect()

            # Update state
            self.state = BackendState.RUNNING
            self.stats.start_count += 1
            self.stats.last_start_time = asyncio.get_event_loop().time()
            self.stats.consecutive_crashes = 0
            self._current_backoff = self.supervision_config.initial_backoff_seconds

            # Start health checks
            self._health_check_task = asyncio.create_task(self._health_check_loop())

            logger.info(f"Backend {self.name} started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start backend {self.name}: {e}")
            await self._handle_crash(e)
            return False

    async def stop(self) -> None:
        """Stop the supervised backend."""
        logger.info(f"Stopping supervised backend {self.name}")

        self._stop_event.set()
        self.state = BackendState.STOPPED

        # Cancel tasks
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
            try:
                await self._restart_task
            except asyncio.CancelledError:
                pass

        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Disconnect backend
        if self.backend:
            try:
                await self.backend.disconnect()
            except asyncio.CancelledError:
                # Don't propagate cancellation
                logger.debug(f"Backend {self.name} disconnect cancelled during stop")
            except Exception as e:
                logger.warning(f"Error disconnecting backend {self.name}: {e}")
            self.backend = None

        logger.info(f"Backend {self.name} stopped")

    async def restart(self) -> bool:
        """Restart the backend."""
        logger.info(f"Restarting backend {self.name}")
        await self.stop()
        await asyncio.sleep(0.5)  # Brief pause before restart
        return await self.start()

    async def restart_with_config(self, new_config: ServerConfig) -> bool:
        """Restart the backend with a new configuration.

        Args:
            new_config: New configuration to use

        Returns:
            True if restart succeeded
        """
        logger.info(f"Restarting backend {self.name} with new config")

        # Update config
        self.config = new_config

        # Stop current instance
        await self.stop()
        await asyncio.sleep(0.5)

        # Start with new config
        return await self.start()

    async def _health_check_loop(self) -> None:
        """Periodic health check for the backend."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.supervision_config.health_check_interval,
                )
            except TimeoutError:
                # Time to check health
                if self.backend and not self.backend.is_connected:
                    logger.warning(f"Backend {self.name} lost connection")
                    await self._handle_crash(ConnectionError("Connection lost"))

    async def _handle_crash(self, error: Exception) -> None:
        """Handle a backend crash."""
        logger.error(f"Backend {self.name} crashed: {error}")

        # Update stats
        self.stats.crash_count += 1
        self.stats.last_crash_time = asyncio.get_event_loop().time()
        self.stats.consecutive_crashes += 1
        self.state = BackendState.CRASHED

        # Update uptime tracking
        if self.stats.last_start_time:
            uptime = self.stats.last_crash_time - self.stats.last_start_time
            self.stats.total_uptime_seconds += uptime

        # Disconnect
        if self.backend:
            try:
                await self.backend.disconnect()
            except Exception:
                pass
            self.backend = None

        # Check if we should restart
        if not self.supervision_config.auto_restart:
            logger.info(f"Auto-restart disabled for {self.name}")
            self.state = BackendState.FAILED
            return

        # Check failure threshold
        if self.stats.consecutive_crashes >= self.supervision_config.max_consecutive_crashes:
            logger.error(
                f"Backend {self.name} exceeded max consecutive crashes "
                f"({self.supervision_config.max_consecutive_crashes}), giving up"
            )
            self.state = BackendState.FAILED
            return

        # Check restart rate
        now = asyncio.get_event_loop().time()
        window = self.supervision_config.restart_window_seconds
        self._restart_times = [t for t in self._restart_times if now - t < window]

        if len(self._restart_times) >= self.supervision_config.max_restarts:
            logger.error(
                f"Backend {self.name} exceeded max restarts "
                f"({self.supervision_config.max_restarts}) in {window}s, backing off"
            )
            self.state = BackendState.BACKING_OFF
            self._schedule_restart(backoff=self.supervision_config.max_backoff_seconds * 2)
            return

        # Schedule restart with backoff
        self._restart_times.append(now)
        self._schedule_restart()

    def _schedule_restart(self, backoff: float | None = None) -> None:
        """Schedule a restart with backoff."""
        if backoff is None:
            backoff = self._current_backoff

        # Add jitter to prevent thundering herd
        if self.supervision_config.jitter:
            backoff = backoff * (0.5 + random.random())

        logger.info(f"Scheduling restart of {self.name} in {backoff:.1f}s")
        self.state = BackendState.BACKING_OFF
        self._restart_task = asyncio.create_task(self._restart_after_delay(backoff))

        # Increase backoff for next time
        self._current_backoff = min(
            self._current_backoff * self.supervision_config.backoff_multiplier,
            self.supervision_config.max_backoff_seconds,
        )

    async def _restart_after_delay(self, delay: float) -> None:
        """Wait and then restart."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            # Stop event was set, cancel restart
            logger.debug(f"Restart of {self.name} cancelled (stop requested)")
        except TimeoutError:
            # Time to restart
            if not self._stop_event.is_set():
                await self.start()


class ProcessSupervisor:
    """Supervises multiple backend processes."""

    def __init__(
        self,
        backend_manager: BackendManager,
        supervision_config: SupervisionConfig | None = None,
    ):
        self.backend_manager = backend_manager
        self.supervision_config = supervision_config or SupervisionConfig()

        self._supervised: dict[str, SupervisedBackend] = {}
        self._running = False

    async def start_supervision(self, configs: dict[str, ServerConfig]) -> None:
        """Start supervising all configured backends."""
        self._running = True

        logger.info(f"Starting process supervision for {len(configs)} backend(s)")

        for name, config in configs.items():
            supervised = SupervisedBackend(config, self.supervision_config)
            self._supervised[name] = supervised

            # Start the backend
            success = await supervised.start()
            if success:
                logger.info(f"Supervised backend {name} started")
            else:
                logger.warning(f"Supervised backend {name} failed to start, will retry")

        # Update backend manager with supervised backends
        self._sync_to_backend_manager()

    async def stop_supervision(self) -> None:
        """Stop all supervised backends."""
        self._running = False

        if not self._supervised:
            return

        logger.info(f"Stopping {len(self._supervised)} supervised backend(s)")

        try:
            await asyncio.gather(
                *[sb.stop() for sb in self._supervised.values()],
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            # Ignore cancellation during shutdown
            pass

        self._supervised.clear()

    async def restart_backend(self, name: str, new_config: ServerConfig | None = None) -> bool:
        """Manually restart a specific backend.

        Args:
            name: Name of the backend to restart
            new_config: Optional new configuration. If None, restarts with current config.
        """
        if name not in self._supervised:
            logger.error(f"Unknown backend: {name}")
            return False

        supervised = self._supervised[name]
        if new_config is not None:
            return await supervised.restart_with_config(new_config)
        return await supervised.restart()

    def get_stats(self) -> dict[str, dict]:
        """Get supervision statistics for all backends."""
        return {
            name: {
                "state": sb.state.value,
                "starts": sb.stats.start_count,
                "crashes": sb.stats.crash_count,
                "consecutive_crashes": sb.stats.consecutive_crashes,
                "uptime_seconds": sb.stats.total_uptime_seconds,
                "is_running": sb.is_running,
            }
            for name, sb in self._supervised.items()
        }

    def _sync_to_backend_manager(self) -> None:
        """Sync supervised backends to backend manager."""
        # Replace backend manager's backends with supervised ones
        for name, supervised in self._supervised.items():
            if supervised.backend:
                self.backend_manager._backends[name] = supervised.backend


async def supervise_backends(
    backend_manager: BackendManager,
    configs: dict[str, ServerConfig],
    supervision_config: SupervisionConfig | None = None,
) -> ProcessSupervisor:
    """Convenience function to start supervision.

    Usage:
        supervisor = await supervise_backends(backend_manager, configs)
        # ... run gateway ...
        await supervisor.stop_supervision()
    """
    supervisor = ProcessSupervisor(backend_manager, supervision_config)
    await supervisor.start_supervision(configs)
    return supervisor
