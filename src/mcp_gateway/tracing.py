"""OpenTelemetry tracing configuration for MCP Gateway.

Provides distributed tracing support for monitoring and debugging
request flows across the gateway and backends.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

# Get tracer
tracer = trace.get_tracer("mcp-gateway")


def setup_tracing(
    service_name: str = "mcp-gateway",
    service_version: str = "0.1.0",
    otlp_endpoint: str | None = None,
    console_export: bool = False,
) -> TracerProvider:
    """Setup OpenTelemetry tracing.

    Args:
        service_name: Name of the service
        service_version: Version of the service
        otlp_endpoint: OTLP endpoint URL (e.g., "http://localhost:4317")
        console_export: Whether to export to console (for debugging)

    Returns:
        Configured TracerProvider
    """
    # Create resource
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    # Create provider
    provider = TracerProvider(resource=resource)

    # Add exporters
    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    if console_export:
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))

    # Set as global provider
    trace.set_tracer_provider(provider)

    return provider


@asynccontextmanager
async def trace_request(
    operation: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[trace.Span, None]:
    """Context manager for tracing an operation.

    Example:
        >>> async with trace_request("backend_call", SpanKind.CLIENT) as span:
        ...     result = await call_backend()
        ...     span.set_attribute("backend.name", "memory")
    """
    with tracer.start_as_current_span(operation, kind=kind) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@asynccontextmanager
async def trace_backend_call(
    backend_name: str,
    tool_name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[trace.Span, None]:
    """Context manager for tracing backend tool calls.

    Example:
        >>> async with trace_backend_call("memory", "add") as span:
        ...     result = await backend.call_tool("add", args)
    """
    attrs = {
        "backend.name": backend_name,
        "backend.tool": tool_name,
    }
    if attributes:
        attrs.update(attributes)

    async with trace_request(
        f"backend.{backend_name}.{tool_name}",
        kind=SpanKind.CLIENT,
        attributes=attrs,
    ) as span:
        yield span


def add_event(span: trace.Span, name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add an event to the current span.

    Args:
        span: The span to add event to
        name: Event name
        attributes: Optional event attributes
    """
    span.add_event(name, attributes)


def set_attribute(span: trace.Span, key: str, value: Any) -> None:
    """Set an attribute on the current span.

    Args:
        span: The span to set attribute on
        key: Attribute key
        value: Attribute value
    """
    span.set_attribute(key, value)


class Traced:
    """Decorator for tracing function calls.

    Example:
        >>> class MyService:
        ...     @Traced("process_request")
        ...     async def process(self, request):
        ...         return await self._process(request)
    """

    def __init__(self, operation: str | None = None):
        self.operation = operation

    def __call__(self, func):
        operation_name = self.operation or func.__name__

        async def async_wrapper(*args, **kwargs):
            with tracer.start_as_current_span(operation_name) as span:
                span.set_attribute("function.name", func.__name__)
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return async_wrapper


def get_current_span() -> trace.Span | None:
    """Get the current active span.

    Returns:
        Current span or None if no span is active
    """
    return trace.get_current_span()
