"""HTTP API routes for MCP Gateway server."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from .models import CircuitBreakerStats, HealthCheckResponse, ServerConfigResponse

if TYPE_CHECKING:
    from fastapi import Response

    from .state import ServerDependencies


logger = logging.getLogger(__name__)


def setup_http_routes(
    app: FastAPI, deps: ServerDependencies, enable_access_control: bool
) -> None:
    """Setup all HTTP API routes."""
    _setup_health_routes(app, deps)
    _setup_admin_routes(app, deps)
    _setup_server_routes(app, deps)
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
    async def health_check() -> dict[str, object]:
        """Health check endpoint."""
        backends: list[dict[str, object]] = []
        for name, backend in deps.backend_manager.backends.items():
            cb_stats: dict[str, object] = {"state": "CLOSED"}
            if deps.circuit_breaker_registry:
                cb = deps.circuit_breaker_registry.get(name)
                if cb:
                    cb_stats = cb.get_stats()

            backends.append(
                {
                    "name": name,
                    "connected": backend.is_connected,
                    "tools": len(backend.tools),
                    "type": "stdio" if backend.config.is_stdio else "remote",
                    "circuit_breaker_state": cb_stats.get("state", "CLOSED"),
                }
            )

        return {
            "status": "healthy",
            "healthy": True,
            "total_backends": len(backends),
            "connected_backends": sum(1 for b in backends if b["connected"]),
            "total_tools": sum(b["tools"] for b in backends),  # type: ignore
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
    async def circuit_breaker_stats() -> dict[str, dict[str, object]]:
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
        return deps.templates.TemplateResponse(
            "retro-dashboard.html", {"request": request}
        )

    @app.get("/retro-admin", response_class=HTMLResponse, tags=["admin"])
    async def retro_admin(request: Request) -> Response:
        """Retro 80s CRT terminal themed admin panel."""
        if not deps.templates:
            raise HTTPException(status_code=500, detail="Templates not available")
        return deps.templates.TemplateResponse(
            "retro-admin.html", {"request": request}
        )


def _setup_server_routes(app: FastAPI, deps: ServerDependencies) -> None:
    """Setup server management routes."""

    @app.get(
        "/api/servers",
        response_model=dict[str, list[ServerConfigResponse]],
        tags=["config"],
        summary="List all servers",
    )
    async def list_servers() -> dict[str, list[dict[str, object]]]:
        """List all configured MCP servers."""
        if not deps.config_manager:
            raise HTTPException(
                status_code=503, detail="Config management not available"
            )

        servers: list[dict[str, object]] = []
        for name, server in deps.config_manager.gateway_config.servers.items():
            backend = deps.backend_manager.backends.get(name)
            available_tools: list[str] = []
            if backend and backend.is_connected:
                available_tools = [tool.name for tool in backend.tools]

            servers.append(
                {
                    "name": name,
                    "command": server.command,
                    "args": server.args,
                    "url": server.url,
                    "type": server.type,
                    "disabledTools": server.disabled_tools,
                    "availableTools": available_tools,
                }
            )

        return {"servers": servers}

    @app.get(
        "/api/servers/{name}/tools",
        tags=["config"],
        summary="Get server tools",
    )
    async def get_server_tools(name: str) -> dict[str, object]:
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
    async def update_server(name: str, request: Request) -> dict[str, object]:
        """Update server configuration with approval flow for sensitive paths."""
        if not deps.config_manager:
            raise HTTPException(
                status_code=503, detail="Config management not available"
            )

        from ..admin import validate_server_config
        from ..services import ApprovalResult

        config: dict[str, object] = await request.json()
        logger.info(
            f"Update server request for '{name}' with args: {config.get('args', [])}"
        )

        # Validate
        is_valid, error = validate_server_config(config)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)

        # Check if approval needed
        if deps.config_approval:
            current_server = deps.config_manager.gateway_config.servers.get(name)
            original_config: dict[str, object] = {}
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

            if result.error:
                raise HTTPException(status_code=400, detail=result.error)

            if result.requires_approval:
                # Apply safe paths immediately
                if result.safe_paths:
                    safe_config = config.copy()
                    safe_args = [
                        arg
                        for arg in config.get("args", [])
                        if arg in original_config.get("args", [])
                        or arg in result.safe_paths
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
                        {"code": r.code, "path": r.path}
                        for r in result.pending_requests
                    ],
                    "safe_paths_applied": result.safe_paths,
                    "message": (
                        f"{len(result.pending_requests)} sensitive path(s) "
                        "require CLI approval"
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
    async def create_server(request: Request) -> dict[str, object]:
        """Create a new MCP server configuration."""
        if not deps.config_manager:
            raise HTTPException(
                status_code=503, detail="Config management not available"
            )

        from ..admin import validate_server_config

        data: dict[str, object] = await request.json()
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
            raise HTTPException(
                status_code=409, detail=f"Server '{name}' already exists"
            )

        try:
            await deps.config_manager.add_server(str(name), config)
            return {"success": True, "server": {"name": name}}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.delete(
        "/api/servers/{name}",
        tags=["config"],
        summary="Delete server",
    )
    async def delete_server(name: str) -> dict[str, object]:
        """Delete an MCP server configuration."""
        if not deps.config_manager:
            raise HTTPException(
                status_code=503, detail="Config management not available"
            )

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
    async def reload_config() -> dict[str, object]:
        """Reload configuration from disk."""
        if not deps.config_manager:
            raise HTTPException(
                status_code=503, detail="Config management not available"
            )

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
    async def list_backends() -> dict[str, list[dict[str, object]]]:
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
    async def get_supervision() -> dict[str, object]:
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
    async def restart_backend(name: str) -> dict[str, object]:
        """Restart a specific backend."""
        if deps.supervisor:
            success = await deps.supervisor.restart_backend(name)
            if success:
                return {
                    "success": True,
                    "message": f"Backend '{name}' restarted",
                }
            else:
                raise HTTPException(
                    status_code=500, detail=f"Failed to restart backend '{name}'"
                )

        # Fallback to backend manager
        try:
            if not deps.config_manager:
                raise HTTPException(
                    status_code=503, detail="Config management not available"
                )
            server_config = deps.config_manager.gateway_config.servers.get(name)
            if not server_config:
                raise HTTPException(
                    status_code=404, detail=f"Server '{name}' not found"
                )
            await deps.backend_manager.restart_backend(name, server_config)
            return {"success": True, "message": f"Backend '{name}' restarted"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # Access Control Stub Routes
    @app.get(
        "/api/access/requests/pending",
        tags=["access-control"],
        summary="List pending access requests",
    )
    async def list_pending_access_requests() -> dict[str, list]:
        """List pending path access requests."""
        return {"requests": []}

    @app.get(
        "/api/access/grants/active",
        tags=["access-control"],
        summary="List active access grants",
    )
    async def list_active_access_grants() -> dict[str, list]:
        """List active path access grants."""
        return {"grants": []}

    @app.post(
        "/api/access/requests/{code}/approve",
        tags=["access-control"],
        summary="Approve an access request",
    )
    async def approve_access_request(code: str) -> dict[str, object]:
        """Approve a path access request."""
        raise HTTPException(
            status_code=503, detail="Access control service not available"
        )

    @app.post(
        "/api/access/requests/{code}/deny",
        tags=["access-control"],
        summary="Deny an access request",
    )
    async def deny_access_request(code: str) -> dict[str, object]:
        """Deny a path access request."""
        raise HTTPException(
            status_code=503, detail="Access control service not available"
        )

    @app.delete(
        "/api/access/grants/{grant_id}",
        tags=["access-control"],
        summary="Revoke an access grant",
    )
    async def revoke_access_grant(grant_id: str) -> dict[str, object]:
        """Revoke an active access grant."""
        raise HTTPException(
            status_code=503, detail="Access control service not available"
        )

    # Additional Config Change Routes
    @app.get(
        "/api/config-changes/grants",
        tags=["config"],
        summary="List active config change grants",
    )
    async def list_config_change_grants_stub() -> dict[str, list]:
        """List active config change grants."""
        return {"grants": []}

    @app.post(
        "/api/config-changes/{code}/deny",
        tags=["config"],
        summary="Deny a config change request",
    )
    async def deny_config_change_stub(code: str) -> dict[str, object]:
        """Deny a config change request."""
        raise HTTPException(status_code=503, detail="Approval service not available")

    @app.delete(
        "/api/config-changes/grants/{grant_id}",
        tags=["config"],
        summary="Revoke a config change grant",
    )
    async def revoke_config_change_grant_stub(grant_id: str) -> dict[str, object]:
        """Revoke an active config change grant."""
        return {"success": True, "message": f"Grant {grant_id} revoked"}

    # SSE Events stub
    @app.get("/api/access/events")
    async def access_events_sse(request: Request) -> Response:
        """SSE endpoint for access control events (stub)."""

        async def event_stream():
            # Send a dummy event every 30 seconds to keep connection alive
            while True:
                await asyncio.sleep(30)
                yield b"data: {}\n\n"

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
    async def list_pending_changes() -> dict[str, list[dict[str, object]]]:
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
    async def approve_change(code: str, request: Request) -> dict[str, object]:
        """Approve a config change request."""
        if not deps.config_approval:
            raise HTTPException(
                status_code=503, detail="Approval service not available"
            )

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

        data: dict[str, object] = await request.json()
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
                server_cfg = deps.config_manager.gateway_config.servers.get(
                    grant.server_name
                )
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
                    async def do_restart():
                        try:
                            # Add a small delay to let the API response complete first
                            await asyncio.sleep(0.5)
                            logger.info(
                                f"Starting restart of backend {grant.server_name}"
                            )
                            if deps.supervisor:
                                await deps.supervisor.restart_backend(
                                    grant.server_name, restart_config
                                )
                            else:
                                await deps.backend_manager.restart_backend(
                                    grant.server_name, restart_config
                                )
                            logger.info(
                                f"Backend {grant.server_name} restarted successfully"
                            )
                        except asyncio.CancelledError:
                            logger.debug(
                                f"Backend restart for {grant.server_name} was cancelled"
                            )
                        except Exception as restart_err:
                            logger.error(
                                f"Backend restart failed: {restart_err}", exc_info=True
                            )

                    # Schedule restart without awaiting (don't block response)
                    asyncio.create_task(do_restart())
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
