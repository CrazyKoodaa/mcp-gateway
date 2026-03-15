"""Structured logging configuration for MCP Gateway.

Provides JSON-formatted logs suitable for log aggregation systems
like ELK, Splunk, or cloud-native logging solutions.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

import structlog
from structlog.processors import JSONRenderer, TimeStamper
from structlog.stdlib import filter_by_level


def setup_structured_logging(
    log_level: str = "INFO",
    json_format: bool = True,
    service_name: str = "mcp-gateway"
) -> None:
    """Configure structured logging for the application.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Whether to output JSON format (vs console)
        service_name: Service name to include in logs
    """
    # Configure structlog
    shared_processors: list[structlog.types.Processor] = [
        # Add timestamp
        TimeStamper(fmt="iso"),
        # Add log level
        structlog.stdlib.add_log_level,
        # Add caller info
        structlog.stdlib.PositionalArgumentsFormatter(),
        # Filter by level
        filter_by_level,
        # Add service context
        structlog.contextvars.merge_contextvars,
    ]

    if json_format:
        # JSON formatting for production
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.ExceptionPrettyPrinter(),
                JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Console formatting for development
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Set service name in context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)

    # Reduce noise from third-party libraries
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)


class RequestContext:
    """Context manager for request-bound logging context.

    Example:
        >>> with RequestContext(request_id="abc123", client_ip="1.2.3.4"):
        ...     logger.info("Processing request")
        ...     # Logs include request_id and client_ip
    """

    def __init__(self, **context: Any):
        self.context = context
        self.token = None

    def __enter__(self) -> RequestContext:
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        structlog.contextvars.unbind_contextvars(*self.context.keys())
        return False


def async_request_context(
    **context: Any,
) -> AsyncGenerator[None, None]:
    """Async context manager for request-bound logging.

    Example:
        >>> async with async_request_context(request_id="abc123"):
        ...     await process_request()
    """
    token = structlog.contextvars.bind_contextvars(**context)  # noqa: F841
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*context.keys())


def log_request(
    logger: structlog.stdlib.BoundLogger,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    **extra: Any
) -> None:
    """Log an HTTP request with standard fields.

    Args:
        logger: Logger instance
        method: HTTP method
        path: Request path
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        **extra: Additional fields to log
    """
    log_data = {
        "event": "http_request",
        "http_method": method,
        "http_path": path,
        "http_status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        **extra
    }

    if status_code >= 500:
        logger.error(**log_data)
    elif status_code >= 400:
        logger.warning(**log_data)
    else:
        logger.info(**log_data)


def log_backend_call(
    logger: structlog.stdlib.BoundLogger,
    backend_name: str,
    tool_name: str,
    duration_ms: float,
    success: bool,
    error: str | None = None,
    **extra: Any
) -> None:
    """Log a backend tool call.

    Args:
        logger: Logger instance
        backend_name: Name of the backend
        tool_name: Name of the tool called
        duration_ms: Call duration in milliseconds
        success: Whether the call succeeded
        error: Error message if failed
        **extra: Additional fields
    """
    log_data = {
        "event": "backend_call",
        "backend_name": backend_name,
        "tool_name": tool_name,
        "duration_ms": round(duration_ms, 2),
        "success": success,
        **extra
    }

    if error:
        log_data["error"] = error

    if success:
        logger.info(**log_data)
    else:
        logger.error(**log_data)
