"""CLI commands for MCP Gateway.

Provides the 'mcp-gateway approve' command for interactive access approval.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:3000"


async def check_pending_requests(api_url: str) -> list[dict[str, Any]]:
    """Get list of pending access requests."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/access/requests/pending", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("requests", [])  # type: ignore[return-value]
        except httpx.HTTPError as e:
            print(f"Error connecting to MCP Gateway: {e}")
            return []
        except Exception as e:
            print(f"Error: {e}")
            return []


async def check_pending_config_changes(api_url: str) -> list[dict[str, Any]]:
    """Get list of pending config change requests."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/config-changes/pending", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("requests", [])  # type: ignore[return-value]
        except httpx.HTTPError as e:
            print(f"Error connecting to MCP Gateway: {e}")
            return []
        except Exception as e:
            print(f"Error: {e}")
            return []


async def approve_request(api_url: str, code: str, duration: int) -> dict[str, Any]:
    """Approve an access request by code."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{api_url}/api/access/requests/{code}/approve",
                json={"duration_minutes": duration, "approved_by": "cli"},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"success": False, "error": f"Invalid code: {code}"}
            return {"success": False, "error": f"Server error: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def approve_config_change(api_url: str, code: str, duration: int) -> dict:
    """Approve a config change request by code."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{api_url}/api/config-changes/{code}/approve",
                json={"duration_minutes": duration, "approved_by": "cli"},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"success": False, "error": f"Invalid code: {code}"}
            return {"success": False, "error": f"Server error: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def get_request_details(api_url: str, code: str) -> dict[str, Any] | None:
    """Get details of a specific access request."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/access/requests/{code}", timeout=10.0)
            if response.status_code == 200:
                return response.json()  # type: ignore[return-value]
            return None
        except httpx.RequestError:
            return None
        except Exception:
            return None


async def get_config_change_details(api_url: str, code: str) -> dict[str, Any] | None:
    """Get details of a specific config change request."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/config-changes/pending", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                for req in data.get("requests", []):
                    if req.get("code") == code:
                        return req  # type: ignore[return-value]
            return None
        except httpx.RequestError:
            return None


def print_banner() -> None:
    """Print the CLI banner."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           MCP Gateway - Dynamic Access Control               ║
╚══════════════════════════════════════════════════════════════╝
""")


def print_pending_requests(requests: list[dict[str, Any]]) -> None:
    """Print pending access requests in a formatted way."""
    if not requests:
        print("📭 No pending access requests.")
        return

    print(f"📋 {len(requests)} pending access request(s):\n")
    print("─" * 60)

    for req in requests:
        code = req.get("code", "UNKNOWN")
        mcp = req.get("mcp_name", "Unknown")
        tool = req.get("tool_name", "Unknown")
        path = req.get("path", "Unknown")
        expires = req.get("expires_at", "Unknown")

        print(f"""
🔐 Code: {code}
   MCP:  {mcp}
   Tool: {tool}
   Path: {path}
   Expires: {expires}
""")
    print("─" * 60)


def print_pending_config_changes(requests: list[dict[str, Any]]) -> None:
    """Print pending config change requests in a formatted way."""
    if not requests:
        print("📭 No pending config change requests.")
        return

    print(f"⚙️  {len(requests)} pending config change request(s):\n")
    print("─" * 60)

    for req in requests:
        code = req.get("code", "UNKNOWN")
        server = req.get("server_name", "Unknown")
        change_type = req.get("change_type", "Unknown")
        paths = req.get("sensitive_paths", [])
        expires = req.get("expires_at", "Unknown")

        paths_str = ", ".join(paths) if paths else "N/A"

        print(f"""
⚠️  Code: {code}
   Server: {server}
   Change: {change_type}
   Sensitive Paths: {paths_str}
   Expires: {expires}
