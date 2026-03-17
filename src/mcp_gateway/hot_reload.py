"""Hot reload functionality for configuration changes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import watchdog for efficient file watching
try:
    from watchdog.events import FileModifiedEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileModifiedEvent = None


@dataclass
class ConfigChange:
    """Represents a configuration change."""

    action: str  # 'added', 'removed', 'modified'
    server_name: str
    old_config: dict[str, Any] | None = None
    new_config: dict[str, Any] | None = None


class ConfigFileHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Handler for config file change events."""

    def __init__(self, callback: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self.callback = callback
        self._last_modified: float = 0
        self._debounce_seconds: float = 1.0

    def on_modified(self, event: FileModifiedEvent | None) -> None:
        """Called when config file is modified."""
        if event is None or event.is_directory:
            return

        # Debounce rapid changes using time.time() (not asyncio)
        import time

        current_time = time.time()
        if current_time - self._last_modified < self._debounce_seconds:
            return

        self._last_modified = current_time
        logger.info(f"Config file modified: {event.src_path}")

        # Schedule callback - don't use asyncio from sync method
        # The callback will be called directly, debounce handled by time check
        if self.callback:
            try:
                # Try to get running loop and schedule
                loop = asyncio.get_running_loop()
                loop.call_later(self._debounce_seconds, self._schedule_callback)
            except RuntimeError:
                # No running loop, just call directly
                pass

    def _schedule_callback(self) -> None:
        """Schedule the async callback safely."""
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._invoke_callback())
        except RuntimeError:
            logger.warning("No event loop running, cannot schedule callback")

    async def _invoke_callback(self) -> None:
        """Invoke callback with debounce."""
        await asyncio.sleep(self._debounce_seconds)
        if self.callback:
            await self.callback()


class ConfigWatcher:
    """Watches configuration file for changes and triggers reloads."""

    def __init__(
        self,
        config_path: str | Path,
        reload_callback: Callable[[], Awaitable[None]],
        use_polling: bool = False,
        poll_interval: float = 5.0,
    ) -> None:
        self.config_path = Path(config_path)
        self.reload_callback = reload_callback
        self.use_polling = use_polling or not WATCHDOG_AVAILABLE
        self.poll_interval = poll_interval

        self._observer: Any | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._last_mtime: float = 0
        self._running = False

        # Store last known config for diffing
        self._last_config: dict[str, Any] = {}

        # Flag to temporarily disable reloads (when server saves config)
        self._reload_disabled = False
        self._last_save_time: float = 0
        self._save_grace_period: float = 2.0  # Ignore changes for 2s after save

    def disable_reload_temporarily(self) -> None:
        """Disable reloads temporarily (call before saving config)."""
        import time

        self._reload_disabled = True
        self._last_save_time = time.time()

    def enable_reload(self) -> None:
        """Re-enable reloads (call after saving config)."""
        self._reload_disabled = False

    def _is_reload_disabled(self) -> bool:
        """Check if reloads should be disabled."""
        import time

        if not self._reload_disabled:
            return False
        # Auto-enable after grace period
        if time.time() - self._last_save_time > self._save_grace_period:
            self._reload_disabled = False
            return False
        return True

    async def start(self) -> None:
        """Start watching for config changes."""
        if self._running:
            return

        self._running = True

        # Load initial config
        await self._load_initial_config()

        if self.use_polling:
            logger.info(f"Starting config polling (interval: {self.poll_interval}s)")
            self._polling_task = asyncio.create_task(self._poll_loop())
        else:
            logger.info("Starting config file watcher (watchdog)")
            self._start_watchdog()

    async def stop(self) -> None:
        """Stop watching for config changes."""
        self._running = False

        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None

        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

        logger.info("Config watcher stopped")

    async def _load_initial_config(self) -> None:
        """Load initial configuration."""
        try:
            if self.config_path.exists():
                # Use asyncio.to_thread for non-blocking file I/O
                import aiofiles

                async with aiofiles.open(self.config_path, encoding="utf-8") as f:
                    content = await f.read()
                    self._last_config = json.loads(content)
                self._last_mtime = self.config_path.stat().st_mtime
        except Exception as e:
            logger.warning(f"Could not load initial config: {e}")

    def _start_watchdog(self) -> None:
        """Start filesystem watchdog."""
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available, falling back to polling")
            self.use_polling = True
            return

        handler = ConfigFileHandler(self._on_config_changed)
        self._observer = Observer()
        self._observer.schedule(
            handler,
            str(self.config_path.parent),
            recursive=False,
        )
        self._observer.start()

    async def _poll_loop(self) -> None:
        """Polling loop for config file changes."""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)

                if not self.config_path.exists():
                    continue

                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != self._last_mtime:
                    logger.info("Config file changed (detected by polling)")
                    self._last_mtime = current_mtime
                    await self._on_config_changed()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in config poll loop: {e}")

    async def _on_config_changed(self) -> None:
        """Handle config file change."""
        # Skip if reload is temporarily disabled (server is saving config)
        if self._is_reload_disabled():
            logger.debug("Ignoring config change (save in progress)")
            return

        try:
            # Reload config using non-blocking I/O
            import aiofiles

            async with aiofiles.open(self.config_path, encoding="utf-8") as f:
                content = await f.read()
                new_config = json.loads(content)

            # Compute changes
            changes = self._compute_changes(self._last_config, new_config)

            if changes:
                logger.info(f"Detected {len(changes)} configuration change(s)")
                for change in changes:
                    logger.info(f"  - {change.action}: {change.server_name}")

                # Update stored config
                self._last_config = new_config

                # Trigger reload
                await self.reload_callback()
            else:
                logger.debug("Config file changed but no effective changes detected")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
        except Exception as e:
            logger.error(f"Error processing config change: {e}")

    def _compute_changes(
        self,
        old_config: dict,
        new_config: dict,
    ) -> list[ConfigChange]:
        """Compute differences between old and new config."""
        changes = []

        old_servers = old_config.get("mcpServers", {})
        new_servers = new_config.get("mcpServers", {})

        # Find added servers
        for name in new_servers:
            if name not in old_servers:
                changes.append(
                    ConfigChange(
                        action="added",
                        server_name=name,
                        old_config=None,
                        new_config=new_servers[name],
                    )
                )

        # Find removed servers
        for name in old_servers:
            if name not in new_servers:
                changes.append(
                    ConfigChange(
                        action="removed",
                        server_name=name,
                        old_config=old_servers[name],
                        new_config=None,
                    )
                )

        # Find modified servers
        for name in new_servers:
            if name in old_servers:
                if self._configs_differ(old_servers[name], new_servers[name]):
                    changes.append(
                        ConfigChange(
                            action="modified",
                            server_name=name,
                            old_config=old_servers[name],
                            new_config=new_servers[name],
                        )
                    )

        return changes

    def _configs_differ(self, old: dict, new: dict) -> bool:
        """Check if two server configs are different."""
        # Compare relevant fields
        fields = [
            "command",
            "args",
            "env",
            "url",
            "type",
            "headers",
            "disabledTools",
            "disabled_tools",
        ]

        for field in fields:
            old_val = old.get(field)
            new_val = new.get(field)

            # Normalize args (list vs string)
            if field == "args":
                old_val = self._normalize_args(old_val)
                new_val = self._normalize_args(new_val)

            if old_val != new_val:
                return True

        return False

    def _normalize_args(self, args: Any) -> tuple:
        """Normalize args to comparable format."""
        if args is None:
            return ()
        if isinstance(args, str):
            import shlex

            return tuple(shlex.split(args))
        return tuple(args)


