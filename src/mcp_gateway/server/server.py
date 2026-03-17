"""MCP Gateway Server - Main server class."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI

from .http_routes import setup_http_routes
from .mcp_handlers import MCPHandlers, setup_mcp_handlers
from .middleware import setup_middleware
from .state import ServerDependencies

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger(__name__)


class McpGatewayServer:
    """MCP Gateway server with FastAPI frontend and FastMCP protocol.

    This class expects all dependencies to be injected via ServerDependencies.
    Use create_dependencies() in main.py to build the dependency container.
    """

    def __init__(
        self,
        dependencies: ServerDependencies,
    ):
        """Initialize the gateway server with injected dependencies.

        Args:
            dependencies: Container with all server dependencies pre-initialized.
        """
        self.deps = dependencies

        # MCP handlers
        self.mcp_handlers: MCPHandlers | None = None

        # FastAPI app (created on start)
        self.app: FastAPI | None = None

        # Background task tracking
        self._background_tasks: set[asyncio.Task] = set()

    def create_app(self, enable_access_control: bool = False) -> FastAPI:
        """Create and configure the FastAPI application."""
        self.app = FastAPI(
            title="MCP Gateway",
            description="Aggregates multiple MCP servers into a single endpoint",
            version="1.0.0",
            lifespan=self._lifespan,
        )

        # Setup middleware
        setup_middleware(self.app, self.deps)

        # Setup HTTP routes
        setup_http_routes(self.app, self.deps, enable_access_control)

        # Setup MCP protocol handlers
        self.mcp_handlers = setup_mcp_handlers(self.app, self.deps)

        # Store mcp_handlers in deps for runtime access (e.g., adding new servers)
        self.deps.mcp_handlers = self.mcp_handlers

        return self.app

    @property
    def config(self):
        """Get gateway config from dependencies."""
        return self.deps.config

    @property
    def backend_manager(self):
        """Get backend manager from dependencies."""
        return self.deps.backend_manager

    @property
    def config_manager(self):
        """Get config manager from dependencies."""
        return self.deps.config_manager

    @property
    def supervisor(self):
        """Get supervisor from dependencies."""
        return self.deps.supervisor

    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """Application lifespan context manager."""
        logger.info("Starting MCP Gateway server...")

        # Initialize rate limiter
        self.deps.rate_limiter = self.deps.rate_limiter or None
        if self.deps.rate_limiter:
            logger.info("Rate limiter initialized")

        # Note: Process supervisor is already started in main.py
        # The supervisor lifecycle is managed by create_dependencies()
        if self.deps.supervisor:
            logger.info("Process supervisor already initialized")

        # Start audit service if enabled
        if self.deps.audit_service:
            await self.deps.audit_service.start()
            logger.info("Audit service started")

        # Initial tool sync before starting MCP session manager
        if self.mcp_handlers:
            self.mcp_handlers.sync_tools()

        # Start MCP session manager
        if self.mcp_handlers:
            async with self.mcp_handlers.lifespan():
                logger.info("MCP Gateway server started successfully")
                yield
        else:
            logger.info("MCP Gateway server started (without MCP handlers)")
            yield

        # Shutdown
        logger.info("Shutting down MCP Gateway server...")

        # Stop audit service
        if self.deps.audit_service:
            await self.deps.audit_service.stop()

        # Stop rate limiter
        if self.deps.rate_limiter:
            await self.deps.rate_limiter.stop()

        # Cancel background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        # Note: Process supervisor is stopped in main.py
        # The supervisor lifecycle is managed by create_dependencies()

        logger.info("MCP Gateway server shutdown complete")

    def sync_tools(self) -> None:
        """Synchronize tools from backends to MCP server."""
        if self.mcp_handlers:
            self.mcp_handlers.sync_tools()

    def _run_background_task(self, coro: asyncio.Coroutine, name: str) -> None:
        """Run a background task and track it for cleanup."""
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def start(self, host: str = "0.0.0.0", port: int = 3000) -> None:
        """Start the server (for programmatic use)."""
        import uvicorn

        if self.app is None:
            self.create_app()

        config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
