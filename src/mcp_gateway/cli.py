"""CLI commands for MCP Gateway.

Provides the 'mcp-gateway approve' command for interactive access approval.
"""

import argparse
import asyncio
import sys

import httpx

DEFAULT_API_URL = "http://127.0.0.1:3000"


async def check_pending_requests(api_url: str) -> list[dict]:
    """Get list of pending access requests."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/access/requests/pending", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("requests", [])
        except httpx.HTTPError as e:
            print(f"Error connecting to MCP Gateway: {e}")
            return []
        except Exception as e:
            print(f"Error: {e}")
            return []


async def check_pending_config_changes(api_url: str) -> list[dict]:
    """Get list of pending config change requests."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/config-changes/pending", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("requests", [])
        except httpx.HTTPError as e:
            print(f"Error connecting to MCP Gateway: {e}")
            return []
        except Exception as e:
            print(f"Error: {e}")
            return []


async def approve_request(api_url: str, code: str, duration: int) -> dict:
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


async def get_request_details(api_url: str, code: str) -> dict | None:
    """Get details of a specific access request."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/access/requests/{code}", timeout=10.0)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None


async def get_config_change_details(api_url: str, code: str) -> dict | None:
    """Get details of a specific config change request."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{api_url}/api/config-changes/pending", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                for req in data.get("requests", []):
                    if req.get("code") == code:
                        return req
            return None
        except Exception:
            return None


def print_banner():
    """Print the CLI banner."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║           MCP Gateway - Dynamic Access Control               ║
╚══════════════════════════════════════════════════════════════╝
""")


def print_pending_requests(requests: list[dict]):
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


def print_pending_config_changes(requests: list[dict]):
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


async def interactive_approve(api_url: str):
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


async def handle_access_approval(api_url: str, code: str, req: dict):
    """Handle approval of an access request."""
    # Show request details
    print(f"""
┌─────────────────────────────────────────────────────────────┐
│                    Access Request Details                   │
├─────────────────────────────────────────────────────────────┤
│  MCP Server:  {req.get('mcp_name', 'Unknown'):<40}│
│  Tool:        {req.get('tool_name', 'Unknown'):<40}│
│  Path:        {req.get('path', 'Unknown'):<40}│
│  Requested:   {req.get('created_at', 'Unknown'):<40}│
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

   Grant ID: {grant.get('id', 'N/A')}
   Expires:  {grant.get('expires_at', 'N/A')}

   The MCP server can now access the requested path.
   Access will be automatically revoked at expiration.
""")
    else:
        print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")


async def handle_config_change_approval(api_url: str, code: str, req: dict):
    """Handle approval of a config change request."""
    server_name = req.get('server_name', 'Unknown')
    change_type = req.get('change_type', 'Unknown')
    sensitive_paths = req.get('sensitive_paths', [])

    # Show request details
    paths_str = ", ".join(sensitive_paths) if sensitive_paths else "N/A"
    print(f"""
┌─────────────────────────────────────────────────────────────┐
│                 Config Change Request Details               │
├─────────────────────────────────────────────────────────────┤
│  Server:        {server_name:<40}│
│  Change Type:   {change_type:<40}│
│  Sensitive:     {paths_str:<40}│
│  Requested:     {req.get('created_at', 'Unknown'):<40}│
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

   Grant ID: {grant.get('id', 'N/A')}
   Server:   {grant.get('server_name', 'N/A')}
   Expires:  {grant.get('expires_at', 'N/A')}

   ⚠️  The config change is now ACTIVE.
   🔄 It will be automatically reverted at expiration.
""")
    else:
        print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")


async def quick_approve(api_url: str, code: str, duration: int = 1):
    """Quick approve with code provided as argument."""
    print_banner()

    # Validate code format
    code = code.upper().strip()
    if len(code) != 9 or code[4] != "-":
        print("❌ Invalid code format. Expected: XXXX-XXXX (e.g., ABCD-1234)")
        sys.exit(1)

    # Try to get request details (check access request first, then config change)
    req = await get_request_details(api_url, code)
    if req:
        # It's an access request
        print(f"""
┌─────────────────────────────────────────────────────────────┐
│                    Access Request Details                   │
├─────────────────────────────────────────────────────────────┤
│  MCP Server:  {req.get('mcp_name', 'Unknown'):<40}│
│  Tool:        {req.get('tool_name', 'Unknown'):<40}│
│  Path:        {req.get('path', 'Unknown'):<40}│
└─────────────────────────────────────────────────────────────┘
""")

        print(f"⏳ Approving for {duration} minute(s)...")
        result = await approve_request(api_url, code, duration)

        if result.get("success"):
            grant = result.get("grant", {})
            print(f"""
✅ APPROVED!

   Grant ID: {grant.get('id', 'N/A')}
   Expires:  {grant.get('expires_at', 'N/A')}

   The MCP server can now access the requested path.
""")
        else:
            print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)
    else:
        # Check if it's a config change request
        config_req = await get_config_change_details(api_url, code)
        if config_req:
            server_name = config_req.get('server_name', 'Unknown')
            sensitive_paths = config_req.get('sensitive_paths', [])
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

   Grant ID: {grant.get('id', 'N/A')}
   Server:   {grant.get('server_name', 'N/A')}
   Expires:  {grant.get('expires_at', 'N/A')}

   ⚠️  The config change is now ACTIVE.
   🔄 It will be automatically reverted at expiration.
""")
            else:
                print(f"\n❌ Approval failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)
        else:
            print(f"❌ Code '{code}' not found or expired.")
            sys.exit(1)


def main():
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
        "-d", "--duration",
        type=int,
        default=1,
        help="Duration in minutes (default: 1, max: 1440)",
    )

    # List command (reserved for future use)
    subparsers.add_parser(
        "list",
        help="List pending access requests",
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
    else:
        parser.print_help()


async def list_requests(api_url: str):
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


if __name__ == "__main__":
    main()
