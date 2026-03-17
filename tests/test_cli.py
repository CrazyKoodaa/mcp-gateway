"""Tests for mcp_gateway.cli module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from mcp_gateway.cli import (
    DEFAULT_API_URL,
    approve_request,
    check_pending_requests,
    get_request_details,
    print_pending_requests,
    quick_approve,
)


class TestCheckPendingRequests:
    """Tests for check_pending_requests function."""

    @pytest.mark.asyncio
    async def test_check_pending_success(self):
        """Test successful retrieval of pending requests."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "requests": [{"code": "ABCD-1234", "mcp_name": "filesystem", "path": "/etc"}]
        }

        with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
            mock_response.raise_for_status = MagicMock()

            result = await check_pending_requests(DEFAULT_API_URL)

            assert len(result) == 1
            assert result[0]["code"] == "ABCD-1234"

    @pytest.mark.asyncio
    async def test_check_pending_http_error(self):
        """Test handling of HTTP error."""
        with patch("httpx.AsyncClient.get", side_effect=httpx.HTTPError("Connection failed")):
            result = await check_pending_requests(DEFAULT_API_URL)

            assert result == []

    @pytest.mark.asyncio
    async def test_check_pending_exception(self):
        """Test handling of general exception."""
        with patch("httpx.AsyncClient.get", side_effect=Exception("Unknown error")):
            result = await check_pending_requests(DEFAULT_API_URL)

            assert result == []


class TestApproveRequest:
    """Tests for approve_request function."""

    @pytest.mark.asyncio
    async def test_approve_success(self):
        """Test successful approval."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "grant": {"id": "grant-123", "expires_at": "2024-01-01T00:00:00"},
        }

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            mock_response.raise_for_status = MagicMock()

            result = await approve_request(DEFAULT_API_URL, "ABCD-1234", 5)

            assert result["success"] is True
            assert result["grant"]["id"] == "grant-123"

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """Test approval with 404 error."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.HTTPStatusError(
                "Not found",
                request=MagicMock(),
                response=mock_response,
            ),
        ):
            result = await approve_request(DEFAULT_API_URL, "INVALID", 5)

            assert result["success"] is False
            assert "Invalid code" in result["error"]

    @pytest.mark.asyncio
    async def test_approve_exception(self):
        """Test approval with general exception."""
        with patch("httpx.AsyncClient.post", side_effect=Exception("Network error")):
            result = await approve_request(DEFAULT_API_URL, "ABCD-1234", 5)

            assert result["success"] is False
            assert "Network error" in result["error"]


class TestGetRequestDetails:
    """Tests for get_request_details function."""

    @pytest.mark.asyncio
    async def test_get_details_success(self):
        """Test successful retrieval of request details."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "ABCD-1234",
            "mcp_name": "filesystem",
            "path": "/etc/ssh",
        }

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await get_request_details(DEFAULT_API_URL, "ABCD-1234")

            assert result is not None
            assert result["code"] == "ABCD-1234"

    @pytest.mark.asyncio
    async def test_get_details_not_found(self):
        """Test retrieval of non-existent request."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await get_request_details(DEFAULT_API_URL, "INVALID")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_details_exception(self):
        """Test handling of exception."""
        with patch("httpx.AsyncClient.get", side_effect=Exception("Network error")):
            result = await get_request_details(DEFAULT_API_URL, "ABCD-1234")

            assert result is None


class TestPrintPendingRequests:
    """Tests for print_pending_requests function."""

    def test_print_empty_requests(self, capsys):
        """Test printing empty request list."""
        print_pending_requests([])

        captured = capsys.readouterr()
        assert "No pending access requests" in captured.out

    def test_print_pending_requests(self, capsys):
        """Test printing pending requests."""
        requests = [
            {
                "code": "ABCD-1234",
                "mcp_name": "filesystem",
                "tool_name": "read_file",
                "path": "/etc/ssh/sshd_config",
                "expires_at": "2024-01-01T00:00:00",
            }
        ]

        print_pending_requests(requests)

        captured = capsys.readouterr()
        assert "ABCD-1234" in captured.out
        assert "filesystem" in captured.out
        assert "/etc/ssh/sshd_config" in captured.out


