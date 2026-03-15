# MCP Gateway

> **One endpoint. All your MCP tools.**

A production-ready gateway that aggregates multiple MCP (Model Context Protocol) servers into a single endpoint. Supports local stdio servers (npx, uvx), remote HTTP/SSE servers, and everything in between.

```
┌─────────────────┐      ┌──────────────────────────────┐      ┌─────────────────┐
│  llama.cpp      │ MCP  │      MCP Gateway             │stdio │  MCP Servers    │
│    webui        │◄────►│  (ONE port: 3000)            │◄────►│ • memory        │
│  Claude Desktop │HTTP  │                              │      │ • time          │
│  Cursor         │      │ • StreamableHTTP primary     │HTTP  │ • filesystem    │
│  Any MCP client │      │ • SSE fallback               │◄────►│ • fetch         │
└─────────────────┘      │ • Smart transport switching  │      │ • github        │
                         └──────────────────────────────┘      └─────────────────┘
```

## 🎯 Why This Project Exists

### The Problem

MCP servers are powerful but managing them is painful:

1. **Too many ports** - Each stdio→HTTP proxy needs its own port
   ```
   memory:3001, time:3002, filesystem:3003, fetch:3004...
   ```

2. **Tool name collisions** - Multiple servers expose `read`, `write`, `search`...

3. **Mixed transports** - Some servers use stdio, others use HTTP/SSE

4. **No filtering** - Can't disable specific tools per server

5. **Protocol confusion** - Some gateways speak OpenAPI (not MCP), breaking compatibility

### Existing "Solutions" and Why They Fall Short

| Solution | Single Port | stdio | Remote HTTP | MCP Protocol | Tool Filter | Notes |
|----------|-------------|-------|-------------|--------------|-------------|-------|
| **supergateway** | ❌ No | ✅ Yes | ❌ No | ✅ Yes | ❌ No | One port per server |
| **lunfengchen/gateway-mcp** | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes | ❌ No | Uses stdio transport, not HTTP |
| **mcpo** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ **NO** | ✅ Yes | Speaks **OpenAPI**, not MCP! Breaks MCP clients |
| **MCP Aggregator (dwillitzer)** | ❓ | ❓ | ❓ | ✅ Yes | ❓ | Very new, unproven |
| **mcp-gateway (this)** | ✅ **Yes** | ✅ **Yes** | ✅ **Yes** | ✅ **Yes** | ✅ **Yes** | Does it all |

### The Breaking Point

**mcpo** (the most popular option) exposes your MCP servers as **OpenAPI REST endpoints**. Sounds good, but:
- ❌ llama.cpp webui speaks **MCP protocol**, not OpenAPI
- ❌ Claude Desktop speaks **MCP protocol**, not OpenAPI
- ❌ Cursor speaks **MCP protocol**, not OpenAPI

**Result**: mcpo is incompatible with standard MCP clients.

## ✨ What Makes mcp-gateway Different

### 1. **Instant Config Changes — No Restart Required**

Edit servers in the **Admin Dashboard** (`/admin`) and changes are **live immediately**:

```bash
# Start with hot reload enabled
mcp-gateway --hot-reload

# Or edit via the web UI — changes apply instantly
# No restart, no downtime, no lost connections
```

Add a new MCP server, disable a tool, or change timeouts — all without restarting the gateway.

### 2. **Security-First Path Approval**

Sensitive filesystem operations require **explicit CLI approval** with **time-limited grants**:

```bash
# Default: 1 minute access
mcp-gateway approve ABC-1234

# Grant 30 minutes of access
mcp-gateway approve ABC-1234 -d 30

# Or use interactive mode to review and approve
mcp-gateway approve
```

When a tool tries to access `/etc`, `/home`, or other sensitive paths, the request is **blocked until approved**. Access automatically **expires** after the granted duration — no lingering permissions.

### 3. **True MCP Protocol**

Unlike mcpo, we speak **MCP natively**:
- ✅ StreamableHTTP (`POST /mcp`) - modern, efficient
- ✅ SSE (`GET /sse`) - legacy fallback
- ✅ Full JSON-RPC implementation
- ✅ Compatible with **all** MCP clients

### 4. **One Port to Rule Them All**

```bash
# Before (with supergateway):
http://localhost:3001/sse  # memory
http://localhost:3002/sse  # time
http://localhost:3003/sse  # filesystem
http://localhost:3004/sse  # fetch

# After (with mcp-gateway):
http://localhost:3000/mcp  # ALL tools in one place
```

### 5. **Automatic Tool Namespacing**

No more collisions:
- `memory` server's `add` → `memory__add`
- `time` server's `get_current_time` → `time__get_current_time`
- `filesystem` server's `read_file` → `filesystem__read_file`

### 6. **Universal Backend Support**

