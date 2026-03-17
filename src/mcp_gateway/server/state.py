"""Server state and dependencies container.

This module provides the ServerDependencies dataclass which implements
dependency injection for the MCP Gateway server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from ..access_control import AccessControlManager
    from ..admin import ConfigManager
    from ..auth import AuthMiddleware
    from ..backends import BackendManager
    from ..circuit_breaker import CircuitBreakerRegistry
    from ..config import GatewayConfig
    from ..metrics import MetricsCollector
    from ..rate_limiter import MemoryRateLimiter
    from ..services import AuditService, ConfigApprovalService, PathSecurityService
    from ..supervisor import ProcessSupervisor
    from .mcp_handlers import MCPHandlers


# Template and static directories
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"


@dataclass
class ServerDependencies:
    """Container for all server dependencies.

    This replaces the global app.state pattern with explicit dependency injection.
    All services and configuration are explicitly passed through this container,
    making the server easier to test and reason about.

    Example:
        >>> deps = ServerDependencies(
        ...     config=gateway_config,
        ...     backend_manager=backend_manager,
        ... )
        >>> server = McpGatewayServer(deps)

    Attributes:
        config: Gateway configuration
        backend_manager: Manager for backend connections
        config_manager: Optional config manager for persistence
        supervisor: Optional process supervisor
        audit_service: Optional audit logging service
        path_security: Optional path security service
        config_approval: Optional config approval service
        rate_limiter: Optional rate limiter for endpoints
        circuit_breaker_registry: Registry of circuit breakers
        metrics: Optional metrics collector
        auth: Optional auth middleware
        templates: Optional Jinja2 templates
        mcp_handlers: Optional MCP protocol handlers for tool sync
    """

    config: GatewayConfig
    backend_manager: BackendManager
    config_manager: ConfigManager | None = None
    supervisor: ProcessSupervisor | None = None
    audit_service: AuditService | None = None
    path_security: PathSecurityService | None = None
    access_control: AccessControlManager | None = None
    config_approval: ConfigApprovalService | None = None
    rate_limiter: MemoryRateLimiter | None = None
    circuit_breaker_registry: CircuitBreakerRegistry = field(
        default_factory=lambda: None  # type: ignore
    )
    metrics: MetricsCollector | None = None
    auth: AuthMiddleware | None = None
    templates: Jinja2Templates | None = None
    mcp_handlers: MCPHandlers | None = None

    def __post_init__(self) -> None:
        """Initialize default circuit breaker registry if not provided."""
        if self.circuit_breaker_registry is None:
            from ..circuit_breaker import CircuitBreakerRegistry
            self.circuit_breaker_registry = CircuitBreakerRegistry()
