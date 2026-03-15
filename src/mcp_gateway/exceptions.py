"""Custom exception hierarchy for MCP Gateway.

This module provides a structured exception hierarchy for all gateway errors,
enabling better error handling and reporting throughout the application.

Example:
    >>> from mcp_gateway.exceptions import BackendConnectionError
    >>> try:
    ...     await backend.connect()
    ... except BackendConnectionError as e:
    ...     logger.error(f"Connection failed: {e}")

Classes:
    GatewayError: Base exception for all gateway errors
    BackendConnectionError: Raised when backend connection fails
    ConfigValidationError: Raised when configuration validation fails
    AccessDeniedError: Raised when access is denied
    CircuitBreakerOpenError: Raised when circuit breaker is open
    AuthenticationError: Raised when authentication fails
    RateLimitExceededError: Raised when rate limit is exceeded
    ToolNotFoundError: Raised when a tool is not found
    ServerNotFoundError: Raised when a server is not found
"""


class GatewayError(Exception):
    """Base exception for all gateway errors.

    All custom exceptions in MCP Gateway inherit from this class.
    This allows catching all gateway-specific errors with a single except clause.

    Attributes:
        message: Human-readable error description
        code: Optional error code for programmatic handling
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            code: Optional error code for programmatic handling
        """
        super().__init__(message)
        self.message = message
        self.code = code


class BackendConnectionError(GatewayError):
    """Raised when backend connection fails.

    This includes connection timeouts, protocol errors, and
    unexpected disconnections from MCP backend servers.

    Example:
        >>> try:
        ...     await backend.connect()
        ... except BackendConnectionError as e:
        ...     await circuit_breaker.record_failure()

    Attributes:
        backend_name: Name of the backend that failed to connect
        details: Additional error details from the connection attempt
    """

    def __init__(
        self,
        message: str,
        backend_name: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            backend_name: Name of the backend that failed
            details: Additional error details
        """
        super().__init__(message, code="BACKEND_CONNECTION_ERROR")
        self.backend_name = backend_name
        self.details = details or {}


class ConfigValidationError(GatewayError):
    """Raised when configuration validation fails.

    This includes invalid server configurations, missing required fields,
    and malformed configuration files.

    Example:
        >>> try:
        ...     config = GatewayConfig.from_file(path)
        ... except ConfigValidationError as e:
        ...     print(f"Invalid config: {e.message}")

    Attributes:
        field: The configuration field that failed validation
        value: The invalid value that was provided
    """

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: object = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            field: The configuration field that failed validation
            value: The invalid value that was provided
        """
        super().__init__(message, code="CONFIG_VALIDATION_ERROR")
        self.field = field
        self.value = value


class AccessDeniedError(GatewayError):
    """Raised when access is denied.

    This includes access control violations, insufficient permissions,
    and attempts to access sensitive paths without approval.

    Example:
        >>> try:
        ...     await access_control.check_access(mcp_name, tool, path, allowed)
        ... except AccessDeniedError as e:
        ...     return {"error": "Access denied", "code": e.code}

    Attributes:
        resource: The resource that was being accessed
        reason: Why access was denied
    """

    def __init__(
        self,
        message: str,
        resource: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            resource: The resource that was being accessed
            reason: Why access was denied
        """
        super().__init__(message, code="ACCESS_DENIED")
        self.resource = resource
        self.reason = reason


class CircuitBreakerOpenError(GatewayError):
    """Raised when circuit breaker is open.

    This error indicates that a backend has failed repeatedly and
    the circuit breaker has opened to prevent further attempts.

    Example:
        >>> try:
        ...     await circuit_breaker.call(backend.call_tool, name, args)
        ... except CircuitBreakerOpenError as e:
        ...     return {"error": "Service temporarily unavailable"}

    Attributes:
        backend_name: Name of the backend with open circuit
        retry_after: Seconds until the circuit may close
    """

    def __init__(
        self,
        message: str,
        backend_name: str | None = None,
        retry_after: float = 0.0,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            backend_name: Name of the backend with open circuit
            retry_after: Seconds until the circuit may close
        """
        super().__init__(message, code="CIRCUIT_BREAKER_OPEN")
        self.backend_name = backend_name
        self.retry_after = retry_after


class AuthenticationError(GatewayError):
    """Raised when authentication fails.

    This includes invalid API keys, expired bearer tokens, and
    missing credentials for protected endpoints.

    Example:
        >>> try:
        ...     user = await auth_middleware.authenticate(request)
        ... except AuthenticationError as e:
        ...     raise HTTPException(status_code=401, detail=str(e))

    Attributes:
        auth_type: Type of authentication that failed (api_key, bearer, etc.)
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        auth_type: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            auth_type: Type of authentication that failed
        """
        super().__init__(message, code="AUTHENTICATION_ERROR")
        self.auth_type = auth_type


class RateLimitExceededError(GatewayError):
    """Raised when rate limit is exceeded.

    This error indicates that a client has made too many requests
    and must wait before making additional requests.

    Example:
        >>> try:
        ...     result = await rate_limiter.check(client_ip)
        ...     if not result.allowed:
        ...         raise RateLimitExceededError(retry_after=result.retry_after)
        ... except RateLimitExceededError as e:
        ...     raise HTTPException(status_code=429, headers={"Retry-After": str(e.retry_after)})

    Attributes:
        retry_after: Seconds until the client can retry
        limit: The rate limit that was exceeded
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: float = 60.0,
        limit: int | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description
            retry_after: Seconds until the client can retry
            limit: The rate limit that was exceeded
        """
        super().__init__(message, code="RATE_LIMIT_EXCEEDED")
        self.retry_after = retry_after
        self.limit = limit


class ToolNotFoundError(GatewayError):
    """Raised when a tool is not found.

    This error indicates that the requested tool does not exist
    in any connected backend.

    Example:
        >>> try:
        ...     backend = backend_manager.get_backend_for_tool(tool_name)
        ... except ToolNotFoundError as e:
        ...     return {"error": f"Tool not found: {e.tool_name}"}

    Attributes:
        tool_name: Name of the tool that was not found
    """

    def __init__(self, tool_name: str, message: str | None = None) -> None:
        """Initialize the error.

        Args:
            tool_name: Name of the tool that was not found
            message: Optional custom error message
        """
        msg = message or f"Tool not found: {tool_name}"
        super().__init__(msg, code="TOOL_NOT_FOUND")
        self.tool_name = tool_name


class ServerNotFoundError(GatewayError):
    """Raised when a server is not found.

    This error indicates that the requested MCP server does not exist
    in the gateway configuration.

    Example:
        >>> try:
        ...     server = config_manager.gateway_config.servers[name]
        ... except ServerNotFoundError as e:
        ...     raise HTTPException(status_code=404, detail=str(e))

    Attributes:
        server_name: Name of the server that was not found
    """

    def __init__(self, server_name: str, message: str | None = None) -> None:
        """Initialize the error.

        Args:
            server_name: Name of the server that was not found
            message: Optional custom error message
        """
        msg = message or f"Server not found: {server_name}"
        super().__init__(msg, code="SERVER_NOT_FOUND")
        self.server_name = server_name


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