class HotReloadManager:
    """Manages hot reload of gateway configuration."""

    def __init__(
        self,
        config_path: str | Path,
        backend_manager: Any,
        config_loader: Callable[[str], dict[str, Any]],
        reconnect_callback: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.config_path = Path(config_path)
        self.backend_manager = backend_manager
        self.config_loader = config_loader
        self.reconnect_callback = reconnect_callback

        self.watcher: ConfigWatcher | None = None
        self._reload_lock = asyncio.Lock()
        self._reload_count = 0
        self._last_reload_time: float | None = None

    async def start(self, use_polling: bool = False) -> None:
        """Start hot reload monitoring."""
        self.watcher = ConfigWatcher(
            config_path=self.config_path,
            reload_callback=self._reload_config,
            use_polling=use_polling,
        )
        await self.watcher.start()
        logger.info("Hot reload manager started")

    async def stop(self) -> None:
        """Stop hot reload monitoring."""
        if self.watcher:
            await self.watcher.stop()
            self.watcher = None
        logger.info("Hot reload manager stopped")

    async def _reload_config(self) -> None:
        """Reload configuration and apply changes."""
        async with self._reload_lock:
            try:
                logger.info("Reloading configuration...")

                # Load new config
                new_config = self.config_loader(str(self.config_path))

                # Disconnect old backends
                await self.backend_manager.disconnect_all()

                # Reconnect with new config
                await self.reconnect_callback(new_config)

                self._reload_count += 1
                self._last_reload_time = asyncio.get_event_loop().time()

                logger.info(f"Configuration reloaded successfully (reload #{self._reload_count})")

            except Exception as e:
                logger.error(f"Failed to reload configuration: {e}")
                # Don't re-raise - keep running with old config

    @property
    def reload_count(self) -> int:
        return self._reload_count

    @property
    def last_reload_time(self) -> float | None:
        return self._last_reload_time