Mix and match any transport:

```json
{
  "mcpServers": {
    // Local stdio servers
    "memory": {
      "command": "npx -y @modelcontextprotocol/server-memory"
    },
    
    // Remote StreamableHTTP servers
    "github": {
      "type": "streamable-http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {"Authorization": "Bearer token"}
    },
    
    // Remote SSE servers
    "custom-api": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

### 7. **Smart Transport Selection**

Like llama.cpp webui, we use the modern **StreamableHTTP** first, with automatic **SSE fallback**:

```
Client connects to /mcp
    ↓
Try StreamableHTTP (efficient, stateless)
    ↓
If that fails → Auto-fallback to SSE
    ↓
Client gets tools from ALL backends
```

### 8. **Tool Filtering**

Disable problematic tools per server:

```json
{
  "time": {
    "command": "uvx mcp-server-time",
    "disabledTools": ["convert_time"]
  }
}
```

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway

# Install (Python 3.11+)
pip install -e .

# Or with uv
uv pip install -e .
```

### Configuration

Create `config.json`:

```json
{
  "gateway": {
    "host": "127.0.0.1",
    "port": 3000,
    "logLevel": "INFO"
  },
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    },
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone=Europe/Berlin"],
      "disabledTools": ["convert_time"]
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/home/user/projects",
        "/home/user/documents"
      ]
    }
  }
}
```

### Run

```bash
# Simple
python -m mcp-gateway

# With custom config
python -m mcp-gateway --config /path/to/config.json

# With overrides
python -m mcp-gateway --host 0.0.0.0 --port 8080 --log-level DEBUG
```

### Connect Your Client

**llama.cpp webui:**
```json
[
  {
    "id": "gateway",
    "enabled": true,
    "url": "http://localhost:3000/mcp",
    "useProxy": false
  }
]
```

**Claude Desktop:**
```json
{
  "mcpServers": {
    "gateway": {
      "type": "sse",
      "url": "http://localhost:3000/sse"
    }
  }
}
```

**Cursor:**
```json
{
  "mcpServers": {
    "gateway": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

## 📖 Configuration Reference

### Stdio Server

**Three formats supported** - use whichever is most readable:

#### Format 1: Separate `command` and `args` (Recommended for complex configs)

```json
{
  "time": {
    "command": "uvx",
    "args": ["mcp-server-time", "--local-timezone=Europe/Berlin"],
    "disabledTools": ["convert_time"]
  }
}
```

Best when you need additional options like `disabledTools` or `env`.

#### Format 2: One-liner (Auto-parsed, great for simple commands)

```json
{
  "filesystem": {
    "command": "npx -y @modelcontextprotocol/server-filesystem /home/user/projects /home/user/docs"
  }
}
```

The gateway automatically splits the command by spaces (respecting quotes). This is parsed as:
- `command`: `npx`
- `args`: `["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects", "/home/user/docs"]`

#### Format 3: Args as string

```json
{
  "fetch": {
    "command": "uvx",
    "args": "mcp-server-fetch --timeout 30"
  }
}
```

String args are automatically split into an array.

#### Full options

```json
{
  "name": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
    "env": {"KEY": "value"},
    "disabledTools": ["tool_name"]
  }
}
```

### Remote StreamableHTTP Server

```json
{
  "name": {
    "type": "streamable-http",
    "url": "https://api.example.com/mcp",
    "headers": {
      "Authorization": "Bearer token"
    }
  }
}
```

### Remote SSE Server

```json
{
  "name": {
    "type": "sse",
    "url": "http://localhost:8001/sse"
  }
}
```

## 🔧 Advanced Features

### Authentication

Protect your gateway with API key or Bearer token authentication:

```json
{
  "gateway": {
    "apiKey": "your-secure-api-key",
    "bearerToken": "your-secure-bearer-token",
    "authExcludePaths": ["/health", "/metrics"]
  }
}
```

Use in requests:
```bash
curl -H "X-API-Key: your-secure-api-key" http://localhost:3000/mcp
# or
curl -H "Authorization: Bearer your-secure-bearer-token" http://localhost:3000/mcp
```

### Hot Reload

Reload configuration without restarting:

```bash
# Enable file watching (uses watchdog if available)
mcp-gateway --hot-reload

