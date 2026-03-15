"""MCP protocol handlers for MCP Gateway server."""
from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from .state import ServerDependencies


logger = logging.getLogger(__name__)


class MCPHandlers:
    """MCP protocol handler setup and tool synchronization."""

    def __init__(self, deps: ServerDependencies) -> None:
        """Initialize MCP handlers."""
        self.deps = deps
        self.mcp_server: FastMCP | None = None

    def setup_routes(self, app: FastAPI) -> None:
        """Setup MCP protocol routes using FastMCP.

        This mounts proper spec-compliant MCP protocol endpoints.
        The session_manager must be run as a lifespan context (handled in main.py).
        """
        from mcp.server.fastmcp import FastMCP

        # Create FastMCP instance for protocol handling
        # Use stateless_http and json_response for better scalability
        self.mcp_server = FastMCP(
            name="mcp-gateway",
            stateless_http=True,
            json_response=True,
        )

        # Mount SSE and StreamableHTTP endpoints
        # FastMCP provides Starlette apps that can be mounted in FastAPI
        try:
            # Configure paths to mount at root (we handle the path prefix)
            self.mcp_server.settings.streamable_http_path = "/"

            # These calls create the session_manager internally
            sse_app = self.mcp_server.sse_app(mount_path="/")
            streamable_app = self.mcp_server.streamable_http_app()

            app.mount("/sse", sse_app, name="mcp_sse")
            app.mount("/mcp", streamable_app, name="mcp_streamable_http")

            logger.info("MCP protocol endpoints mounted: /sse, /mcp")
        except Exception as e:
            logger.error(f"Failed to mount MCP protocol endpoints: {e}")
            self.mcp_server = None

    def sync_tools(self) -> None:
        """Synchronize tools from all backends to the MCP server.

        This registers all tools with the FastMCP instance so they're
        available via the MCP protocol endpoints.
        """
        if self.mcp_server is None:
            logger.warning("Cannot sync tools - MCP server not initialized")
            return

        # Remove existing tools using correct internal attribute
        try:
            tool_names = list(self.mcp_server._tool_manager._tools.keys())
            for tool_name in tool_names:
                try:
                    self.mcp_server._tool_manager.remove_tool(tool_name)
                except Exception as e:
                    logger.debug(f"Failed to remove tool {tool_name}: {e}")
        except Exception as e:
            logger.debug(f"No existing tools to remove: {e}")

        # Register tools from all backends
        tools_added = 0
        for backend in self.deps.backend_manager.backends.values():
            for tool in backend.tools:
                sep = self.deps.backend_manager._namespace_separator
                namespaced_name = f"{backend.name}{sep}{tool.name}"

                # Create a wrapper that routes to the correct backend
                # Use default arguments to avoid closure issues
                def make_wrapper(b=backend, t=tool.name):
                    async def wrapper(**kwargs):
                        return await b.call_tool(t, kwargs)

                    return wrapper

                try:
                    self.mcp_server._tool_manager.add_tool(
                        make_wrapper(),
                        name=namespaced_name,
                        description=f"[{backend.name}] {tool.description or ''}",
                    )

                    # Preserve the original tool's input schema
                    mcp_tool = self.mcp_server._tool_manager._tools.get(namespaced_name)
                    if mcp_tool:
                        if tool.inputSchema:
                            mcp_tool.parameters = tool.inputSchema

                            # Also update the lowlevel server's tool cache
                            if (
                                hasattr(self.mcp_server, "_mcp_server")
                                and hasattr(self.mcp_server._mcp_server, "_tool_cache")
                            ):
                                from mcp.types import Tool as MCPTool

                                self.mcp_server._mcp_server._tool_cache[
                                    namespaced_name
                                ] = MCPTool(
                                    name=mcp_tool.name,
                                    description=mcp_tool.description,
                                    inputSchema=mcp_tool.parameters,
                                )

                            logger.debug(f"Updated schema for {namespaced_name}")
                        else:
                            logger.debug(f"No inputSchema for tool {namespaced_name}")

                        # Replace the fn_metadata.arg_model to accept any arguments
                        # This bypasses validation since the backend will validate
                        try:
                            from mcp.server.fastmcp.utilities.func_metadata import (
                                ArgModelBase,
                                FuncMetadata,
                            )
                            from pydantic import ConfigDict

                            # Create a model that accepts any extra fields
                            class FlexibleArgModel(ArgModelBase):
                                """A model that accepts any arguments and dumps them correctly."""

                                model_config = ConfigDict(extra="allow")

                                def model_dump_one_level(self) -> dict[str, Any]:
                                    # Include both defined fields and extra fields
                                    result = super().model_dump_one_level()
                                    # Add extra fields
                                    if (
                                        hasattr(self, "__pydantic_extra__")
                                        and self.__pydantic_extra__
                                    ):
                                        result.update(self.__pydantic_extra__)
                                    return result

                            # Create new FuncMetadata with the flexible model
                            mcp_tool.fn_metadata = FuncMetadata(
                                arg_model=FlexibleArgModel,
                                output_schema=mcp_tool.fn_metadata.output_schema,
                                output_model=mcp_tool.fn_metadata.output_model,
                                wrap_output=mcp_tool.fn_metadata.wrap_output,
                            )
                            logger.debug(
                                f"Set flexible argument model for {namespaced_name}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to set flexible argument model for {namespaced_name}: {e}"
                            )

                    tools_added += 1
                except Exception as e:
                    logger.warning(f"Failed to register tool {namespaced_name}: {e}")

        logger.info(f"Synchronized {tools_added} tools to MCP server")

        # Verify tool schemas
        for tool_name, mcp_tool in self.mcp_server._tool_manager._tools.items():
            has_tz = "timezone" in str(mcp_tool.parameters)
            logger.debug(
                f"Final schema for {tool_name}: has_timezone={has_tz}, params={mcp_tool.parameters}"
            )

    @contextlib.asynccontextmanager
    async def lifespan(self):
        """Lifespan context manager for the MCP server session manager.

        Usage:
            async with handlers.lifespan():
                # MCP server is running
                pass
        """
        if self.mcp_server is None or not hasattr(
            self.mcp_server, "session_manager"
        ):
            # No MCP server, just yield
            yield
            return

        # Verify tool schemas before starting session manager
        logger.debug(
            f"Pre-run check: {len(self.mcp_server._tool_manager._tools)} tools"
        )
        for tool_name, mcp_tool in self.mcp_server._tool_manager._tools.items():
            has_tz = "timezone" in str(mcp_tool.parameters)
            logger.debug(
                f"Pre-run {tool_name}: has_timezone={has_tz}, params={mcp_tool.parameters}"
            )

        async with self.mcp_server.session_manager.run():
            logger.info("MCP session manager started")
            yield
            logger.info("MCP session manager stopped")


def setup_mcp_handlers(app: FastAPI, deps: ServerDependencies) -> MCPHandlers:
    """Setup MCP protocol handlers and return handler instance."""
    handlers = MCPHandlers(deps)
    handlers.setup_routes(app)
    return handlers
