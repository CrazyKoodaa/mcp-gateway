#!/usr/bin/env python3
import sys
import json

print(json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "test", "version": "1.0.0"},
        "capabilities": {}
    }
}), flush=True)

for line in sys.stdin:
    req = json.loads(line)
    if req.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": []}}), flush=True)
