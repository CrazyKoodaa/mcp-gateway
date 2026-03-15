# Model Context Protocol (MCP) Overview

## Architecture

### Participants

| Component | Description |
|-----------|-------------|
| **MCP Host** | AI application (e.g., Claude Code, VS Code) that coordinates clients |
| **MCP Client** | Maintains connection to servers, obtains context for host |
| **MCP Server** | Program providing tools, resources, prompts to clients |

Each host creates one dedicated client per server. Local servers typically serve a single client; remote servers can serve many clients.

### Layered Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Data Layer                          │
│     JSON-RPC 2.0 based protocol (inner layer)       │
│                                                     │
│  • Lifecycle Management                             │
│  • Server Primitives: Tools, Resources, Prompts    │
│  • Client Primitives: Sampling, Elicitation        │
│  • Notifications, Progress Tracking                │
├─────────────────────────────────────────────────────┤
│                 Transport Layer                     │
│     Communication mechanisms (outer layer)          │
│                                                     │
│  • STDIO                                            │
│  • Streamable HTTP                                  │
│  • SSE (deprecated as of 2025-03-26)               │
└─────────────────────────────────────────────────────┘
```

## JSON-RPC 2.0 Protocol

### Request Format

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "method": "<method-name>",
  "params": { ... }
}
```

- **Request**: Contains `id` field for correlation
- **Notification**: No `id` field; no response expected

### Response Format

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "result": { ... }
}
```

### Error Format

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "error": {
    "code": <error-code>,
    "message": "<error-message>",
    "data": { ... }
  }
}
```

### Common Error Codes

| Code | Description |
|------|-------------|
| -32700 | Parse error - Invalid JSON |
| -32600 | Invalid Request - Method doesn't exist |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
| -32000 to -32099 | Server error range |

## Session Lifecycle

### 1. Initialize Request (Client → Server)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {
      "tools": {},
      "resources": {}
    },
    "clientInfo": {
      "name": "mcp-gateway",
      "version": "0.1.0"
    }
  }
}
```

### 2. Initialize Response (Server → Client)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {
      "tools": { "listChanged": true },
      "resources": { "subscribe": true }
    },
    "serverInfo": {
      "name": "mcp-gateway",
      "version": "0.1.0"
    }
  }
}
```

### 3. Initialized Notification (Client → Server)

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

### 4. Tool Discovery and Usage

#### List Tools

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

#### Call Tool

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "filesystem__read_file",
    "arguments": {
      "path": "/home/user/file.txt"
    }
  }
}
```

### 5. Termination

Client or server can terminate connection when complete.

## Primitives

### Server-to-Client Primitives

| Primitive | Methods | Description |
|-----------|---------|-------------|
| **Tools** | `tools/list`, `tools/call` | Executable functions for AI actions |
| **Resources** | `resources/list`, `resources/read` | Data sources for context |
| **Prompts** | `prompts/list`, `prompts/get` | Interaction templates |

### Client-to-Server Primitives

| Primitive | Method | Description |
|-----------|--------|-------------|
| **Sampling** | `sampling/complete` | Request LLM completions from host |
| **Elicitation** | `elicitation/request` | Request additional user information |
| **Logging** | `logging/message` | Send log messages to client |

## Notifications

Real-time event-driven updates without requiring responses:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/tools/list_changed"
}
```

**Key Features:**
- No `id` field (no response expected)
- Capability-based (only sent if feature declared during initialization)
- Enables dynamic synchronization

---

## References

- [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
