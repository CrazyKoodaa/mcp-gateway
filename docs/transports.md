# MCP Transport Mechanisms

MCP supports multiple transport mechanisms for communication between clients and servers. Each transport has different characteristics and use cases.

## Available Transports

| Transport | Status | Use Case | Performance |
|-----------|--------|----------|-------------|
| **Streamable HTTP** | Current spec (2025-03-26+) | Remote servers, production | High |
| **STDIO** | Stable | Local CLI tools | Highest |
| **SSE** | Deprecated | Legacy systems | Medium |

---

## STDIO Transport

### Overview

STDIO is the default transport for local processes. It uses standard input/output streams for direct process communication.

### Characteristics

- **Best for**: Local MCP servers running as CLI tools
- **Performance**: Highest (no network overhead)
- **Security**: Process-isolated, no network exposure
- **Limitations**: Single client only, no authentication

### Implementation

```python
from mcp.client.stdio import StdioServerParameters, stdio_client

# Define server parameters
server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-memory"],
    env={**os.environ, "MY_VAR": "value"}
)

# Create client session
async with stdio_client(server_params) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        # Use session...
```

### Message Flow

```
┌──────────────┐     stdin      stdout      ┌──────────────┐
│   MCP Client │ ◄───────────► │──────────► │ MCP Server   │
│              │                 │          │  (npx/uvx)   │
└──────────────┘                 │          └──────────────┘
                                 │
                    JSON-RPC 2.0 messages on pipes
```

### Best Practices

1. **Use stderr for logging** - Never log to stdout/stdin as it interferes with transport
2. **Handle signals properly** - Catch SIGINT/SIGTERM for graceful shutdown
3. **Set proper environment** - Pass necessary env vars via `env` parameter
4. **Validate arguments** - Ensure command exists and is executable

### Error Handling Patterns

```python
import signal
import sys

def handle_signal(sig):
    logger.info(f"Received signal {sig}, shutting down...")
    server.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, lambda s, f: handle_signal(s))
signal.signal(signal.SIGTERM, lambda s, f: handle_signal(s))
```

---

## Streamable HTTP Transport

### Overview

Streamable HTTP is the current recommended transport for remote MCP servers. It combines HTTP POST for requests with optional SSE for streaming responses.

### Characteristics

- **Best for**: Remote MCP servers, production deployments
- **Performance**: High (HTTP/1.1 or HTTP/2)
- **Security**: Supports OAuth, Bearer tokens, API keys
- **Features**: Session management, resumability, CORS support

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/mcp` | POST | Client → Server messages |
| `/mcp` | GET | Server → Client SSE stream |
| `/mcp` | DELETE | Terminate session (optional) |
| `OPTIONS /mcp` | OPTIONS | CORS preflight |

### Request Pattern

All communication uses a single endpoint (`/mcp`). Requests use JSON-RPC 2.0 format:

```json
{
  "jsonrpc": "2.0",
  "id": "request-id",
  "method": "tools/call",
  "params": {
    "name": "my_tool",
    "arguments": {}
  }
}
```

### Required Headers

```http
Content-Type: application/json
Accept: application/json, text/event-stream
Mcp-Session-Id: <session-id>  # After initialization
Authorization: Bearer <token>  # If auth enabled
```

### Response Modes

1. **Batch Mode** (`responseMode: "batch"`)
   - Collects all responses into single JSON response
   - Suitable for simple request/response patterns

2. **Stream Mode** (`responseMode: "stream"`)
   - Opens SSE stream for progressive responses
   - Suitable for long-running operations

### Session Management

```javascript
// Session configuration
session: {
  enabled: true,                  // Default: true
  headerName: "Mcp-Session-Id",   // Default header name
  allowClientTermination: true    // Allow DELETE termination
}
```

**Lifecycle:**
1. Unique session ID generated during first `initialize` request
2. Returned in `Mcp-Session-Id` response header
3. Client must include this header in all subsequent requests
4. Can be terminated via DELETE method

### Resumability Feature

When enabled (`resumability.enabled: true`):
- Each SSE event gets a unique ID
- Clients reconnect using `Last-Event-ID` header
- Server replays missed messages since that event ID
- Message history kept for configurable duration (default: 5 minutes)

### Error Handling

Standard HTTP status codes with JSON-RPC error format:

| Status | Description |
|--------|-------------|
| 400 | Invalid JSON/message format |
| 401 | Authentication failure |
| 404 | Invalid session ID |
| 405 | Unsupported HTTP method |
| 406 | Missing Accept header |
| 413 | Payload too large |
| 429 | Rate limit exceeded |

### Implementation Example

```python
import httpx
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    url="https://api.example.com/mcp",
    headers={"Authorization": "Bearer token"}
) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        # Use session...
```

---

## SSE Transport (Deprecated)

### Overview

SSE (Server-Sent Events) transport is deprecated as of MCP specification version 2025-03-26. It uses separate endpoints for client→server and server→client communication.

### Characteristics

- **Status**: Deprecated (migration recommended)
- **Endpoints**: Separate `/sse` (stream) and `/messages` (POST)
- **Best for**: Legacy systems already using SSE

### Endpoints

| Component | Default Path | Description |
|-----------|--------------|-------------|
| SSE Connection | `/sse` | Server-to-client streaming |
| Message Endpoint | `/messages` | Client-to-server POST |

### Event Formats

**SSE Events:**
- `endpoint`: Contains full message endpoint URL with session ID
- `message`: Contains JSON-RPC responses

**Keep-alive:** Sends ping messages every 15 seconds

### Limitations vs HTTP Stream

| Feature | SSE | HTTP Stream |
|---------|-----|-------------|
| Bidirectional | Separate endpoints | Single endpoint |
| Session Header | Query params | Headers |
| Resumability | Limited | Built-in |
| Termination | Not supported | DELETE method |
| CORS | Basic | Comprehensive |

---

## Comparison Summary

### Performance

| Transport | Latency | Throughput | Network Overhead |
|-----------|---------|------------|------------------|
| STDIO | Lowest | Highest | None |
| Streamable HTTP | Low | High | HTTP headers |
| SSE | Medium | Medium | HTTP + SSE overhead |

### Security

| Transport | Authentication | Authorization | Isolation |
|-----------|---------------|---------------|-----------|
| STDIO | Process-level | N/A | Complete |
| Streamable HTTP | Bearer/API key | Token-based | Network |
| SSE | Bearer/API key | Token-based | Network |

### Use Case Recommendations

| Scenario | Recommended Transport |
|----------|----------------------|
| Local CLI tools | STDIO |
| Remote production server | Streamable HTTP |
| Browser-based clients | Streamable HTTP |
| Legacy systems | SSE (migrate when possible) |
| High-security environments | STDIO or authenticated HTTP |

---

## References

- [MCP Transports Documentation](https://mcp-framework.com/docs/Transports/)
- [STDIO Transport Guide](https://mcp-framework.com/docs/Transports/stdio-transport/)
- [HTTP Stream Transport Guide](https://mcp-framework.com/docs/Transports/http-stream-transport/)
- [SSE Transport Guide](https://mcp-framework.com/docs/Transports/sse/)