""")
    print("─" * 60)


async def interactive_approve(api_url: str) -> None:
    """Interactive approval workflow for both access and config change requests."""
    print_banner()

    # Show pending requests (both types)
    access_requests = await check_pending_requests(api_url)
    config_requests = await check_pending_config_changes(api_url)

    has_pending = access_requests or config_requests

    if access_requests:
        print_pending_requests(access_requests)

    if config_requests:
        print_pending_config_changes(config_requests)

    if not has_pending:
        print("\n✨ No action needed. Monitoring for new requests...")
        print("   (Press Ctrl+C to exit)\n")

        # Monitor for new requests
        while True:
            await asyncio.sleep(2)
            new_access = await check_pending_requests(api_url)
            new_config = await check_pending_config_changes(api_url)
            if new_access or new_config:
                if new_access:
                    print("\n🔔 New access request detected!\n")
                    print_pending_requests(new_access)
                if new_config:
                    print("\n🔔 New config change request detected!\n")
                    print_pending_config_changes(new_config)
                break

    # Interactive approval loop
    while True:
        print("\nEnter approval code (or 'refresh' to check for new requests, 'quit' to exit):")
        try:
            user_input = input("> ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 Goodbye!")
            return

        if user_input in ("QUIT", "Q", "EXIT"):
            print("\n👋 Goodbye!")
            return

        if user_input in ("REFRESH", "R"):
            access_requests = await check_pending_requests(api_url)
            config_requests = await check_pending_config_changes(api_url)
            if access_requests:
                print_pending_requests(access_requests)
            if config_requests:
                print_pending_config_changes(config_requests)
            if not access_requests and not config_requests:
                print("📭 No pending requests.")
            continue

        # Validate code format (ABCD-1234)
        if len(user_input) != 9 or user_input[4] != "-":
            print("❌ Invalid code format. Expected: XXXX-XXXX (e.g., ABCD-1234)")
            continue

        # Try to get request details (check both types)
        access_req = await get_request_details(api_url, user_input)
        config_req = None
        if not access_req:
            config_req = await get_config_change_details(api_url, user_input)

        if access_req:
            await handle_access_approval(api_url, user_input, access_req)
        elif config_req:
            await handle_config_change_approval(api_url, user_input, config_req)
        else:
            print(f"❌ Code '{user_input}' not found or expired.")


async def handle_access_approval(api_url: str, code: str, req: dict[str, Any]) -> None:
    """Handle approval of an access request."""
    # Show request details
    print(f"""
┌─────────────────────────────────────────────────────────────┐
│                    Access Request Details                   │
├─────────────────────────────────────────────────────────────┤
│  MCP Server:  {req.get("mcp_name", "Unknown"):<40}│
│  Tool:        {req.get("tool_name", "Unknown"):<40}│
│  Path:        {req.get("path", "Unknown"):<40}│
│  Requested:   {req.get("created_at", "Unknown"):<40}│
└─────────────────────────────────────────────────────────────┘
""")

    # Ask for approval
    print("Approve this request? [y/n]: ", end="")
    try:
        approval = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        return

    if approval not in ("y", "yes"):
        print("❌ Request denied.")
        return

    # Ask for duration
    print("\nDuration (minutes) [default: 1]: ", end="")
    try:
        duration_input = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        return

    try:
        duration = int(duration_input) if duration_input else 1
        if duration < 1:
            duration = 1
        if duration > 1440:  # Max 24 hours
            duration = 1440
    except ValueError:
        duration = 1

    # Approve the request
    print(f"\n⏳ Approving for {duration} minute(s)...")
    result = await approve_request(api_url, code, duration)

    if result.get("success"):
        grant = result.get("grant", {})
        print(f"""
✅ APPROVED!

   Grant ID: {grant.get("id", "N/A")}
   Expires:  {grant.get("expires_at", "N/A")}

   The MCP server can now access the requested path.
   Access will be automatically revoked at expiration.
""")
    else:
        print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")


async def handle_config_change_approval(api_url: str, code: str, req: dict[str, Any]) -> None:
    """Handle approval of a config change request."""
    server_name = req.get("server_name", "Unknown")
    change_type = req.get("change_type", "Unknown")
    sensitive_paths = req.get("sensitive_paths", [])  # type: ignore[assignment]

    # Show request details
    paths_str = ", ".join(sensitive_paths) if sensitive_paths else "N/A"
    print(f"""
