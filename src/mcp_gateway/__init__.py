"""MCP Gateway - Aggregate multiple MCP servers into one endpoint."""

__version__ = "0.1.0"

# Export exceptions for convenience
from .exceptions import (
    AccessDeniedError,
    AuthenticationError,
    BackendConnectionError,
    CircuitBreakerOpenError,
    ConfigValidationError,
    GatewayError,
    RateLimitExceededError,
    ServerNotFoundError,
    ToolNotFoundError,
)

__all__ = [
    "GatewayError",
    "BackendConnectionError",
    "ConfigValidationError",
    "AccessDeniedError",
    "CircuitBreakerOpenError",
    "AuthenticationError",
    "RateLimitExceededError",
    "ToolNotFoundError",
    "ServerNotFoundError",
]
