"""Prometheus metrics for MCP Gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .logging_config import get_logger

if TYPE_CHECKING:
    from .backends import BackendManager

logger = get_logger(__name__)

# Try to import prometheus_client
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Create dummy classes for when prometheus_client is not installed
    class _DummyMetric:
        """Dummy metric class when prometheus is not available."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def labels(self, *args: Any, **kwargs: Any) -> _DummyMetric:
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set(self, *args: Any, **kwargs: Any) -> None:
            pass

        def observe(self, *args: Any, **kwargs: Any) -> None:
            pass

        def info(self, *args: Any, **kwargs: Any) -> None:
            pass

    Counter: type[_DummyMetric] = _DummyMetric  # type: ignore[assignment]
    Gauge: type[_DummyMetric] = _DummyMetric  # type: ignore[assignment]
    Histogram: type[_DummyMetric] = _DummyMetric  # type: ignore[assignment]
    Info: type[_DummyMetric] = _DummyMetric  # type: ignore[assignment]

    def _generate_latest() -> bytes:
        return b""

    generate_latest = _generate_latest
    CONTENT_TYPE_LATEST = "text/plain"


# Metrics definitions
METRICS_PREFIX = "mcp_gateway"

# Gateway info
gateway_info = Info(
    f"{METRICS_PREFIX}_info",
    "Gateway version and build information",
)

# Backend metrics
backends_connected = Gauge(
    f"{METRICS_PREFIX}_backends_connected",
    "Number of connected backends",
    ["backend_name"],
)
backends_total = Gauge(
    f"{METRICS_PREFIX}_backends_total",
    "Total number of configured backends",
)
tools_total = Gauge(
    f"{METRICS_PREFIX}_tools_total",
    "Total number of available tools",
)

