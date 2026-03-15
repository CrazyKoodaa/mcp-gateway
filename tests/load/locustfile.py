"""Locust load testing configuration for MCP Gateway.

Run with: locust -f tests/load/locustfile.py --host http://localhost:3000

Requirements:
    pip install locust

Usage:
    1. Start the gateway: python -m mcp_gateway
    2. Run locust: locust -f tests/load/locustfile.py
    3. Open browser at http://localhost:8089
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task


class MCPGatewayUser(HttpUser):
    """Simulates an MCP client interacting with the gateway."""
    
    wait_time = between(0.1, 1.0)  # Wait 0.1-1.0s between tasks
    
    def on_start(self) -> None:
        """Called when a user starts."""
        # Health check
        self.client.get("/health")
    
    @task(10)
    def health_check(self) -> None:
        """Check gateway health."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("healthy"):
                    response.success()
                else:
                    response.failure("Gateway not healthy")
            else:
                response.failure(f"Status code: {response.status_code}")
    
    @task(5)
    def get_metrics(self) -> None:
        """Get Prometheus metrics."""
        self.client.get("/metrics")
    
    @task(5)
    def list_backends(self) -> None:
        """List connected backends."""
        with self.client.get("/backends", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if "backends" in data:
                    response.success()
                else:
                    response.failure("Invalid response format")
    
    @task(3)
    def list_servers(self) -> None:
        """List configured servers."""
        self.client.get("/api/servers")
    
    @task(2)
    def get_circuit_breaker_stats(self) -> None:
        """Get circuit breaker statistics."""
        self.client.get("/circuit-breakers")
    
    @task(1)
    def get_pending_changes(self) -> None:
        """Get pending config changes."""
        self.client.get("/api/config-changes/pending")


class AdminUser(HttpUser):
    """Simulates an admin user performing management tasks."""
    
    wait_time = between(1.0, 5.0)
    weight = 1  # Less frequent than regular users
    
    @task(3)
    def view_admin_dashboard(self) -> None:
        """View admin dashboard."""
        self.client.get("/admin")
    
    @task(1)
    def restart_backend(self) -> None:
        """Restart a random backend."""
        # Get list of backends first
        response = self.client.get("/backends")
        if response.status_code == 200:
            data = response.json()
            backends = data.get("backends", [])
            if backends:
                backend = random.choice(backends)
                name = backend["name"]
                with self.client.post(
                    f"/backends/{name}/restart",
                    catch_response=True
                ) as restart_response:
                    if restart_response.status_code in [200, 202]:
                        restart_response.success()
                    else:
                        restart_response.failure(
                            f"Restart failed: {restart_response.status_code}"
                        )


class StressTestUser(HttpUser):
    """High-intensity stress test user."""
    
    wait_time = between(0.01, 0.1)  # Very short waits
    weight = 0  # Disabled by default, enable with --tag stress
    
    @task
    def rapid_health_checks(self) -> None:
        """Rapid health checks to stress the system."""
        self.client.get("/health")
    
    @task
    def rapid_metrics(self) -> None:
        """Rapid metrics requests."""
        self.client.get("/metrics")


class CircuitBreakerTestUser(HttpUser):
    """Test user that triggers circuit breaker scenarios."""
    
    wait_time = between(0.5, 2.0)
    weight = 0  # Disabled by default
    
    @task
    def trigger_backend_errors(self) -> None:
        """Simulate scenarios that might trigger circuit breaker."""
        # Rapid requests that might fail
        for _ in range(10):
            self.client.get("/health")