# Use polling instead (for network filesystems)
mcp-gateway --hot-reload --poll
```

Edit `config.json` and changes are applied automatically.

### Process Supervision

Auto-restart crashed stdio servers (enabled by default):

```bash
# Disable supervision
mcp-gateway --no-supervision
```

Configure in `config.json`:
```json
{
  "gateway": {
    "supervision": {
      "autoRestart": true,
      "maxRestarts": 10,
      "maxConsecutiveCrashes": 5,
      "initialBackoffSeconds": 1,
      "maxBackoffSeconds": 60
    }
  }
}
```

View supervision status: `GET /supervision`

### Circuit Breaker

Prevent cascading failures when backends are unhealthy:

```json
{
  "gateway": {
    "circuitBreakerEnabled": true,
    "circuitBreakerFailureThreshold": 5,
    "circuitBreakerRecoveryTimeout": 30
  }
}
```

- **CLOSED**: Normal operation
- **OPEN**: Failing fast after threshold reached
- **HALF_OPEN**: Testing if backend recovered

View circuit states: `GET /circuit-breakers`

### Config Approval for Sensitive Paths

Require CLI approval for filesystem changes:

```json
{
  "gateway": {
    "sensitivePaths": ["/etc", "/home", "/var"],
    "pathApprovalTimeout": 300
  }
}
```

When a tool tries to access a sensitive path, approve via CLI:

```bash
mcp-gateway approve
# Enter the approval code shown in the web UI or logs
```

### Rate Limiting

Prevent abuse with per-client rate limiting:

```json
{
  "gateway": {
    "rateLimit": {
      "enabled": true,
      "requestsPerSecond": 10,
      "burstSize": 20
    }
  }
}
```

### Structured Logging

JSON logs for production environments:

```bash
# Default: JSON structured logging
mcp-gateway

# Console logging for development
mcp-gateway --console-log
```

### Metrics

Prometheus-compatible metrics at `/metrics`:

```prometheus
# HELP mcp_gateway_requests_total Total requests
# TYPE mcp_gateway_requests_total counter
mcp_gateway_requests_total{backend="memory",status="success"} 42

# HELP mcp_gateway_backend_connected Backend connection status
# TYPE mcp_gateway_backend_connected gauge
mcp_gateway_backend_connected{name="time"} 1
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Gateway                               │
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   HTTP      │    │   Backend   │    │   Backend   │         │
│  │   Server    │───►│   Manager   │───►│  Connection │         │
│  │             │    │             │    │             │         │
│  │ • /mcp      │    │ • Spawn     │    │ • stdio     │         │
│  │ • /sse      │    │ • Monitor   │    │ • Streamable│◄───────┐│
│  │ • /health   │    │ • Route     │    │   HTTP      │        ││
│  │             │    │             │    │ • SSE       │        ││
│  └─────────────┘    └─────────────┘    └─────────────┘        ││
│         │                                    │                 ││
│         ▼                                    ▼                 ││
│  MCP Protocol                         MCP Protocol             ││
│  (JSON-RPC)                          (stdio/SSE/HTTP)          ││
│         │                                    │                 ││
│    Client                                 Servers              ││
│  (llama.cpp,                            (memory, time,        ││
│   Claude, etc.)                          filesystem, etc.)     ││
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 🧪 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | Primary StreamableHTTP endpoint |
| `/sse` | GET | SSE fallback endpoint |
| `/message` | POST | SSE message handler |
| `/health` | GET | Health check + backend status |
| `/metrics` | GET | Prometheus metrics |
| `/circuit-breakers` | GET | Circuit breaker statistics |
| `/backends` | GET | List connected backends |
| `/supervision` | GET | Process supervision status |
| `/backends/{name}/restart` | POST | Restart a backend |
| `/api/servers` | GET | List all configured servers |
| `/api/servers/{name}/tools` | GET | Get tools for a server |
| `/api/servers/{name}` | PUT | Update server configuration |
| `/api/config-changes/pending` | GET | List pending config changes |
| `/api/config-changes/{code}/approve` | POST | Approve a config change |

### Web Dashboards

Multiple themed dashboards are available:

| URL | Theme | Description |
|-----|-------|-------------|
| `/` | Standard | Clean modern dashboard |
| `/admin` | Admin Panel | Server configuration management |
| `/blue-box` | Blue Box | Cyberpunk blue terminal theme |
| `/retro` | Retro 80s | CRT terminal nostalgia |
| `/retro-admin` | Retro Admin | CRT terminal admin panel |

## 🔄 Comparison in Detail

### vs supergateway

supergateway is great for exposing a **single** stdio server over HTTP:

```bash
# supergateway - one command per server
npx -y supergateway --stdio "npx -y @modelcontextprotocol/server-memory" --port 3001
npx -y supergateway --stdio "uvx mcp-server-time" --port 3002

# Result: localhost:3001, localhost:3002 (multiple ports)
```

**mcp-gateway** manages **all** servers with one port:

```bash
# mcp-gateway - one process, all servers
python -m mcp-gateway

# Result: localhost:3000/mcp (all tools aggregated)
```

### vs mcpo

mcpo is an **OpenAPI proxy**, not an MCP server:

```
Client ──OpenAPI──► mcpo ──MCP──► Servers
       ❌ Wrong protocol!
```

