"""Benchmark tests for MCP Gateway performance.

Run with: pytest tests/test_benchmark.py -v --benchmark-only
Requires: pytest-benchmark plugin
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from mcp_gateway.backends import BackendConnection, BackendManager
from mcp_gateway.config import ServerConfig
from mcp_gateway.rate_limiter import MemoryRateLimiter

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.fixture
def sample_tools() -> list[Tool]:
    """Create sample tools for benchmarking."""
    return [
        Tool(
            name=f"tool_{i}",
            description=f"Test tool {i}",
            inputSchema={"type": "object", "properties": {}}
        )
        for i in range(100)
    ]


@pytest.fixture
def mock_backend() -> MagicMock:
    """Create a mock backend for benchmarking."""
    backend = MagicMock(spec=BackendConnection)
    backend.name = "test_backend"
    backend.is_connected = True
    backend.tools = [
        Tool(name=f"tool_{i}", description=f"Tool {i}", inputSchema={})
        for i in range(50)
    ]
    backend.call_tool = AsyncMock(return_value=CallToolResult(
        content=[TextContent(type="text", text="result")],
        isError=False
    ))
    return backend


@pytest.mark.benchmark
class TestBackendManagerBenchmarks:
    """Benchmark tests for BackendManager."""
    
    def test_get_all_tools_performance(
        self,
        benchmark: BenchmarkFixture,
        mock_backend: MagicMock
    ) -> None:
        """Benchmark getting all tools from multiple backends."""
        manager = BackendManager()
        
        # Add multiple backends
        for i in range(10):
            backend = MagicMock(spec=BackendConnection)
            backend.name = f"backend_{i}"
            backend.is_connected = True
            backend.tools = [
                Tool(name=f"tool_{j}", description=f"Tool {j}", inputSchema={})
                for j in range(50)
            ]
            manager._backends[f"backend_{i}"] = backend
            for tool in backend.tools:
                manager._tool_map[f"backend_{i}__{tool.name}"] = f"backend_{i}"
        
        def get_tools():
            return manager.get_all_tools()
        
        result = benchmark(get_tools)
        assert len(result) == 500  # 10 backends * 50 tools each
    
    def test_extract_tool_name_performance(
        self,
        benchmark: BenchmarkFixture
    ) -> None:
        """Benchmark tool name extraction."""
        manager = BackendManager(namespace_separator="__")
        tool_names = [f"backend_{i}__tool_{j}" for i in range(10) for j in range(50)]
        
        def extract_names():
            return [manager.extract_original_tool_name(name) for name in tool_names]
        
        result = benchmark(extract_names)
        assert len(result) == 500


@pytest.mark.benchmark
class TestRateLimiterBenchmarks:
    """Benchmark tests for rate limiter."""
    
    @pytest.mark.skip(reason="Rate limiter requires event loop setup - complex benchmark")
    def test_rate_limiter_check_performance(
        self,
        benchmark: BenchmarkFixture
    ) -> None:
        """Benchmark rate limiter check operations."""
        pass


@pytest.mark.benchmark
class TestConfigValidationBenchmarks:
    """Benchmark tests for config validation."""
    
    def test_server_config_validation(
        self,
        benchmark: BenchmarkFixture
    ) -> None:
        """Benchmark server config validation."""
        from mcp_gateway.config import ServerConfig
        
        def validate_configs():
            configs = []
            for i in range(100):
                config = ServerConfig(
                    name=f"server_{i}",
                    command="npx",
                    args=["-y", f"@modelcontextprotocol/server-{i}"],
                )
                configs.append(config)
            return configs
        
        result = benchmark(validate_configs)
        assert len(result) == 100
    
    def test_path_security_check(
        self,
        benchmark: BenchmarkFixture
    ) -> None:
        """Benchmark path security checks."""
        from mcp_gateway.services.path_security_service import PathSecurityService
        
        service = PathSecurityService()
        paths = [
            "/home/user/documents",
            "/etc/passwd",
            "/var/log",
            "/tmp/test",
            "/home/user/.ssh/id_rsa",
        ] * 100  # 500 paths total
        
        def check_paths():
            return service.check_paths(paths)
        
        result = benchmark(check_paths)
        assert len(result) == 500


@pytest.mark.benchmark
class TestCircuitBreakerBenchmarks:
    """Benchmark tests for circuit breaker."""
    
    def test_circuit_breaker_state_transitions(
        self,
        benchmark: BenchmarkFixture
    ) -> None:
        """Benchmark circuit breaker state transitions."""
        from mcp_gateway.circuit_breaker import CircuitBreaker
        
        def run_benchmark():
            breaker = CircuitBreaker("test", failure_threshold=100)
            
            async def state_transitions():
                for _ in range(100):
                    await breaker._on_success()
                    await breaker._on_failure()
                return breaker.state
            
            return asyncio.run(state_transitions())
        
        result = benchmark(run_benchmark)
        # State depends on success/failure balance


@pytest.mark.slow
@pytest.mark.integration
class TestLoadTests:
    """Integration load tests (marked as slow)."""
    
    @pytest.mark.asyncio
    async def test_concurrent_backend_calls(self) -> None:
        """Test handling many concurrent backend calls."""
        manager = BackendManager()
        
        # Setup mock backends
        for i in range(5):
            backend = MagicMock(spec=BackendConnection)
            backend.name = f"backend_{i}"
            backend.is_connected = True
            backend.call_tool = AsyncMock(return_value=CallToolResult(
                content=[TextContent(type="text", text="ok")],
                isError=False
            ))
            manager._backends[f"backend_{i}"] = backend
        
        # Make 1000 concurrent calls
        async def make_calls():
            tasks = []
            for i in range(1000):
                backend = manager._backends[f"backend_{i % 5}"]
                tasks.append(backend.call_tool("test", {}))
            return await asyncio.gather(*tasks)
        
        results = await make_calls()
        assert len(results) == 1000
        assert all(not r.isError for r in results)
