"""HTTP API routes for MCP Gateway server."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from ..config import load_config
from .models import CircuitBreakerStats, HealthCheckResponse, ServerConfigResponse

if TYPE_CHECKING:
    from fastapi import Response

    from .state import ServerDependencies


logger = logging.getLogger(__name__)


def setup_http_routes(app: FastAPI, deps: ServerDependencies, enable_access_control: bool) -> None:
    """Setup all HTTP API routes."""
    _setup_health_routes(app, deps)
    _setup_admin_routes(app, deps)
    _setup_server_routes(app, deps)
    _setup_logs_routes(app, deps)
    if enable_access_control and deps.config_approval:
        _setup_approval_routes(app, deps)


def _setup_health_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup health and monitoring routes."""

    @app.get(
        "/health",
        response_model=HealthCheckResponse,
        tags=["health"],
        summary="Health check",
        description="Returns health status of the gateway and all backends",
    )
    async def health_check() -> dict[str, Any]:
        """Health check endpoint with diagnostic information."""
        backends: list[dict[str, object]] = []

        # Get diagnostic info for all backends (connected and failed)
        all_backends = deps.backend_manager.get_backend_diagnostics()

        for backend_diag in all_backends:
            name = str(backend_diag["name"])
            is_connected = bool(backend_diag["connected"])

            cb_stats: dict[str, object] = {"state": "CLOSED"}
            if deps.circuit_breaker_registry:
                cb = deps.circuit_breaker_registry.get(name)
                if cb:
                    cb_stats = cb.get_stats()

            # Get backend config for type info
            backend_config = deps.config_manager.gateway_config.servers.get(name)
            backend_type = "stdio"
            if backend_config:
                backend_type = "remote" if backend_config.url else "stdio"

            backend_info: dict[str, object] = {
                "name": name,
                "connected": is_connected,
                "tools": int(backend_diag.get("tools", 0)),
                "type": backend_type,
                "circuit_breaker_state": cb_stats.get("state", "CLOSED"),
                "status": "connected" if is_connected else "error",
            }

            # Add diagnostic info for failed backends
            if not is_connected and backend_diag.get("diagnostic"):
                diag = backend_diag["diagnostic"]
                backend_info["diagnostic"] = {
                    "error_message": diag.get("error_message", "Connection failed"),
                    "fix_tip": diag.get("fix_tip", "Check server configuration"),
                    "connection_attempts": backend_diag.get("connection_attempts", 0),
                    "last_attempt": diag.get("last_attempt"),
                }

            backends.append(backend_info)

        connected_count = sum(1 for b in backends if b["connected"])

        # Gateway is healthy if at least one backend is connected OR no backends configured
        is_healthy = connected_count > 0 or len(backends) == 0

        return {
            "status": "healthy" if is_healthy else "degraded",
            "healthy": is_healthy,
            "total_backends": len(backends),
            "connected_backends": connected_count,
            "failed_backends": len(backends) - connected_count,
            "total_tools": int(sum(b["tools"] for b in backends)),
            "backends": backends,
        }

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        tags=["health"],
        summary="Prometheus metrics",
    )
    async def metrics() -> PlainTextResponse:
        """Prometheus metrics endpoint."""
        if deps.metrics:
            content = deps.metrics.generate_metrics()
            return PlainTextResponse(content=content)
        return PlainTextResponse(content="# No metrics available")

    @app.get(
        "/circuit-breakers",
        response_model=dict[str, CircuitBreakerStats],
        tags=["health"],
        summary="Circuit breaker statistics",
    )
    async def circuit_breaker_stats() -> dict[str, Any]:
        """Get circuit breaker statistics for all backends."""
        if deps.circuit_breaker_registry:
            return deps.circuit_breaker_registry.get_all_stats()
        return {}