**This breaks MCP clients** like llama.cpp webui, Claude Desktop, and Cursor.

**mcp-gateway** speaks **MCP natively**:

```
Client ──MCP──► mcp-gateway ──MCP──► Servers
       ✅ Native protocol!
```

### vs lunfengchen/gateway-mcp

That project uses **stdio transport** for the gateway itself:

```
Client ──stdio──► gateway ──stdio──► Servers
```

This works for local CLI clients but **not for HTTP-based clients** like llama.cpp webui.

**mcp-gateway** exposes **HTTP endpoints**:

```
Client ──HTTP/SSE──► mcp-gateway ──(stdio/HTTP)──► Servers
```

Works with **all** MCP clients.

## 🏗️ Architecture

MCP Gateway is built with a modular, maintainable architecture:

```
src/mcp_gateway/
├── server/              # FastAPI server package
│   ├── __init__.py      # Package exports
│   ├── server.py        # Main server class
│   ├── state.py         # Dependency injection container
│   ├── models.py        # Pydantic request/response models
│   ├── http_routes.py   # HTTP API route handlers
│   ├── mcp_handlers.py  # MCP protocol handlers
│   └── middleware.py    # FastAPI middleware
├── access_control/      # Access control package
│   ├── __init__.py      # Package exports
│   ├── manager.py       # Access control manager
│   ├── models.py        # Data models & enums
│   ├── patterns.py      # Sensitive path patterns
│   └── utils.py         # Utility functions
├── exceptions.py        # Custom exception hierarchy
├── config.py            # Configuration models & validation
├── backends.py          # Backend connection management
├── circuit_breaker.py   # Circuit breaker implementation
├── rate_limiter.py      # Rate limiting middleware
├── auth.py              # Authentication middleware
├── metrics.py           # Prometheus metrics
├── admin.py             # Config management
├── supervisor.py        # Process supervision
└── main.py              # Application entry point
```

### Design Principles

1. **Explicit Dependencies**: `ServerDependencies` dataclass replaces global state
2. **Custom Exceptions**: Structured error hierarchy for better error handling
3. **Modular Packages**: Related functionality grouped into subpackages
4. **Type Safety**: Full type annotations with mypy strict mode
5. **Testability**: All components easily mockable

## 🛣️ Roadmap

### ✅ Completed

- [x] **StreamableHTTP primary transport** - Modern stateless MCP transport
- [x] **SSE fallback transport** - Legacy fallback for older clients
- [x] **stdio backend support** - Run local MCP servers via command
- [x] **Remote HTTP/SSE backend support** - Connect to remote MCP servers
- [x] **Tool namespacing** - Configurable separator (default: `__`) prevents collisions
- [x] **Tool filtering** - Disable specific tools per server
- [x] **CORS support** - Cross-origin resource sharing enabled
- [x] **Configurable timeouts** - Connection & request timeouts
- [x] **Per-backend health check** - Individual backend status tracking
- [x] **Authentication** - API key (`X-API-Key` header) and Bearer token support
- [x] **Metrics endpoint** - Prometheus-compatible `/metrics` endpoint
- [x] **Circuit breaker** - Fail fast when backends are down
- [x] **Structured logging** - JSON format with configurable levels
- [x] **Web Dashboard** - Multiple themes (Standard, Blue Box, Retro 80s CRT)
- [x] **Hot reload** - Config changes without restart (`--hot-reload`)
- [x] **Process supervision** - Auto-restart crashed stdio servers
- [x] **Config approval** - CLI approval for sensitive path changes (`mcp-gateway approve`)
- [x] **Rate limiting** - Per-client request throttling middleware

### 🔜 Short-term (Planned)

- [ ] **Connection pooling** - Reuse backend connections for better performance
- [ ] **Request tracing** - Distributed tracing for debugging
- [ ] **Audit logging** - Security event logging
- [ ] **Plugin system** - Extensible middleware architecture

### 🎯 Mid-term (Planned)

- [ ] **Dynamic tool discovery** - Add/remove backends at runtime via API
- [ ] **Caching layer** - Cache tool results for expensive operations
- [ ] **Load balancing** - Distribute requests across multiple backend instances
- [ ] **Health check webhooks** - Notify external systems on backend state changes

### 🚀 Long-term (Vision)

- [ ] **Multi-tenant support** - Isolated backend sets per API key
- [ ] **Federation** - Connect multiple gateways hierarchically
- [ ] **Web-based config editor** - Visual configuration management
- [ ] **Advanced analytics** - Tool usage patterns and performance metrics

## 🤝 Contributing

Contributions welcome! This is a community project to fill a genuine gap in the MCP ecosystem.

## 📜 License

MIT - See [LICENSE](LICENSE) for details.

---

**Built because the alternatives didn't cut it.** One port. All tools. Native MCP.
