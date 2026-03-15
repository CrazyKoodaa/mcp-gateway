"""Tests for mcp_gateway.metrics module."""

import pytest
from unittest.mock import MagicMock, patch

from mcp_gateway.metrics import (
    MetricsCollector,
    MetricsSnapshot,
    setup_metrics,
    get_collector,
)


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""
    
    def test_default_values(self):
        """Test MetricsSnapshot default values."""
        snapshot = MetricsSnapshot()
        assert snapshot.total_backends == 0
        assert snapshot.connected_backends == 0
        assert snapshot.total_tools == 0
        assert snapshot.total_requests == 0
        assert snapshot.total_tool_calls == 0
        assert snapshot.backend_status == {}
    
    def test_custom_values(self):
        """Test MetricsSnapshot with custom values."""
        snapshot = MetricsSnapshot(
            total_backends=3,
            connected_backends=2,
            total_tools=10,
            total_requests=100,
            total_tool_calls=50,
            backend_status={"backend1": {"connected": True}}
        )
        assert snapshot.total_backends == 3
        assert snapshot.connected_backends == 2
        assert snapshot.total_tools == 10
        assert snapshot.total_requests == 100
        assert snapshot.total_tool_calls == 50
    
    def test_to_dict(self):
        """Test to_dict method."""
        snapshot = MetricsSnapshot(
            total_backends=2,
            connected_backends=1,
            total_tools=5,
            total_requests=10,
            total_tool_calls=20,
            backend_status={"backend1": {"connected": True}}
        )
        
        result = snapshot.to_dict()
        
        assert result["backends"]["total"] == 2
        assert result["backends"]["connected"] == 1
        assert result["backends"]["details"] == {"backend1": {"connected": True}}
        assert result["tools"]["total"] == 5
        assert result["requests"]["total"] == 10
        assert result["tool_calls"]["total"] == 20


class TestMetricsCollector:
    """Tests for MetricsCollector class."""
    
    @pytest.fixture
    def collector(self):
        """Return a MetricsCollector instance."""
        return MetricsCollector(version="1.0.0")
    
    def test_initialization(self, collector):
        """Test MetricsCollector initialization."""
        assert collector.version == "1.0.0"
    
    def test_record_request(self, collector):
        """Test recording HTTP request metrics."""
        # Should not raise any errors
        collector.record_request(
            method="GET",
            endpoint="/health",
            status=200,
            duration=0.1,
        )
        # Metrics are recorded to Prometheus (or dummy when not available)
    
    def test_record_tool_call_success(self, collector):
        """Test recording successful tool call."""
        collector.record_tool_call(
            backend="memory",
            tool="add",
            duration=0.5,
            error=None,
        )
    
    def test_record_tool_call_error(self, collector):
        """Test recording failed tool call."""
        collector.record_tool_call(
            backend="memory",
            tool="add",
            duration=1.0,
            error="ToolNotFoundError",
        )
    
    def test_record_connection_error(self, collector):
        """Test recording connection error."""
        collector.record_connection_error(
            backend="remote-server",
            error_type="ConnectionTimeout",
        )
    
    def test_record_connection_duration(self, collector):
        """Test recording connection duration."""
        collector.record_connection_duration(
            backend="remote-server",
            duration=2.5,
        )
    
    def test_update_backend_status_connected(self, collector):
        """Test updating backend status to connected."""
        collector.update_backend_status(
            backend_name="memory",
            connected=True,
            tool_count=5,
        )
    
    def test_update_backend_status_disconnected(self, collector):
        """Test updating backend status to disconnected."""
        collector.update_backend_status(
            backend_name="memory",
            connected=False,
            tool_count=0,
        )
    
    def test_update_backends_total(self, collector):
        """Test updating total backends count."""
        collector.update_backends_total(count=5)
    
    def test_update_tools_total(self, collector):
        """Test updating total tools count."""
        collector.update_tools_total(count=20)
    
    def test_get_prometheus_format(self, collector):
        """Test getting metrics in Prometheus format."""
        content, content_type = collector.get_prometheus_format()
        
        assert isinstance(content, str)
        assert content_type == "text/plain"
    
    def test_get_json_snapshot_no_backend_manager(self, collector):
        """Test getting JSON snapshot without backend manager."""
        snapshot = collector.get_json_snapshot(backend_manager=None)
        
        assert snapshot.total_backends == 0
        assert snapshot.connected_backends == 0
        assert snapshot.total_tools == 0
    
    def test_get_json_snapshot_with_backend_manager(self, collector):
        """Test getting JSON snapshot with backend manager."""
        backend_manager = MagicMock()
        
        backend1 = MagicMock()
        backend1.is_connected = True
        backend1.tools = [MagicMock(), MagicMock()]
        backend1.config.transport_type = "stdio"
        
        backend2 = MagicMock()
        backend2.is_connected = False
        backend2.tools = []
        backend2.config.transport_type = "streamable-http"
        
        backend_manager.backends = {"backend1": backend1, "backend2": backend2}
        backend_manager.get_all_tools.return_value = [
            MagicMock(), MagicMock(), MagicMock()
        ]
        
        snapshot = collector.get_json_snapshot(backend_manager=backend_manager)
        
        assert snapshot.total_backends == 2
        assert snapshot.connected_backends == 1
        assert snapshot.total_tools == 3
        assert "backend1" in snapshot.backend_status
        assert "backend2" in snapshot.backend_status


class TestSetupMetrics:
    """Tests for setup_metrics function."""
    
    def test_setup_metrics(self):
        """Test setting up global metrics collector."""
        # Reset the global collector first
        import mcp_gateway.metrics as metrics
        metrics._collector = None
        
        collector = setup_metrics(version="1.0.0")
        
        assert collector is not None
        assert isinstance(collector, MetricsCollector)
        assert collector.version == "1.0.0"
    
    def test_setup_metrics_logging(self):
        """Test that setup_metrics logs initialization."""
        with patch("mcp_gateway.metrics.logger") as mock_logger:
            import mcp_gateway.metrics as metrics
            metrics._collector = None
            
            setup_metrics(version="2.0.0")
            
            mock_logger.info.assert_called_once()


class TestGetCollector:
    """Tests for get_collector function."""
    
    def test_get_collector_initialized(self):
        """Test getting collector when initialized."""
        import mcp_gateway.metrics as metrics
        metrics._collector = MetricsCollector(version="1.0.0")
        
        collector = get_collector()
        
        assert collector is not None
        assert isinstance(collector, MetricsCollector)
    
    def test_get_collector_not_initialized(self):
        """Test getting collector when not initialized."""
        import mcp_gateway.metrics as metrics
        # Reset the global collector
        metrics._collector = None
        
        with pytest.raises(RuntimeError, match="Metrics not initialized"):
            get_collector()


class TestDummyMetrics:
    """Tests for dummy metrics when prometheus_client is not available."""
    
    def test_dummy_metric_methods(self):
        """Test that dummy metrics have all required methods."""
        from mcp_gateway.metrics import _DummyMetric
        
        dummy = _DummyMetric()
        
        # These should all work without errors
        labeled = dummy.labels("test")
        dummy.inc()
        dummy.set(1.0)
        dummy.observe(0.5)
        dummy.info({"version": "1.0"})
        
        # labels should return self for chaining
        assert labeled is dummy