def _setup_admin_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup admin dashboard routes."""

    @app.get("/", response_class=HTMLResponse, tags=["admin"])
    async def dashboard(request: Request) -> Response:
        """Main dashboard HTML page."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/admin", response_class=HTMLResponse, tags=["admin"])
    async def admin_dashboard(request: Request) -> Response:
        """Admin dashboard HTML page."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse("admin.html", {"request": request})

    @app.get("/blue-box", response_class=HTMLResponse, tags=["admin"])
    async def blue_box_dashboard(request: Request) -> Response:
        """Blue Box themed dashboard."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse("blue-box.html", {"request": request})

    @app.get("/retro", response_class=HTMLResponse, tags=["admin"])
    async def retro_dashboard(request: Request) -> Response:
        """Retro 80s CRT terminal themed dashboard."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse("retro-dashboard.html", {"request": request})

    @app.get("/retro-admin", response_class=HTMLResponse, tags=["admin"])
    async def retro_admin(request: Request) -> Response:
        """Retro 80s CRT terminal themed admin panel."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse("retro-admin.html", {"request": request})


def _setup_server_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup server management routes."""

    @app.get(
        "/api/servers",
        response_model=dict[str, list[ServerConfigResponse]],
        tags=["config"],
        summary="List all servers",
    )
    async def list_servers() -> dict[str, list[dict[str, Any]]]:
        """List all configured MCP servers with connection status and diagnostics."""
        if not deps.config_manager:
            raise HTTPException(status_code=503, detail="Config management not available")

        servers: list[dict[str, Any]] = []
        for name, server in deps.config_manager.gateway_config.servers.items():
            backend = deps.backend_manager.backends.get(name)
            available_tools: list[str] = []
            server_info: dict[str, Any] = {
                "name": name,
                "command": server.command,
                "args": server.args,
                "url": server.url,
                "type": server.type,
                "disabledTools": server.disabled_tools,
                "enabled": server.enabled,
                "availableTools": available_tools,
                "connectionStatus": "unknown",
            }

            if backend:
                if backend.is_connected:
                    available_tools = [tool.name for tool in backend.tools]
                    server_info["availableTools"] = available_tools
                    server_info["connectionStatus"] = "connected"
                else:
                    server_info["connectionStatus"] = "error"
                    # Add diagnostic info for failed connections
                    if backend.last_error:
                        server_info["diagnostic"] = {
                            "error": backend.last_error,
                            "fixTip": backend.diagnostic_tip,
                            "attempts": backend.connection_attempts,
                        }

            servers.append(server_info)

        return {"servers": servers}

    @app.get(
        "/api/servers/{name}/tools",
        tags=["config"],
        summary="Get server tools",
    )
    async def get_server_tools(name: str) -> dict[str, Any]:
        """Get list of tools available for a specific server."""
        backend = deps.backend_manager.backends.get(name)
        if not backend:
            raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

        tools = []
        if backend.is_connected:
            for tool in backend.tools:
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                    }
                )

        # Get disabled tools from server config
        disabled_tools: list[str] = []
        if deps.config_manager:
            server_config = deps.config_manager.gateway_config.servers.get(name)
            if server_config:
                disabled_tools = server_config.disabled_tools

        return {"tools": tools, "disabledTools": disabled_tools}

    @app.put(
        "/api/servers/{name}",
        tags=["config"],
        summary="Update server configuration",
    )
    async def update_server(name: str, request: Request) -> dict[str, Any]:
        """Update server configuration with approval flow for sensitive paths."""
        if not deps.config_manager:
            raise HTTPException(status_code=503, detail="Config management not available")

        from ..admin import validate_server_config
        from ..services import ApprovalResult

        config: dict[str, Any] = await request.json()
        logger.info(f"Update server request for '{name}' with args: {config.get('args', [])}")
        logger.debug(f"Full config received: {config}")

        # Validate
        is_valid, error = validate_server_config(config)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)

        # Check if approval needed
        if deps.config_approval:
            current_server = deps.config_manager.gateway_config.servers.get(name)
            original_config: dict[str, Any] = {}
            if current_server:
                original_config = {
                    "command": current_server.command,
                    "args": current_server.args,
                    "env": current_server.env,
                    "url": current_server.url,
                    "type": current_server.type,
                    "headers": current_server.headers,
                    "disabledTools": current_server.disabled_tools,
                }

            result: ApprovalResult = await deps.config_approval.check_config_change(
                server_name=name,
                change_type="modify",
                original_config=original_config,
                new_config=config,
            )
            logger.info(
                f"Config approval check for '{name}': "
                f"requires_approval={result.requires_approval}, "
                f"safe_paths={result.safe_paths}, "
                f"pending={len(result.pending_requests)}"
            )

            if result.error:
                raise HTTPException(status_code=400, detail=result.error)

            if result.requires_approval:
                # Apply safe paths immediately
                if result.safe_paths:
                    safe_config = config.copy()
                    safe_args = [
                        arg
                        for arg in config.get("args", [])
                        if arg in original_config.get("args", []) or arg in result.safe_paths
                    ]
                    safe_config["args"] = safe_args
                    await deps.config_manager.update_server(name, safe_config)
                    await deps.config_manager.save()

                # Get first pending request code for display
                approval_code = (
                    result.pending_requests[0].code if result.pending_requests else "UNKNOWN"
                )

                return {
                    "success": False,
                    "requires_approval": True,
                    "approval_code": approval_code,
                    "pending_requests": [
                        {"code": r.code, "path": r.path} for r in result.pending_requests
                    ],
                    "safe_paths_applied": result.safe_paths,
                    "message": (
                        f"{len(result.pending_requests)} sensitive path(s) require CLI approval"
                    ),
                }

        # No approval needed, apply directly
        try:
            await deps.config_manager.update_server(name, config)
            logger.info(f"Server '{name}' updated successfully")
            return {"success": True, "server": {"name": name}}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post(
        "/api/servers",
        tags=["config"],
        summary="Create new server",
    )
    async def create_server(request: Request) -> dict[str, Any]:
        """Create a new MCP server configuration and activate it."""
        if not deps.config_manager:
            raise HTTPException(status_code=503, detail="Config management not available")

        from ..admin import validate_server_config
        from ..config import ServerConfig

        data: dict[str, Any] = await request.json()
        name = data.get("name")
        config = data.get("config", {})

        if not name:
            raise HTTPException(status_code=400, detail="Server name is required")

        # Validate
        is_valid, error = validate_server_config(config)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)

        # Check if server already exists
        if name in deps.config_manager.gateway_config.servers:
            raise HTTPException(status_code=409, detail=f"Server '{name}' already exists")

        try:
            # Save configuration
            await deps.config_manager.add_server(str(name), config)

            # Create ServerConfig for backend connection
            server_config = ServerConfig(
                name=name,
                command=config.get("command"),
                args=config.get("args", []),
                env=config.get("env", {}),
                url=config.get("url"),
                type=config.get("type"),
                headers=config.get("headers", {}),
                disabled_tools=config.get("disabledTools", []),
                enabled=config.get("enabled", True),
            )

            # Only connect if server is enabled
            if server_config.enabled:
                # Connect the new backend
                logger.info(f"Connecting to new backend: {name}")
                await deps.backend_manager.add_backend(server_config)

                # Add to process supervisor if enabled
                if deps.supervisor:
                    logger.info(f"Adding {name} to process supervision")
                    await deps.supervisor.start_supervision({name: server_config})
            else:
                logger.info(f"Server '{name}' is disabled, skipping connection")

            # Update config in memory
            if deps.config_manager:
                deps.config_manager.gateway_config = load_config(deps.config_manager.config_path)

            # Sync tools to MCP server
            if deps.mcp_handlers:
                deps.mcp_handlers.sync_tools()

            logger.info(f"New backend '{name}' activated successfully")

            return {"success": True, "server": {"name": name}}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Failed to activate new backend '{name}': {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Server created but activation failed: {e}"
            ) from e

    @app.delete(
        "/api/servers/{name}",
        tags=["config"],
        summary="Delete server",
    )
    async def delete_server(name: str) -> dict[str, Any]:
        """Delete an MCP server configuration."""
        if not deps.config_manager:
            raise HTTPException(status_code=503, detail="Config management not available")

        try:
            await deps.config_manager.remove_server(name)
            return {"success": True, "message": f"Server '{name}' deleted"}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post(
        "/api/reload",
        tags=["config"],
        summary="Reload configuration",
    )
    async def reload_config() -> dict[str, Any]:
        """Reload configuration from disk."""
        if not deps.config_manager:
            raise HTTPException(status_code=503, detail="Config management not available")

        try:
            await deps.config_manager.reload()
            return {"success": True, "message": "Configuration reloaded"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.get(
        "/backends",
        tags=["config"],
        summary="List all backends",
    )
    async def list_backends() -> dict[str, list[dict[str, Any]]]:
        """List all backends with their connection status."""
        backends: list[dict[str, object]] = []
        for name, backend in deps.backend_manager.backends.items():
            backends.append(
                {
                    "name": name,
                    "connected": backend.is_connected,
                    "tools": len(backend.tools),
                }
            )
        return {"backends": backends}

    @app.get(
        "/supervision",
        tags=["config"],
        summary="Get supervision status",
    )
    async def get_supervision() -> dict[str, Any]:
        """Get process supervision status and statistics."""
        if not deps.supervisor:
            return {"enabled": False}

        return {
            "enabled": True,
            "backends": deps.supervisor.get_stats(),
        }

    @app.post(
        "/backends/{name}/restart",
        tags=["config"],
        summary="Restart a backend",
    )
    async def restart_backend(name: str) -> dict[str, Any]:
        """Restart a specific backend."""
        if deps.supervisor:
            success = await deps.supervisor.restart_backend(name)
            if success:
                return {
                    "success": True,
                    "message": f"Backend '{name}' restarted",
                }
            else:
                raise HTTPException(status_code=500, detail=f"Failed to restart backend '{name}'")

        # Fallback to backend manager
        try:
            if not deps.config_manager:
                raise HTTPException(status_code=503, detail="Config management not available")
            server_config = deps.config_manager.gateway_config.servers.get(name)
            if not server_config:
                raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
            await deps.backend_manager.restart_backend(name, server_config)
            return {"success": True, "message": f"Backend '{name}' restarted"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # Access Control Routes
    @app.get(
        "/api/access/requests/pending",
        tags=["access-control"],
        summary="List pending access requests",
    )
    async def list_pending_access_requests() -> dict[str, list[Any]]:
        """List pending path access requests."""
        if not deps.access_control:
            return {"requests": []}

        requests = deps.access_control.get_pending_requests()
        return {
            "requests": [
                {
                    "id": r.id,
                    "code": r.code,
                    "mcp_name": r.mcp_name,
                    "path": r.path,
                    "status": r.status.value,
                    "created_at": r.created_at.isoformat(),
                    "expires_at": r.expires_at.isoformat(),
                }
                for r in requests
            ]
        }

    @app.get(
        "/api/access/grants/active",
        tags=["access-control"],
        summary="List active access grants",
    )
    async def list_active_access_grants() -> dict[str, list[Any]]:
        """List active path access grants."""
        if not deps.access_control:
            return {"grants": []}

        grants = await deps.access_control.get_active_grants()
        return {
            "grants": [
                {
                    "id": g.id,
                    "request_id": g.request_id,
                    "mcp_name": g.mcp_name,
                    "path": g.path,
                    "granted_at": g.granted_at.isoformat(),
                    "expires_at": g.expires_at.isoformat(),
                    "duration_minutes": g.duration_minutes,
                }
                for g in grants
            ]
        }

    @app.post(
        "/api/access/requests/{code}/approve",
        tags=["access-control"],
        summary="Approve an access request",
    )
    async def approve_access_request(code: str, request: Request) -> dict[str, Any]:
        """Approve a path access request."""
        if not deps.access_control:
            raise HTTPException(status_code=503, detail="Access control service not available")

        data: dict[str, Any] = await request.json() if await request.body() else {}
        duration = data.get("duration_minutes", 1)

        success, message, grant = await deps.access_control.approve_request(
            code=code,
            duration_minutes=int(duration),
        )

        if not success:
            raise HTTPException(status_code=400, detail=message)

        return {
            "success": True,
            "message": message,
            "grant": {
                "id": grant.id,
                "mcp_name": grant.mcp_name,
                "path": grant.path,
                "expires_at": grant.expires_at.isoformat(),
                "duration_minutes": grant.duration_minutes,
            }
            if grant
            else None,
        }

    @app.post(
        "/api/access/requests/{code}/deny",
        tags=["access-control"],
        summary="Deny an access request",
    )
    async def deny_access_request(code: str) -> dict[str, Any]:
        """Deny a path access request."""
        if not deps.access_control:
            raise HTTPException(status_code=503, detail="Access control service not available")

        success, message = await deps.access_control.deny_request(code)

        if not success:
            raise HTTPException(status_code=400, detail=message)

        return {"success": True, "message": message}

    @app.delete(
        "/api/access/grants/{grant_id}",
        tags=["access-control"],
        summary="Revoke an access grant",
    )
    async def revoke_access_grant(grant_id: str) -> dict[str, Any]:
        """Revoke an active access grant."""
        if not deps.access_control:
            raise HTTPException(status_code=503, detail="Access control service not available")

        success = await deps.access_control.revoke_grant(grant_id)

        if not success:
            raise HTTPException(status_code=404, detail="Grant not found")

        return {"success": True, "message": "Grant revoked successfully"}

    # Config Change Routes (via access_control)
    @app.get(
        "/api/config-changes/grants",
        tags=["config"],
        summary="List active config change grants",
    )
    async def list_config_change_grants() -> dict[str, list[Any]]:
        """List active config change grants."""
        if not deps.access_control:
            return {"grants": []}

        grants = deps.access_control.get_active_config_grants()
        return {
            "grants": [
                {
                    "id": g.id,
                    "request_id": g.request_id,
                    "server_name": g.server_name,
                    "sensitive_path": g.sensitive_path,
                    "granted_at": g.granted_at.isoformat(),
                    "expires_at": g.expires_at.isoformat(),
                    "duration_minutes": g.duration_minutes,
                }
                for g in grants
            ]
        }

    @app.post(
        "/api/config-changes/{code}/deny",
        tags=["config"],
        summary="Deny a config change request",
    )
    async def deny_config_change(code: str) -> dict[str, Any]:
        """Deny a config change request."""
        if not deps.access_control:
            raise HTTPException(status_code=503, detail="Access control service not available")

        success, message = await deps.access_control.deny_config_change(code)

        if not success:
            raise HTTPException(status_code=400, detail=message)

        return {"success": True, "message": message}

    @app.delete(
        "/api/config-changes/grants/{grant_id}",
        tags=["config"],
        summary="Revoke a config change grant",
    )
    async def revoke_config_change_grant(grant_id: str) -> dict[str, Any]:
        """Revoke an active config change grant."""
        if not deps.access_control:
            raise HTTPException(status_code=503, detail="Access control service not available")

        success, message = await deps.access_control.revert_config_change(grant_id)

        if not success:
            raise HTTPException(status_code=404, detail=message)

        return {"success": True, "message": message}

    # SSE Events endpoint for real-time access control notifications
    @app.get("/api/access/events")
    async def access_events_sse(request: Request) -> Response:
        """SSE endpoint for access control events."""

        async def event_stream() -> Any:  # type: ignore[return-value]
            if not deps.access_control:
                # No access control service - send keepalive only
                while True:
                    await asyncio.sleep(30)
                    yield b"event: keepalive\ndata: {}\n\n"
                return

            # Subscribe to notifications
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def notification_handler(event_type: str, data: dict[str, Any]) -> None:
                await queue.put({"type": event_type, "data": data})

            deps.access_control.register_notification_callback(notification_handler)

            try:
                # Send initial connection event
                yield b'event: connected\ndata: {"status": "connected"}\n\n'

                # Stream events
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30)
                        event_json = json.dumps(event)
                        yield f"event: access_control\ndata: {event_json}\n\n".encode()
                    except TimeoutError:
                        # Send keepalive
                        yield b"event: keepalive\ndata: {}\n\n"
            finally:
                # Note: There's no unregister method, callbacks are cleaned up on disconnect
                pass

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )


def _setup_approval_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup config approval routes."""

    @app.get(
        "/api/config-changes/pending",
        tags=["config"],
        summary="List pending config changes",
    )
    async def list_pending_changes() -> dict[str, list[dict[str, Any]]]:
        """List pending config change requests."""
        if not deps.config_approval:
            logger.warning("Config approval service not available")
            return {"requests": []}

        try:
            requests = deps.config_approval.get_pending_requests()
            logger.info(f"Found {len(requests)} pending config change requests")
            return {
                "requests": [
                    {
                        "id": r.id,
                        "code": r.code,
                        "server_name": r.server_name,
                        "change_type": r.change_type,
                        "sensitive_path": r.sensitive_path,
                        "created_at": r.created_at.isoformat(),
                        "expires_at": r.expires_at.isoformat(),
                    }
                    for r in requests
                ]
            }
        except Exception as e:
            logger.error(f"Error getting pending requests: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post(
        "/api/config-changes/{code}/approve",
        tags=["config"],
        summary="Approve a config change",
    )
    async def approve_change(code: str, request: Request) -> dict[str, Any]:
        """Approve a config change request."""
        if not deps.config_approval:
            raise HTTPException(status_code=503, detail="Approval service not available")

        # Rate limit check
        if deps.rate_limiter:
            client_ip = request.client.host if request.client else "unknown"
            from ..rate_limiter import RateLimitResult

            limit_key = f"approve:{client_ip}"
            limit_result: RateLimitResult = await deps.rate_limiter.check(limit_key)
            if not limit_result.allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Retry after {limit_result.retry_after:.0f}s",
                )

        data: dict[str, Any] = await request.json()
        duration = data.get("duration_minutes", 1)
        approved_by = data.get("approved_by", "web")

        # Approve
        success, message, grant = await deps.config_approval.approve(
            code=code,
            duration_minutes=int(duration),
            approved_by=str(approved_by),
        )

        if not success:
            raise HTTPException(status_code=400, detail=message)

        # Apply and restart
        if grant and deps.config_manager:
            try:
                from ..config import ServerConfig

                await deps.config_manager.update_server(
                    grant.server_name, {"args": grant.target_args}
                )
                await deps.config_manager.save()

                # Restart backend
                server_cfg = deps.config_manager.gateway_config.servers.get(grant.server_name)
                if server_cfg:
                    restart_config = ServerConfig(
                        name=grant.server_name,
                        command=server_cfg.command,
                        args=server_cfg.args,
                        env=server_cfg.env,
                        url=server_cfg.url,
                        type=server_cfg.type,
                        headers=server_cfg.headers,
                        disabled_tools=server_cfg.disabled_tools,
                    )

                    # Restart in background to avoid blocking response
                    async def do_restart() -> None:  # type: ignore[no-untyped-def]
                        try:
                            # Add a small delay to let the API response complete first
                            await asyncio.sleep(0.5)
                            logger.info(f"Starting restart of backend {grant.server_name}")
                            if deps.supervisor:
                                await deps.supervisor.restart_backend(
                                    grant.server_name, restart_config
                                )
                            else:
                                await deps.backend_manager.restart_backend(
                                    grant.server_name, restart_config
                                )
                            logger.info(f"Backend {grant.server_name} restarted successfully")
                        except asyncio.CancelledError:
                            logger.debug(f"Backend restart for {grant.server_name} was cancelled")
                        except Exception as restart_err:
                            logger.error(f"Backend restart failed: {restart_err}", exc_info=True)

                    # Schedule restart without awaiting (don't block response)
                    asyncio.create_task(do_restart())  # type: ignore[misc]
            except Exception as e:
                logger.error(f"Restart failed: {e}")
                message += f" (Warning: restart failed: {e})"

        return {
            "success": True,
            "message": message,
            "grant": {
                "id": grant.id,
                "server_name": grant.server_name,
                "sensitive_path": grant.sensitive_path,
                "expires_at": grant.expires_at.isoformat(),
                "duration_minutes": grant.duration_minutes,
            }
            if grant
            else None,
        }