# Request metrics
requests_total = Counter(
    f"{METRICS_PREFIX}_requests_total",
    "Total number of requests",
    ["method", "endpoint", "status"],
)
request_duration_seconds = Histogram(
    f"{METRICS_PREFIX}_request_duration_seconds",
    "Request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Tool call metrics
tool_calls_total = Counter(
    f"{METRICS_PREFIX}_tool_calls_total",
    "Total number of tool calls",
    ["backend", "tool", "status"],
)
tool_call_duration_seconds = Histogram(
    f"{METRICS_PREFIX}_tool_call_duration_seconds",
    "Tool call duration in seconds",
    ["backend", "tool"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
tool_call_errors_total = Counter(
    f"{METRICS_PREFIX}_tool_call_errors_total",
    "Total number of tool call errors",
    ["backend", "tool", "error_type"],
)

# Connection metrics
connection_errors_total = Counter(
    f"{METRICS_PREFIX}_connection_errors_total",
    "Total number of connection errors",
    ["backend", "error_type"],
)
connection_duration_seconds = Histogram(
    f"{METRICS_PREFIX}_connection_duration_seconds",
    "Backend connection duration in seconds",
    ["backend"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


@dataclass
class MetricsSnapshot:
    """Snapshot of current metrics for non-Prometheus consumers."""

    total_backends: int = 0
    connected_backends: int = 0
    total_tools: int = 0
    total_requests: int = 0
    total_tool_calls: int = 0
    backend_status: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "backends": {
                "total": self.total_backends,
                "connected": self.connected_backends,
                "details": self.backend_status,
            },
            "tools": {"total": self.total_tools},
            "requests": {"total": self.total_requests},
            "tool_calls": {"total": self.total_tool_calls},
        }


class MetricsCollector:
    """Collects and exposes metrics for the gateway."""

    def __init__(self, version: str = "0.1.0") -> None:
        self.version = version
        # Set gateway info
        gateway_info.info({"version": version})

    def record_http_request(
        self,
        method: str,
        path: str,
        status: int,
        duration: float,
    ) -> None:
        """Record HTTP request metrics."""
        requests_total.labels(
            method=method,
            endpoint=path,
            status=str(status),
        ).inc()
        request_duration_seconds.labels(
            method=method,
            endpoint=path,
        ).observe(duration)

    def record_request(
        self,
        method: str,
        endpoint: str,
        status: int,
        duration: float,
    ) -> None:
        """Record HTTP request metrics (backward-compatible alias)."""
        self.record_http_request(method, endpoint, status, duration)

    def record_tool_call(
        self,
        backend: str,
        tool: str,
        duration: float,
        error: str | None = None,
    ) -> None:
        """Record tool call metrics."""
        status = "error" if error else "success"
        tool_calls_total.labels(
            backend=backend,
            tool=tool,
            status=status,
        ).inc()
        tool_call_duration_seconds.labels(
            backend=backend,
            tool=tool,
        ).observe(duration)

        if error:
            tool_call_errors_total.labels(
                backend=backend,
                tool=tool,
                error_type=error,
            ).inc()

    def record_connection_error(
        self,
        backend: str,
        error_type: str,
    ) -> None:
        """Record connection error."""
        connection_errors_total.labels(
            backend=backend,
            error_type=error_type,
        ).inc()

    def record_connection_duration(
        self,
        backend: str,
        duration: float,
    ) -> None:
        """Record successful connection duration."""
        connection_duration_seconds.labels(backend=backend).observe(duration)

    def update_backend_status(
        self,
        backend_name: str,
        connected: bool,
        tool_count: int = 0,
    ) -> None:
        """Update backend connection status gauge."""
        value = 1.0 if connected else 0.0
        backends_connected.labels(backend_name=backend_name).set(value)

    def update_backends_total(self, count: int) -> None:
        """Update total backends gauge."""
        backends_total.set(count)

    def update_tools_total(self, count: int) -> None:
        """Update total tools gauge."""
        tools_total.set(count)

    def generate_metrics(self) -> str:
        """Get metrics in Prometheus exposition format.

        Returns:
            Metrics as a string
        """
        return generate_latest().decode("utf-8")

    def get_prometheus_format(self) -> tuple[str, str]:
        """Get metrics in Prometheus format with content type.

        Returns:
            Tuple of (content, content_type)
        """
        return self.generate_metrics(), "text/plain"

    def get_json_snapshot(
        self,
        backend_manager: BackendManager | None = None,
    ) -> MetricsSnapshot:
        """Get a JSON-serializable snapshot of current metrics."""
        snapshot = MetricsSnapshot()

        if backend_manager:
            backends = backend_manager.backends
            snapshot.total_backends = len(backends)
            snapshot.connected_backends = sum(
                1 for b in backends.values() if b.is_connected
            )
            snapshot.total_tools = len(backend_manager.get_all_tools())

            for name, backend in backends.items():
                snapshot.backend_status[name] = {
                    "connected": backend.is_connected,
                    "tools": len(backend.tools),
                    "type": backend.config.transport_type,
                }

        return snapshot


# Global collector instance
_collector: MetricsCollector | None = None


def setup_metrics(version: str = "0.1.0") -> MetricsCollector:
    """Initialize the global metrics collector."""
    global _collector
    _collector = MetricsCollector(version)
    logger.info("Metrics collector initialized", version=version)
    return _collector


def get_collector() -> MetricsCollector:
    """Get the global metrics collector."""
    global _collector
    if _collector is None:
        raise RuntimeError("Metrics not initialized. Call setup_metrics() first.")
    return _collector


# Export _DummyMetric for tests (conditionally available)
if not PROMETHEUS_AVAILABLE:
    DummyMetricExport = _DummyMetric  # type: ignore[assignment]
else:
    # Create a dummy class for testing when prometheus IS available
    class DummyMetricExport:
        """Dummy metric class for tests."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def labels(
            self, *args: Any, **kwargs: Any
        ) -> DummyMetricExport:
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set(self, *args: Any, **kwargs: Any) -> None:
            pass

        def observe(self, *args: Any, **kwargs: Any) -> None:
            pass

        def info(self, *args: Any, **kwargs: Any) -> None:
            pass

_DummyMetric = DummyMetricExport
