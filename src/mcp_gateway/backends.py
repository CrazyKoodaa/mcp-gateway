"""Backend connection management for MCP servers with circuit breaker support."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, ListToolsResult, Tool

from .config import ServerConfig
from .exceptions import BackendConnectionError

if TYPE_CHECKING:
    from .circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Default timeouts for remote connections
DEFAULT_CONNECTION_TIMEOUT: float = 30.0
DEFAULT_REQUEST_TIMEOUT: float = 60.0


class ToolMapping:
    """Thread-safe tool mapping container."""

    __slots__ = ("_mapping", "_lock")

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}  # tool_name -> backend_name
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        """Get backend name for a tool."""
        async with self._lock:
            return self._mapping.get(key)

    async def update_for_backend(
        self,
        backend_name: str,
        tools: list[Tool],
        separator: str
    ) -> list[str]:
        """Update mappings for a backend atomically.

        Returns list of conflicting tool names.
        """
        conflicts: list[str] = []
        async with self._lock:
            # Remove old mappings for this backend
            self._mapping = {
                k: v for k, v in self._mapping.items()
                if v != backend_name
            }

            # Add new mappings
            for tool in tools:
                namespaced_name = f"{backend_name}{separator}{tool.name}"
                if namespaced_name in self._mapping:
                    conflicts.append(namespaced_name)
                self._mapping[namespaced_name] = backend_name

            return conflicts

    async def remove_backend(self, backend_name: str) -> None:
        """Remove all mappings for a backend."""
        async with self._lock:
            self._mapping = {
                k: v for k, v in self._mapping.items()
                if v != backend_name
            }

    async def clear(self) -> None:
        """Clear all mappings."""
        async with self._lock:
            self._mapping.clear()

    def get_snapshot(self) -> dict[str, str]:
        """Get a snapshot of current mappings (for read-only use)."""
        return self._mapping.copy()


class BackendConnection:
    """Manages connection to a single MCP backend server."""

    __slots__ = (
        "config", "session", "_exit_stack", "_tools", "_connected",
        "_connection_timeout", "_request_timeout", "_circuit_breaker"
    )

    def __init__(
        self,
        config: ServerConfig,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        circuit_breaker: CircuitBreaker | None = None
    ) -> None:
        self.config: ServerConfig = config
        self.session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[Tool] = []
        self._connected: bool = False
        self._connection_timeout: float = connection_timeout
        self._request_timeout: float = request_timeout
        self._circuit_breaker: CircuitBreaker | None = circuit_breaker

    @property
    def name(self) -> str:
        """Backend name."""
        return self.config.name

    @property
    def is_connected(self) -> bool:
        """Whether the backend is currently connected."""
        return self._connected and self.session is not None

    @property
    def tools(self) -> list[Tool]:
        """Copy of available tools."""
        return self._tools.copy()

    async def connect(self) -> None:
        """Establish connection to the backend server."""
        logger.info(
            f"Connecting to backend: {self.name} ({self.config.transport_type})"
        )

        self._exit_stack = AsyncExitStack()

        try:
            if self.config.is_stdio:
                await self._connect_stdio()
            else:
                await self._connect_remote()

            # Initialize session
            if self.session:
                await self.session.initialize()
                self._connected = True

                # List available tools
                tools_result: ListToolsResult = await self.session.list_tools()
                self._tools = self._filter_tools(tools_result.tools)

                logger.info(
                    f"Backend {self.name} connected with {len(self._tools)} tools"
                )

        except Exception as e:
            logger.error(f"Failed to connect to backend {self.name}: {e}")
            await self.disconnect()
            raise BackendConnectionError(f"Connection failed: {e}") from e

    async def _connect_stdio(self) -> None:
        """Connect to stdio-based MCP server."""
        if not self.config.command:
            raise ValueError(f"No command specified for stdio server: {self.name}")

        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env={**os.environ, **self.config.env},
        )

        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = transport

        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

    async def _connect_remote(self) -> None:
        """Connect to remote MCP server via HTTP/SSE."""
        if not self.config.url:
            raise ValueError(f"No URL specified for remote server: {self.name}")

        url: str = self.config.url
        transport_type: str = self.config.transport_type

        # Try StreamableHTTP first, then SSE
        if transport_type == "streamable-http":
            try:
                await self._connect_streamable_http(url)
            except Exception as e:
                logger.warning(f"StreamableHTTP failed for {self.name}, trying SSE: {e}")
                await self._connect_sse(url)
        elif transport_type == "sse":
            await self._connect_sse(url)
        else:
            # Try StreamableHTTP first (like llama.cpp), fallback to SSE
            try:
                await self._connect_streamable_http(url)
            except Exception as e:
                logger.warning(f"StreamableHTTP failed for {self.name}, trying SSE: {e}")
                await self._connect_sse(url)

    async def _connect_streamable_http(self, url: str) -> None:
        """Connect via StreamableHTTP transport."""
        logger.debug(f"Connecting via StreamableHTTP to {url}")

        transport = await self._exit_stack.enter_async_context(
            streamablehttp_client(
                url=url,
                headers=self.config.headers,
            )
        )
        read_stream, write_stream = transport

        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        logger.debug(f"StreamableHTTP connection established to {url}")

    async def _connect_sse(self, url: str) -> None:
        """Connect via SSE transport."""
        logger.debug(f"Connecting via SSE to {url}")

        transport = await self._exit_stack.enter_async_context(
            sse_client(
                url=url,
                headers=self.config.headers,
            )
        )
        read_stream, write_stream = transport

        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        logger.debug(f"SSE connection established to {url}")

    def _filter_tools(self, tools: list[Tool]) -> list[Tool]:
        """Filter out disabled tools."""
        if not self.config.disabled_tools:
            return tools

        disabled: set[str] = set(self.config.disabled_tools)
        filtered: list[Tool] = [t for t in tools if t.name not in disabled]

        removed: int = len(tools) - len(filtered)
        if removed > 0:
            logger.info(f"Filtered {removed} disabled tools for {self.name}")

        return filtered

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, object]
    ) -> CallToolResult:
        """Call a tool on this backend."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Backend {self.name} is not connected")

        return await self.session.call_tool(tool_name, arguments=arguments)

    async def disconnect(self) -> None:
        """Close connection to backend."""
        logger.info(f"Disconnecting from backend: {self.name}")

        self._connected = False
        self._tools = []

        if self._exit_stack:
            # Suppress all stderr output during disconnect to prevent
            # "RuntimeError: Attempted to exit cancel scope in a different task"
            # and other async generator errors from polluting the console.
            # These errors are harmless during shutdown.
            import sys
            from io import StringIO

            old_stderr = sys.stderr
            old_stdout = sys.stdout

            try:
                # Redirect both stdout and stderr to a dummy buffer
                dummy = StringIO()
                sys.stderr = dummy
                sys.stdout = dummy

                # Close the exit stack with comprehensive error suppression
                try:
                    await self._exit_stack.aclose()
                except asyncio.CancelledError:
                    # Don't re-raise - we're shutting down anyway
                    logger.debug(f"Backend {self.name} disconnect cancelled")
                except (Exception, RuntimeError, BaseException):
                    # Suppress ALL other errors during shutdown
                    pass

            finally:
                # Always restore stdout/stderr
                sys.stderr = old_stderr
                sys.stdout = old_stdout
                self._exit_stack = None

        self.session = None

    async def restart(self, new_config: ServerConfig | None = None) -> None:
        """Restart the backend with optionally new configuration.

        Args:
            new_config: Optional new configuration. If None, uses current config.
        """
        logger.info(f"Restarting backend: {self.name}")

        # Update config if provided
        if new_config is not None:
            old_args: list[str] = self.config.args
            self.config = new_config
            logger.info(
                f"Backend {self.name} config updated: {old_args} -> {new_config.args}"
            )

        # Disconnect
        await self.disconnect()

        # Brief pause to ensure process termination
        await asyncio.sleep(0.5)

        # Reconnect with (possibly) new config
        try:
            await self.connect()
            logger.info(f"Backend {self.name} restarted successfully")
        except Exception as e:
            logger.error(f"Failed to restart backend {self.name}: {e}")
            raise


