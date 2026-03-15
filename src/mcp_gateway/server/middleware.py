"""Middleware setup for MCP Gateway server."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from .state import ServerDependencies


logger = logging.getLogger(__name__)


class CircuitBreakerMiddleware:
    """ASGI Middleware to check circuit breaker state before processing requests."""

    def __init__(self, app: object, deps: ServerDependencies) -> None:
        """Initialize middleware with app and dependencies."""
        self.app = app
        self.deps = deps

    async def __call__(
        self, scope: dict[str, object], receive: object, send: object
    ) -> None:
        """ASGI application interface."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Build request object for path checking
        from starlette.requests import Request

        request = Request(scope, receive)
        path = request.url.path

        # Only check tool-related paths
        if path.startswith("/tools/") or path in ["/mcp", "/sse"]:
            # Extract backend name from path if possible
            backend_name = None
            if path.startswith("/tools/"):
                parts = path.split("/")
                if len(parts) >= 3:
                    backend_name = parts[2].split("__")[0]

            # Check circuit breaker state
            if backend_name and self.deps.circuit_breaker_registry:
                cb = self.deps.circuit_breaker_registry.get(backend_name)
                if cb and cb.is_open:  # type: ignore
                    retry_after = cb._get_retry_after()  # type: ignore
                    logger.warning(
                        f"Circuit breaker open for {backend_name}, "
                        f"retry after {retry_after:.0f}s"
                    )
                    response = JSONResponse(
                        status_code=503,
                        content={
                            "error": f"Service temporarily unavailable for {backend_name}",
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(int(retry_after))},
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def setup_middleware(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup all middleware for the FastAPI application."""

    # CORS middleware - must be first to handle OPTIONS requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=86400,  # 24 hours preflight cache
    )

    # Request timing middleware
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        """Add X-Process-Time header to responses."""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    # Auth middleware (if enabled) - uses setup_auth from auth module
    if deps.auth:
        from ..auth import setup_auth
        setup_auth(app, deps.auth.config)

    # Circuit breaker middleware
    app.add_middleware(CircuitBreakerMiddleware, deps=deps)