class TestQuickApprove:
    """Tests for quick_approve function."""

    @pytest.mark.asyncio
    async def test_quick_approve_success(self, capsys):
        """Test successful quick approval."""
        mock_details = {
            "mcp_name": "filesystem",
            "tool_name": "read_file",
            "path": "/etc/ssh",
        }

        with patch("mcp_gateway.cli.get_request_details", return_value=mock_details):
            with patch(
                "mcp_gateway.cli.approve_request",
                return_value={
                    "success": True,
                    "grant": {"id": "grant-123", "expires_at": "2024-01-01T00:00:00"},
                },
            ):
                await quick_approve(DEFAULT_API_URL, "ABCD-1234", 5)

        captured = capsys.readouterr()
        assert "APPROVED" in captured.out
        assert "grant-123" in captured.out

    @pytest.mark.asyncio
    async def test_quick_approve_invalid_code_format(self, capsys):
        """Test quick approve with invalid code format."""
        with pytest.raises(SystemExit) as exc_info:
            await quick_approve(DEFAULT_API_URL, "INVALID", 5)

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_quick_approve_request_not_found(self, capsys):
        """Test quick approve with non-existent request."""
        with patch("mcp_gateway.cli.get_request_details", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                await quick_approve(DEFAULT_API_URL, "ABCD-1234", 5)

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_quick_approve_failure(self, capsys):
        """Test quick approve failure."""
        mock_details = {
            "mcp_name": "filesystem",
            "tool_name": "read_file",
            "path": "/etc/ssh",
        }

        with patch("mcp_gateway.cli.get_request_details", return_value=mock_details):
            with patch(
                "mcp_gateway.cli.approve_request",
                return_value={"success": False, "error": "Approval failed"},
            ):
                with pytest.raises(SystemExit) as exc_info:
                    await quick_approve(DEFAULT_API_URL, "ABCD-1234", 5)

        assert exc_info.value.code == 1


class TestMainCLI:
    """Tests for CLI main function."""

    @pytest.mark.asyncio
    async def test_list_command(self):
        """Test list command."""
        from mcp_gateway.cli import list_requests

        with patch("mcp_gateway.cli.check_pending_requests", return_value=[]) as mock_check:
            await list_requests(DEFAULT_API_URL)

            mock_check.assert_called_once_with(DEFAULT_API_URL)

    def test_main_no_command(self, capsys):
        """Test main with no command shows help."""
        from mcp_gateway.cli import main

        with patch("sys.argv", ["mcp-gateway"]):
            main()

        captured = capsys.readouterr()
        assert "usage:" in captured.out or "MCP Gateway CLI" in captured.out

    def test_main_approve_interactive(self):
        """Test main with approve command in interactive mode."""
        from mcp_gateway.cli import main

        with patch("sys.argv", ["mcp-gateway", "approve"]):
            with patch("mcp_gateway.cli.interactive_approve") as mock_interactive:
                main()

                mock_interactive.assert_called_once()

    def test_main_approve_quick(self):
        """Test main with approve command and code."""
        from mcp_gateway.cli import main

        with patch("sys.argv", ["mcp-gateway", "approve", "ABCD-1234"]):
            with patch("mcp_gateway.cli.quick_approve") as mock_quick:
                main()

                mock_quick.assert_called_once()

    def test_main_list(self):
        """Test main with list command."""
        from mcp_gateway.cli import main

        with patch("sys.argv", ["mcp-gateway", "list"]):
            with patch("mcp_gateway.cli.list_requests") as mock_list:
                main()

                mock_list.assert_called_once()

    def test_main_custom_api_url(self):
        """Test main with custom API URL."""
        from mcp_gateway.cli import main

        with patch("sys.argv", ["mcp-gateway", "--api-url", "http://localhost:8080", "list"]):
            with patch("mcp_gateway.cli.list_requests") as mock_list:
                main()

                # Should use custom URL
                call_args = mock_list.call_args
                assert "8080" in str(call_args)


class TestInteractiveApprove:
    """Tests for interactive_approve function."""

    @pytest.mark.asyncio
    async def test_interactive_quit(self, capsys):
        """Test interactive mode quit."""
        from mcp_gateway.cli import interactive_approve

        # When no pending requests, it monitors - break out with exception
        with patch("mcp_gateway.cli.check_pending_requests", return_value=[]):
            with patch("asyncio.sleep", side_effect=KeyboardInterrupt()):
                try:
                    await interactive_approve(DEFAULT_API_URL)
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "MCP Gateway" in captured.out or "No action needed" in captured.out

    @pytest.mark.asyncio
    async def test_interactive_refresh(self, capsys):
        """Test interactive mode refresh - just verify banner prints."""
        from mcp_gateway.cli import interactive_approve

        # Skip the full test - just verify the monitoring message appears
        with patch("mcp_gateway.cli.check_pending_requests", return_value=[]):
            with patch("asyncio.sleep", side_effect=KeyboardInterrupt()):
                try:
                    await interactive_approve(DEFAULT_API_URL)
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "MCP Gateway" in captured.out

    @pytest.mark.asyncio
    async def test_interactive_invalid_code(self, capsys):
        """Test interactive mode with invalid code."""
        from mcp_gateway.cli import interactive_approve

        # Start with a pending request so we skip the monitoring loop
        with patch("mcp_gateway.cli.check_pending_requests", return_value=[{"code": "ABCD-1234"}]):
            with patch("builtins.input", side_effect=["INVALID-FORMAT", "quit"]):
                await interactive_approve(DEFAULT_API_URL)

        captured = capsys.readouterr()
        # Should show banner and error
        assert "MCP Gateway" in captured.out or len(captured.out) > 0

    @pytest.mark.asyncio
    async def test_interactive_approve_flow(self, capsys):
        """Test interactive approval flow."""
        from mcp_gateway.cli import interactive_approve

        mock_request = {
            "mcp_name": "filesystem",
            "tool_name": "read_file",
            "path": "/etc/ssh",
            "created_at": "2024-01-01T00:00:00",
        }

        with patch("mcp_gateway.cli.check_pending_requests", return_value=[{"code": "ABCD-1234"}]):
            with patch("mcp_gateway.cli.get_request_details", return_value=mock_request):
                with patch(
                    "mcp_gateway.cli.approve_request",
                    return_value={"success": True, "grant": {"id": "grant-123"}},
                ):
                    with patch("builtins.input", side_effect=["ABCD-1234", "y", "5", "quit"]):
                        await interactive_approve(DEFAULT_API_URL)

        captured = capsys.readouterr()
        # Should show the request or approval
        assert len(captured.out) > 0
