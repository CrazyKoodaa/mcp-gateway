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


class BackendConnection:
    """Manages connection to a single MCP backend server."""

    __slots__ = (
        "config",
        "session",
        "_exit_stack",
        "_tools",
        "_connected",
        "_connection_timeout",
        "_request_timeout",
        "_circuit_breaker",
        "_last_error",
        "_diagnostic_tip",
        "_connection_attempts",
        "_last_connection_attempt",
    )

    def __init__(
        self,
        config: ServerConfig,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.config: ServerConfig = config
        self.session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[Tool] = []
        self._connected: bool = False
        self._connection_timeout: float = connection_timeout
        self._request_timeout: float = request_timeout
        self._circuit_breaker: CircuitBreaker | None = circuit_breaker

        # Diagnostic tracking
        self._last_error: str | None = None
        self._diagnostic_tip: str | None = None
        self._connection_attempts: int = 0
        self._last_connection_attempt: float | None = None

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

    @property
    def last_error(self) -> str | None:
        """Last connection error message."""
        return self._last_error

    @property
    def diagnostic_tip(self) -> str | None:
        """Diagnostic tip for fixing connection issues."""
        return self._diagnostic_tip

    @property
    def connection_attempts(self) -> int:
        """Number of connection attempts made."""
        return self._connection_attempts

    @property
    def last_connection_attempt(self) -> float | None:
        """Timestamp of last connection attempt."""
        return self._last_connection_attempt

    def _generate_diagnostic_tip(self, error: Exception) -> str:
        """Generate a helpful diagnostic tip based on the error."""
        error_msg = str(error).lower()
        backend_name = self.name.lower()

        # Configuration errors
        if "not set" in error_msg or "missing" in error_msg:
            if "searxng" in backend_name or "url" in error_msg:
                return "Add SEARXNG_URL environment variable in server configuration"
            return "Check required environment variables in server configuration"

        # Path/Filesystem errors
        if "does not exist" in error_msg or "enoent" in error_msg or "no such file" in error_msg:
            if "filesystem" in backend_name or "directory" in error_msg:
                return "Update allowed directories in server arguments"
            return "Check that paths exist and are accessible"

        # Connection errors
        if "connection refused" in error_msg:
            return "Verify the backend service is running and accessible"
        if "timeout" in error_msg:
            return "Check network connectivity and firewall settings"

        # Permission errors
        if "permission" in error_msg or "access denied" in error_msg:
            return "Verify file/directory permissions or use absolute paths"

        # Package/Command errors
        if "command not found" in error_msg or "enoent" in error_msg:
            return "Ensure the command is installed and in PATH"

        # Default tip
        return "Check server logs for detailed error information"

    async def connect(self) -> None:
        """Establish connection to the backend server."""
        import time

        logger.info(
            f"[CONNECTION] Initiating connection to backend: {self.name} "
            f"(transport: {self.config.transport_type})"
        )

        # Track connection attempt
        self._connection_attempts += 1
        self._last_connection_attempt = time.time()

        # Clear previous error on new attempt
        self._last_error = None
        self._diagnostic_tip = None

        self._exit_stack = AsyncExitStack()

        try:
            logger.debug(f"[CONNECTION] Starting transport-specific connection for {self.name}")
            if self.config.is_stdio:
                await self._connect_stdio()
                logger.info(f"[CONNECTION] Stdio transport established for {self.name}")
            else:
                await self._connect_remote()
                logger.info(f"[CONNECTION] Remote transport established for {self.name}")

            # Initialize session
            if self.session:
                logger.debug(f"[CONNECTION] Initializing MCP session for {self.name}")
                await self.session.initialize()
                self._connected = True
                logger.debug(f"[CONNECTION] MCP session initialized for {self.name}")

                # List available tools
                tools_result: ListToolsResult = await self.session.list_tools()
                self._tools = self._filter_tools(tools_result.tools)

                logger.info(
                    f"[CONNECTION] Backend {self.name} connected successfully with "
                    f"{len(self._tools)} tools available"
                )
                logger.debug(f"[CONNECTION] Tools: {[tool.name for tool in self._tools]}")

                # Clear any previous error on successful connection
                self._last_error = None
                self._diagnostic_tip = None

        except Exception as e:
            # Store error details for diagnostics
            self._last_error = f"{type(e).__name__}: {e}"
            self._diagnostic_tip = self._generate_diagnostic_tip(e)

            logger.error(
                f"[CONNECTION] Failed to connect to backend {self.name}: {self._last_error}",
                exc_info=True,
            )
            logger.info(f"[DIAGNOSTIC] Backend '{self.name}': {self._diagnostic_tip}")

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

        transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
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

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> CallToolResult:
        """Call a tool on this backend."""
        if not self.session or not self._connected:
            raise RuntimeError(f"Backend {self.name} is not connected")

        return await self.session.call_tool(tool_name, arguments=arguments)

    async def disconnect(self) -> None:
        """Close connection to backend."""
        logger.info(f"[DISCONNECT] Initiating disconnection from backend: {self.name}")

        self._connected = False
        self._tools = []

        if self._exit_stack:
            try:
                logger.debug(f"[DISCONNECT] Closing exit stack for {self.name}")
                await self._exit_stack.aclose()
                logger.info(f"[DISCONNECT] Exit stack closed successfully for {self.name}")
            except asyncio.CancelledError:
                # Don't re-raise - we're shutting down anyway
                logger.debug(f"[DISCONNECT] Backend {self.name} disconnect cancelled")
            except Exception as e:
                # Log the error but don't propagate - we're shutting down anyway
                logger.warning(
                    f"[DISCONNECT] Error closing exit stack for {self.name}: "
                    f"{type(e).__name__}: {e}"
                )

        self._exit_stack = None
        self.session = None
        logger.info(f"[DISCONNECT] Backend {self.name} disconnection complete")

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
            logger.info(f"Backend {self.name} config updated: {old_args} -> {new_config.args}")

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
        "_backends",
        "_tool_map",
        "_namespace_separator",
        "_connection_timeout",
        "_request_timeout",
        "_lock",
    )

    def __init__(
        self,
        namespace_separator: str = "__",
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self._backends: dict[str, BackendConnection] = {}
        self._tool_map: dict[str, str] = {}  # tool_name -> backend_name
        self._namespace_separator: str = namespace_separator
        self._connection_timeout: float = connection_timeout
        self._request_timeout: float = request_timeout
        self._lock: asyncio.Lock = asyncio.Lock()

    async def add_backend(self, config: ServerConfig) -> BackendConnection:
        """Add and connect a new backend (thread-safe)."""
        backend = BackendConnection(config, self._connection_timeout, self._request_timeout)
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
        """Connect to all configured backends.

        Stores all backends (even failed ones) so diagnostics can be retrieved.
        """
        logger.info(f"Connecting to {len(configs)} backend(s)...")

        results: list[BackendConnection | Exception] = await asyncio.gather(
            *[self._try_connect(name, cfg) for name, cfg in configs.items()],
            return_exceptions=True,
        )

        connected: int = 0
        failed: int = 0

        for name, result in zip(configs.keys(), results, strict=True):
            if isinstance(result, Exception):
                logger.error(f"Failed to connect to {name}: {result}")
                failed += 1
            else:
                connected += 1

        logger.info(f"Connected to {connected}/{len(configs)} backend(s), {failed} failed")

        if failed > 0:
            logger.info(
                "Some backends failed to connect. Use admin dashboard or /health "
                "endpoint to view diagnostics."
            )

    async def _try_connect(self, name: str, config: ServerConfig) -> BackendConnection:
        """Try to connect to a backend, logging errors.

        If connection fails, the backend is still stored with error information
        for diagnostic purposes.
        """
        backend = BackendConnection(config, self._connection_timeout, self._request_timeout)

        try:
            await backend.connect()

            async with self._lock:
                self._backends[name] = backend

                # Update tool mapping
                for tool in backend.tools:
                    namespaced_name = f"{config.name}{self._namespace_separator}{tool.name}"
                    if namespaced_name in self._tool_map:
                        logger.warning(f"Tool name conflict: {namespaced_name}")
                    self._tool_map[namespaced_name] = config.name

            return backend

        except Exception as e:
            logger.error(f"Backend {name} connection failed: {e}")

            # Store the backend even if connection failed (for diagnostics)
            async with self._lock:
                self._backends[name] = backend

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
                timeout=5.0,
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
                    name=f"{backend.name}{self._namespace_separator}{tool.name}",
                    description=f"[{backend.name}] {tool.description or ''}",
                    inputSchema=tool.inputSchema,
                )
                all_tools.append(namespaced_tool)

        return all_tools

    def get_backend_for_tool(self, tool_name: str) -> BackendConnection | None:
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

    def get_backend_diagnostics(self) -> list[dict[str, object]]:
        """Get diagnostic information for all backends.

        Returns:
            List of backend diagnostic information including connection status,
            error messages, and fix tips.
        """
        diagnostics = []

        # Include all backends (connected and failed)
        for name, backend in self._backends.items():
            diag = {
                "name": name,
                "connected": backend.is_connected,
                "status": "connected" if backend.is_connected else "error",
                "tools": len(backend.tools),
                "connection_attempts": backend.connection_attempts,
                "diagnostic": None,
            }

            if not backend.is_connected and backend.last_error:
                diag["diagnostic"] = {
                    "error_message": backend.last_error,
                    "fix_tip": backend.diagnostic_tip,
                    "last_attempt": backend.last_connection_attempt,
                }

            diagnostics.append(diag)

        return diagnostics

    async def restart_backend(
        self, name: str, new_config: ServerConfig | None = None
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
                tool_name
                for tool_name, backend_name in self._tool_map.items()
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