def _setup_logs_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup logs viewer routes."""
    from pathlib import Path

    TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

    @app.get("/logs", response_class=HTMLResponse, tags=["logs"])
    async def logs_page() -> HTMLResponse:
        """Serve the logs viewer page."""
        template_path = TEMPLATE_DIR / "logs.html"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Logs page not found")

        with open(template_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/api/logs", tags=["logs"])
    async def get_logs(
        minutes: int = 60,
        level: str | None = None,
        service: str | None = None,
        search: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Get application logs with filtering.

        Args:
            minutes: Time range in minutes (default: 60)
            level: Filter by log level (debug, info, warning, error)
            service: Filter by service name
            search: Search in log messages
            limit: Maximum number of logs to return

        Returns:
            List of log entries with metadata
        """
        import glob
        from datetime import datetime, timedelta

        # Calculate cutoff time
        cutoff = datetime.now() - timedelta(minutes=minutes)

        # Find log files
        log_dir = Path.cwd() / "logs"
        log_files = []

        if log_dir.exists():
            # Find all log files
            log_files = (
                glob.glob(str(log_dir / "*.log"))
                + glob.glob(str(log_dir / "*.json"))
                + glob.glob(str(log_dir / "*.jsonl"))
            )

        # Also check for structlog output in common locations
        possible_logs = [
            Path.cwd() / "logs" / "mcp-gateway.log",
            Path.cwd() / "logs" / "app.log",
            Path.cwd() / "mcp-gateway.log",
        ]

        for log_file in possible_logs:
            if log_file.exists() and str(log_file) not in log_files:
                log_files.append(str(log_file))

        logs = []

        # Parse log files
        for log_file in log_files:
            try:
                with open(log_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue

                        log_entry = _parse_log_line(line)
                        if log_entry:
                            # Check if within time range
                            if log_entry.get("timestamp"):
                                try:
                                    log_time = datetime.fromisoformat(
                                        log_entry["timestamp"].replace("Z", "+00:00")
                                    )
                                    if log_time < cutoff:
                                        continue
                                except (ValueError, TypeError):
                                    pass

                            # Apply filters
                            if level and log_entry.get("level", "").lower() != level.lower():
                                continue
                            if (
                                service
                                and service.lower() not in log_entry.get("service", "").lower()
                            ):
                                continue
                            if (
                                search
                                and search.lower() not in log_entry.get("message", "").lower()
                            ):
                                continue

                            logs.append(log_entry)

                            if len(logs) >= limit:
                                break
            except Exception as e:
                logger.debug(f"Error reading log file {log_file}: {e}")

        # Sort by timestamp (newest first)
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return {
            "logs": logs[:limit],
            "total": len(logs),
            "time_range_minutes": minutes,
        }


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def _parse_log_line(line: str) -> dict[str, Any] | None:
    """Parse a log line into structured format.

    Handles both JSON and plain text log formats, including ANSI escape codes.
    """
    import json as json_module

    # Strip ANSI escape codes for parsing
    clean_line = _strip_ansi(line)

    # Try JSON format first
    if clean_line.startswith("{"):
        try:
            data = json_module.loads(clean_line)
            return {
                "timestamp": data.get("timestamp") or data.get("time") or data.get("@timestamp"),
                "level": data.get("level") or data.get("severity") or "info",
                "message": data.get("event") or data.get("message") or data.get("msg") or "",
                "service": data.get("service") or data.get("logger") or "mcp-gateway",
                "raw": data,
            }
        except json_module.JSONDecodeError:
            pass

    # Try structured log format: timestamp [level] message (with ANSI)
    # Pattern: ISO timestamp followed by [level] with optional ANSI codes
    text_pattern = (
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*"
        r"(?:Z|[+-]\d{2}:\d{2})?)\s+(?:\x1B\[[0-;]*m)?"
        r"\[?(\w+)\]?(?:\x1B\[[0-9]*m)?\s+(.*)"
    )
    match = re.match(text_pattern, line)
    if match:
        return {
            "timestamp": match.group(1),
            "level": match.group(2).lower(),
            "message": _strip_ansi(match.group(3)),
            "service": "mcp-gateway",
            "raw": clean_line,
        }

    # Try simple format with clean line
    text_pattern_clean = (
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*"
        r"(?:Z|[+-]\d{2}:\d{2})?)\s+\[?(\w+)\]?\s+(.*)"
    )
    match = re.match(text_pattern_clean, clean_line)
    if match:
        return {
            "timestamp": match.group(1),
            "level": match.group(2).lower(),
            "message": match.group(3),
            "service": "mcp-gateway",
            "raw": clean_line,
        }

    # Fallback: return as-is (cleaned)
    return {
        "timestamp": None,
        "level": "info",
        "message": clean_line,
        "service": "mcp-gateway",
        "raw": clean_line,
    }
