#!/usr/bin/env python3
"""Simple MCP server for manual testing.

This script is NOT a pytest test - it's a helper for manual testing.
Run it directly: python tests/manual/test_simple.py
"""
import json
import sys

# Skip if run by pytest (prevents stdin issues during test collection)
if "pytest" in sys.modules:
    sys.exit(0)

print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "test", "version": "1.0.0"},
                "capabilities": {},
            },
        }
    ),
    flush=True,
)

for line in sys.stdin:
    req = json.loads(line)
    if req.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": []}}), flush=True)