class BackendManager:
    """Manages connections to all backend MCP servers with thread-safe operations."""

    __slots__ = (
        "_backends", "_tool_map", "_namespace_separator",
        "_connection_timeout", "_request_timeout", "_lock"
    )

    def __init__(
        self,
        namespace_separator: str = "__",
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    ) -> None:
        self._backends: dict[str, BackendConnection] = {}
        self._tool_map: dict[str, str] = {}  # tool_name -> backend_name
        self._namespace_separator: str = namespace_separator
        self._connection_timeout: float = connection_timeout
        self._request_timeout: float = request_timeout
        self._lock: asyncio.Lock = asyncio.Lock()

    async def add_backend(self, config: ServerConfig) -> BackendConnection:
        """Add and connect a new backend (thread-safe)."""
        backend = BackendConnection(
            config,
            self._connection_timeout,
            self._request_timeout
        )
        await backend.connect()

        async with self._lock:
            self._backends[config.name] = backend

            # Update tool mapping
            for tool in backend.tools:
                namespaced_name = f"{config.name}{self._namespace_separator}{tool.name}"
                if namespaced_name in self._tool_map:
                    logger.warning(f"Tool name conflict: {namespaced_name}")
                self._tool_map[namespaced_name] = config.name

        return backend

    async def connect_all(self, configs: dict[str, ServerConfig]) -> None:
        """Connect to all configured backends."""
        logger.info(f"Connecting to {len(configs)} backend(s)...")

        results: list[BackendConnection | Exception] = await asyncio.gather(
            *[self._try_connect(name, cfg) for name, cfg in configs.items()],
            return_exceptions=True,
        )

        connected: int = 0
        for name, result in zip(configs.keys(), results, strict=True):
            if isinstance(result, Exception):
                logger.error(f"Failed to connect to {name}: {result}")
            else:
                connected += 1

        logger.info(f"Connected to {connected}/{len(configs)} backend(s)")

    async def _try_connect(self, name: str, config: ServerConfig) -> BackendConnection:
        """Try to connect to a backend, logging errors."""
        try:
            return await self.add_backend(config)
        except Exception as e:
            logger.error(f"Backend {name} connection failed: {e}")
            raise

    async def disconnect_all(self) -> None:
        """Disconnect from all backends."""
        if not self._backends:
            return

        logger.info(f"Disconnecting from {len(self._backends)} backend(s)...")

        # Create a copy of backends to avoid modification during iteration
        backends_to_disconnect = list(self._backends.values())

        try:
            # Use wait_for to prevent hanging during shutdown
            await asyncio.wait_for(
                asyncio.gather(
                    *[backend.disconnect() for backend in backends_to_disconnect],
                    return_exceptions=True,
                ),
                timeout=5.0
            )
        except TimeoutError:
            logger.warning("Backend disconnect timed out, forcing exit")
        except asyncio.CancelledError:
            logger.debug("Backend disconnect cancelled during shutdown")
            # Don't re-raise - just log and continue with cleanup
        except Exception as e:
            logger.debug(f"Backend disconnect error: {e}")

        # Clear backends dict and tool mappings
        async with self._lock:
            self._backends.clear()
            self._tool_map.clear()

    def get_all_tools(self) -> list[Tool]:
        """Get all tools from all backends with namespacing."""
        all_tools: list[Tool] = []

        for backend in self._backends.values():
            for tool in backend.tools:
                # Create namespaced copy of tool
                namespaced_tool = Tool(
                    name=f"{backend.name}__{tool.name}",
                    description=f"[{backend.name}] {tool.description or ''}",
                    inputSchema=tool.inputSchema,
                )
                all_tools.append(namespaced_tool)

        return all_tools

    def get_backend_for_tool(
        self,
        tool_name: str
    ) -> BackendConnection | None:
        """Get the backend that handles a given tool."""
        # Tool name should already be namespaced: "backend__tool"
        if self._namespace_separator not in tool_name:
            return None

        backend_name: str | None = self._tool_map.get(tool_name)
        if not backend_name:
            return None

        return self._backends.get(backend_name)

    def extract_original_tool_name(self, namespaced_name: str) -> tuple[str, str]:
        """Extract backend name and original tool name from namespaced name."""
        if self._namespace_separator not in namespaced_name:
            return "", namespaced_name

        parts: list[str] = namespaced_name.split(self._namespace_separator, 1)
        return parts[0], parts[1]

    @property
    def backends(self) -> dict[str, BackendConnection]:
        """Copy of backends dictionary."""
        return self._backends.copy()

    async def restart_backend(
        self,
        name: str,
        new_config: ServerConfig | None = None
    ) -> BackendConnection:
        """Restart a specific backend with optionally new configuration (thread-safe).

        This method is atomic - the tool map is only updated after successful restart.

        Args:
            name: Name of the backend to restart
            new_config: Optional new configuration. If None, restarts with current config.

        Returns:
            The restarted backend connection

        Raises:
            KeyError: If backend not found
            BackendConnectionError: If restart fails
        """
        async with self._lock:
            backend: BackendConnection | None = self._backends.get(name)
            if not backend:
                raise KeyError(f"Backend '{name}' not found")

            logger.info(f"BackendManager restarting backend: {name}")

        # Perform restart outside the lock to avoid holding it during I/O
        try:
            await backend.restart(new_config)
        except Exception as e:
            logger.error(f"Backend {name} restart failed: {e}")
            raise BackendConnectionError(f"Restart failed: {e}") from e

        # Update tool mappings atomically with new tools
        async with self._lock:
            # Remove old tool mappings for this backend
            tools_to_remove = [
                tool_name for tool_name, backend_name in self._tool_map.items()
                if backend_name == name
            ]
            for tool_name in tools_to_remove:
                del self._tool_map[tool_name]

            # Add new tool mappings
            for tool in backend.tools:
                namespaced_name = f"{name}{self._namespace_separator}{tool.name}"
                if namespaced_name in self._tool_map:
                    logger.warning(f"Tool name conflict on restart: {namespaced_name}")
                self._tool_map[namespaced_name] = name

        logger.info(f"Backend {name} restarted with {len(backend.tools)} tools")
        return backend
