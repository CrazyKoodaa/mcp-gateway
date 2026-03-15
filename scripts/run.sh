#!/bin/bash
# Simple run script for MCP Gateway

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add src to Python path
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

# Run the gateway
exec python3 -m mcp_gateway "$@"