┌─────────────────────────────────────────────────────────────┐
│                 Config Change Request Details               │
├─────────────────────────────────────────────────────────────┤
│  Server:        {server_name:<40}│
│  Change Type:   {change_type:<40}│
│  Sensitive:     {paths_str:<40}│
│  Requested:     {req.get("created_at", "Unknown"):<40}│
└─────────────────────────────────────────────────────────────┘
""")

    print("⚠️  WARNING: Approving will allow temporary access to sensitive paths.")
    print("   The config will be automatically reverted after the grant expires.\n")

    # Ask for approval
    print("Approve this config change? [y/n]: ", end="")
    try:
        approval = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        return

    if approval not in ("y", "yes"):
        print("❌ Config change denied.")
        return

    # Ask for duration
    print("\nDuration (minutes) [default: 1]: ", end="")
    try:
        duration_input = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        return

    try:
        duration = int(duration_input) if duration_input else 1
        if duration < 1:
            duration = 1
        if duration > 1440:  # Max 24 hours
            duration = 1440
    except ValueError:
        duration = 1

    # Approve the config change
    print(f"\n⏳ Approving config change for {duration} minute(s)...")
    result = await approve_config_change(api_url, code, duration)

    if result.get("success"):
        grant = result.get("grant", {})
        print(f"""
✅ CONFIG CHANGE APPROVED!

   Grant ID: {grant.get("id", "N/A")}
   Server:   {grant.get("server_name", "N/A")}
   Expires:  {grant.get("expires_at", "N/A")}

   ⚠️  The config change is now ACTIVE.
   🔄 It will be automatically reverted at expiration.
""")
    else:
        print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")


async def quick_approve(api_url: str, code: str, duration: int = 1) -> None:
    """Quick approve with code provided as argument."""
    print_banner()

    # Validate code format
    code = code.upper().strip()
    if len(code) != 9 or code[4] != "-":
        print("❌ Invalid code format. Expected: XXXX-XXXX (e.g., ABCD-1234)")
        sys.exit(1)

    # Try to get request details (check access request first, then config change)
    req = await get_request_details(api_url, code)
    if req is not None:
        # It's an access request
        print(f"""
┌─────────────────────────────────────────────────────────────┐
│                    Access Request Details                   │
├─────────────────────────────────────────────────────────────┤
│  MCP Server:  {req.get("mcp_name", "Unknown"):<40}│
│  Tool:        {req.get("tool_name", "Unknown"):<40}│
│  Path:        {req.get("path", "Unknown"):<40}│
└─────────────────────────────────────────────────────────────┘
""")

        print(f"⏳ Approving for {duration} minute(s)...")
        result = await approve_request(api_url, code, duration)

        if result.get("success"):
            grant = result.get("grant", {})
            print(f"""
✅ APPROVED!

   Grant ID: {grant.get("id", "N/A")}
   Expires:  {grant.get("expires_at", "N/A")}

   The MCP server can now access the requested path.
""")
        else:
            print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)
    else:
        # Check if it's a config change request
        config_req = await get_config_change_details(api_url, code)
        if config_req is not None:
            server_name = config_req.get("server_name", "Unknown")
            sensitive_paths = config_req.get("sensitive_paths", [])
            paths_str = ", ".join(sensitive_paths) if sensitive_paths else "N/A"

            print(f"""
┌─────────────────────────────────────────────────────────────┐
│                 Config Change Request Details               │
├─────────────────────────────────────────────────────────────┤
│  Server:        {server_name:<40}│
│  Sensitive:     {paths_str:<40}│
└─────────────────────────────────────────────────────────────┘
""")

            print(f"⏳ Approving config change for {duration} minute(s)...")
            result = await approve_config_change(api_url, code, duration)

            if result.get("success"):
                grant = result.get("grant", {})
                print(f"""
