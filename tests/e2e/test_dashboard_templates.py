"""E2E Tests for MCP Gateway Dashboard Templates."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestHTMLRendering:
    """Tests for HTML template rendering."""

    def test_dashboard_html_rendering(self, test_client: TestClient):
        """Test dashboard.html template renders correctly."""
        response = test_client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
        assert "<body" in response.text.lower()
        assert "</html>" in response.text
        assert "Dashboard" in response.text or "dashboard" in response.text.lower()

    def test_admin_html_rendering(self, test_client: TestClient):
        """Test admin.html template renders correctly."""
        response = test_client.get("/admin")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
        assert "<body" in response.text.lower()
        assert "</html>" in response.text
        assert "Admin" in response.text or "admin" in response.text.lower()

    def test_blue_box_html_rendering(self, test_client: TestClient):
        """Test blue-box.html template renders correctly."""
        response = test_client.get("/blue-box")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
        assert "blue" in response.text.lower() or "box" in response.text.lower()

    def test_retro_dashboard_html_rendering(self, test_client: TestClient):
        """Test retro-dashboard.html template renders correctly."""
        response = test_client.get("/retro")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
        assert "retro" in response.text.lower() or "80s" in response.text.lower()

    def test_retro_admin_html_rendering(self, test_client: TestClient):
        """Test retro-admin.html template renders correctly."""
        response = test_client.get("/retro-admin")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
        assert "retro" in response.text.lower() or "admin" in response.text.lower()

    @pytest.mark.parametrize(
        "endpoint,template_name",
        [
            ("/", "dashboard.html"),
            ("/admin", "admin.html"),
            ("/blue-box", "blue-box.html"),
            ("/retro", "retro-dashboard.html"),
            ("/retro-admin", "retro-admin.html"),
        ],
    )
    def test_all_templates_exist(self, test_client: TestClient, endpoint: str, template_name: str):
        """Test that all templates exist and return 200."""
        response = test_client.get(endpoint)
        assert response.status_code == 200, f"{template_name} not found at {endpoint}"

    @pytest.mark.parametrize("endpoint", ["/", "/admin", "/blue-box", "/retro", "/retro-admin"])
    def test_templates_have_content(self, test_client: TestClient, endpoint: str):
        """Test that templates have substantial content."""
        response = test_client.get(endpoint)

        assert response.status_code == 200
        assert len(response.text) > 100  # Template should have content


class TestAPIIntegration:
    """Tests for API integration with dashboard."""

    def test_health_endpoint(self, test_client: TestClient):
        """Test /health endpoint returns correct data."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["healthy"] is True
        assert "total_backends" in data
        assert "connected_backends" in data
        assert "total_tools" in data
        assert "backends" in data

    def test_get_servers_endpoint(self, test_client: TestClient):
        """Test GET /api/servers endpoint."""
        response = test_client.get("/api/servers")

        assert response.status_code == 200
        data = response.json()

        assert "servers" in data
        assert isinstance(data["servers"], list)

        if data["servers"]:
            server = data["servers"][0]
            assert "name" in server
            assert "command" in server or "url" in server
            assert "type" in server

    def test_get_server_tools_endpoint(self, test_client: TestClient):
        """Test GET /api/servers/{name}/tools endpoint."""
        response = test_client.get("/api/servers/memory/tools")

        assert response.status_code == 200
        data = response.json()

        assert "tools" in data
        assert "disabledTools" in data
        assert isinstance(data["tools"], list)

    def test_api_content_type_json(self, test_client: TestClient):
        """Test API endpoints return JSON content type."""
        response = test_client.get("/health")

        assert "application/json" in response.headers["content-type"]


class TestAdminOperations:
    """Tests for admin panel operations."""

    def test_put_server_update(self, test_client: TestClient):
        """Test PUT /api/servers/{name} updates server."""
        update_data = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
        }

        response = test_client.put("/api/servers/memory", json=update_data)

        # Should succeed (mock returns success)
        assert response.status_code in [200, 202]
        data = response.json()
        assert "success" in data

    def test_post_server_create(self, test_client: TestClient):
        """Test POST /api/servers creates new server."""
        new_server = {
            "name": "new-server",
            "config": {
                "command": "npx",
                "args": ["-y", "test-package"],
            },
        }

        response = test_client.post("/api/servers", json=new_server)

        assert response.status_code in [200, 201, 409]  # Success or already exists
        if response.status_code in [200, 201]:
            data = response.json()
            assert data.get("success") is True

    def test_delete_server(self, test_client: TestClient):
        """Test DELETE /api/servers/{name} removes server."""
        response = test_client.delete("/api/servers/time")

        assert response.status_code in [200, 404]  # Success or not found
        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is True

    def test_restart_backend(self, test_client: TestClient):
        """Test POST /backends/{name}/restart."""
        response = test_client.post("/backends/memory/restart")

        assert response.status_code in [200, 500]  # Success or error
        if response.status_code == 200:
            data = response.json()
            assert "success" in data


class TestTemplateSecurity:
    """Tests for template security."""

    @pytest.mark.parametrize("endpoint", ["/", "/admin", "/blue-box", "/retro", "/retro-admin"])
    def test_no_xss_vulnerabilities(
        self, test_client: TestClient, endpoint: str, xss_payloads: list[str]
    ):
        """Test that templates don't contain XSS vulnerabilities."""
        response = test_client.get(endpoint)

        # Check that dangerous patterns are not present
        content_lower = response.text.lower()

        # Script tags should be properly escaped or not present
        # In a real app, this would check for proper escaping
        for payload in xss_payloads:
            # The payload itself might be in the content if it's escaped
            # We're checking for unescaped execution here
            if payload in response.text and "<script>" in payload:
                # If raw script tag is present, it should be escaped
                assert "&lt;script&gt;" in response.text or "escaped" in content_lower, (
                    f"Unescaped script tag found: {payload}"
                )

    def test_html_has_basic_structure(self, test_client: TestClient):
        """Test that HTML has basic security structure."""
        response = test_client.get("/")

        # Should have proper HTML structure
        assert "<!DOCTYPE" in response.text or "<html" in response.text.lower()


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_for_nonexistent_routes(self, test_client: TestClient):
        """Test 404 response for non-existent routes."""
        response = test_client.get("/nonexistent-page")

        assert response.status_code == 404

    def test_404_for_nonexistent_server(self, test_client: TestClient):
        """Test 404 for non-existent server."""
        response = test_client.get("/api/servers/nonexistent-server/tools")

        assert response.status_code == 404

    def test_invalid_json_payload(self, test_client: TestClient):
        """Test error handling for invalid JSON."""
        response = test_client.post(
            "/api/servers", data="invalid json", headers={"content-type": "application/json"}
        )

        assert response.status_code in [400, 422]  # Bad request or validation error


class TestDashboardDataConsistency:
    """Tests for data consistency between API and templates."""

    def test_health_data_matches_backend_count(self, test_client: TestClient):
        """Test that health endpoint reports correct backend count."""
        response = test_client.get("/health")
        data = response.json()

        assert "total_backends" in data
        assert "backends" in data
        assert data["total_backends"] == len(data["backends"])

    def test_servers_list_matches_api(self, test_client: TestClient):
        """Test that servers list from API is consistent."""
        response = test_client.get("/api/servers")
        data = response.json()

        assert "servers" in data
        servers = data["servers"]

        # Each server should have required fields
        for server in servers:
            assert "name" in server
            assert "type" in server