✅ CONFIG CHANGE APPROVED!

   Grant ID: {grant.get("id", "N/A")}
   Server:   {grant.get("server_name", "N/A")}
   Expires:  {grant.get("expires_at", "N/A")}

   ⚠️  The config change is now ACTIVE.
   🔄 It will be automatically reverted at expiration.
""")
            else:
                print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)
        else:
            print(f"❌ Code '{code}' not found or expired.")
            sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mcp-gateway",
        description="MCP Gateway CLI - Manage dynamic path access control",
    )

    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"MCP Gateway API URL (default: {DEFAULT_API_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Approve command
    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve pending access requests",
    )
    approve_parser.add_argument(
        "code",
        nargs="?",
        help="Approval code (e.g., ABCD-1234). If not provided, enters interactive mode.",
    )
    approve_parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=1,
        help="Duration in minutes (default: 1, max: 1440)",
    )

    # List command (reserved for future use)
    subparsers.add_parser(
        "list",
        help="List pending access requests",
    )

    # Status command - show backend status
    status_parser = subparsers.add_parser(
        "status",
        help="Show backend connection status and diagnostics",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    # Diagnose command - detailed diagnostics
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Run diagnostic check on all backends",
    )
    diagnose_parser.add_argument(
        "backend",
        nargs="?",
        help="Specific backend to diagnose (optional)",
    )

    args = parser.parse_args()

    if args.command == "approve":
        if args.code:
            # Quick approve with provided code
            asyncio.run(quick_approve(args.api_url, args.code, args.duration))
        else:
            # Interactive mode
            asyncio.run(interactive_approve(args.api_url))
    elif args.command == "list":
        asyncio.run(list_requests(args.api_url))
    elif args.command == "status":
        asyncio.run(show_status(args.api_url, args.json))
    elif args.command == "diagnose":
        asyncio.run(run_diagnose(args.api_url, args.backend))
    else:
        parser.print_help()


async def list_requests(api_url: str) -> None:
    """List all pending requests (both access and config change)."""
    print_banner()

    access_pending = await check_pending_requests(api_url)
    config_pending = await check_pending_config_changes(api_url)

    if access_pending:
        print_pending_requests(access_pending)

    if config_pending:
        print_pending_config_changes(config_pending)

    if not access_pending and not config_pending:
        print("📭 No pending requests.")


async def get_health_status(api_url: str) -> dict[str, Any] | None:
    """Get health status from the gateway."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/health", timeout=10.0)
            response.raise_for_status()
            return response.json()  # type: ignore[return-value]
        except httpx.HTTPError as e:
            print(f"❌ Error connecting to MCP Gateway: {e}")
            return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None


async def get_servers_status(api_url: str) -> list[dict[str, Any]]:
    """Get server list with connection status."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/servers", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("servers", [])  # type: ignore[return-value]
        except Exception:
            return []


def print_status_table(health: dict[str, Any], servers: list[dict[str, Any]]) -> None:
    """Print backend status in a formatted table."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MCP Gateway - Backend Status                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

    # Gateway status
    status = health.get("status", "unknown")
    healthy = health.get("healthy", False)
    total = health.get("total_backends", 0)
    connected = health.get("connected_backends", 0)
    failed = health.get("failed_backends", 0)

    status_icon = "✅" if healthy else "⚠️"
    print(f"{status_icon} Gateway Status: {status.upper()}")
    print(f"   Backends: {connected}/{total} connected", end="")
    if failed > 0:
        print(f" ({failed} failed)")
    else:
        print()
    print()

    # Backends table
    backends = health.get("backends", [])
    if not backends:
        print("📭 No backends configured.")
        return

    # Header
    print("─" * 80)
    print(f"{'Backend':<20} {'Status':<12} {'Tools':<8} {'Type':<10} {'Error':<25}")
    print("─" * 80)

    for backend in backends:
        name = backend.get("name", "Unknown")
        is_connected = backend.get("connected", False)
        tools = backend.get("tools", 0)
        backend_type = backend.get("type", "unknown")

        if is_connected:
            status_str = "✅ OK"
            error_str = "-"
        else:
            status_str = "❌ ERROR"
            diagnostic = backend.get("diagnostic", {})
            error_msg = diagnostic.get("error_message", "Connection failed")
            error_str = error_msg[:24] if error_msg else "Unknown error"

        print(f"{name:<20} {status_str:<12} {tools:<8} {backend_type:<10} {error_str:<25}")

    print("─" * 80)
    print()

    # Show fix tips for failed backends
    failed_backends = [b for b in backends if not b.get("connected", False)]
    if failed_backends:
        print("💡 FIX TIPS:")
        print()
        for backend in failed_backends:
            name = backend.get("name", "Unknown")
            diagnostic = backend.get("diagnostic", {})
            fix_tip = diagnostic.get("fix_tip", "Check server configuration")
            print(f"   {name}:")
            print(f"      → {fix_tip}")
            print()


async def show_status(api_url: str, json_output: bool = False) -> None:
    """Show backend status."""
    health = await get_health_status(api_url)

    if health is None:
        sys.exit(1)

    if json_output:
        import json

        print(json.dumps(health, indent=2))
        return

    servers = await get_servers_status(api_url)
    print_status_table(health, servers)


def print_diagnostic_detail(backend: dict[str, Any]) -> None:
    """Print detailed diagnostic information for a backend."""
    name = backend.get("name", "Unknown")
    is_connected = backend.get("connected", False)
    backend_type = backend.get("type", "unknown")
    tools = backend.get("tools", 0)

    print(f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  Backend: {name:<64}│
├─────────────────────────────────────────────────────────────────────────────┤
│  Status:      {"✅ CONNECTED" if is_connected else "❌ DISCONNECTED":<58}│
│  Type:        {backend_type:<58}│
│  Tools:       {tools:<58}│
└─────────────────────────────────────────────────────────────────────────────┘""")

    if not is_connected:
        diagnostic = backend.get("diagnostic", {})
        error_msg = diagnostic.get("error_message", "Unknown error")
        fix_tip = diagnostic.get("fix_tip", "Check server configuration")
        attempts = diagnostic.get("connection_attempts", 0)
        last_attempt = diagnostic.get("last_attempt")

        print(f"""
⚠️  DIAGNOSTIC INFORMATION:

   Error Message:
      {error_msg}

   Suggested Fix:
      💡 {fix_tip}

   Connection Attempts: {attempts}
   Last Attempt: {last_attempt if last_attempt else "Never"}

🔧 ACTIONABLE STEPS:
   1. Check the server configuration in your config.json
   2. Verify environment variables are set correctly
   3. Ensure the backend service is running and accessible
   4. Use 'mcp-gateway edit {name}' to modify configuration
   5. Restart the gateway after making changes
""")


async def run_diagnose(api_url: str, backend_name: str | None = None) -> None:
    """Run diagnostic check on backends."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MCP Gateway - Diagnostic Tool                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

    health = await get_health_status(api_url)

    if health is None:
        print("❌ Failed to connect to MCP Gateway.")
        print("   Make sure the gateway is running on the specified URL.")
        sys.exit(1)

    backends = health.get("backends", [])

    if not backends:
        print("📭 No backends configured.")
        return

    if backend_name:
        # Diagnose specific backend
        backend = next((b for b in backends if b.get("name") == backend_name), None)
        if backend:
            print_diagnostic_detail(backend)
        else:
            print(f"❌ Backend '{backend_name}' not found.")
            print(f"   Available backends: {', '.join(b.get('name') for b in backends)}")
            sys.exit(1)
    else:
        # Diagnose all backends
        failed_backends = [b for b in backends if not b.get("connected", False)]

        if not failed_backends:
            print("✅ All backends are connected and healthy!")
            print()
            print("Backend Summary:")
            for backend in backends:
                name = backend.get("name", "Unknown")
                tools = backend.get("tools", 0)
                print(f"   ✅ {name}: {tools} tools available")
            return

        print(f"Found {len(failed_backends)} backend(s) with issues:\n")

        for backend in failed_backends:
            print_diagnostic_detail(backend)
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
