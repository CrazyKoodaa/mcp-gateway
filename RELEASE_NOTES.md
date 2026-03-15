# MCP Gateway v0.1.0 - Beta Release

> **One endpoint. All your MCP tools.**

⚠️ **BETA VERSION** - This is an early release with active development. Features may change, and there are still many improvements planned. Use with caution in production environments.

🔐 **Security-First**: Additional security layer between MCP servers and your system. MCP Gateway acts as an "air gap" - preventing direct access to critical system areas while allowing time-limited approvals for sensitive operations via Admin Dashboard or CLI.

---

## ✨ What's Included

### Core Features

- 🔌 **Multiple Transport Support** - stdio (npx, uvx), HTTP/SSE, StreamableHTTP
- 🎯 **One Port** - Aggregate all MCP servers on a single port (default: 3000)
- 🏷️ **Tool Namespacing** - Automatic prefixing prevents collisions (`memory__add`, `time__get_current_time`)
- 🛠️ **Tool Filtering** - Disable specific tools per server
- 🔐 **Authentication** - API key and Bearer token support
- 📊 **Web Dashboard** - Multiple themes (Standard, Blue Box, Retro 80s CRT)
- 🔄 **Hot Reload** - Config changes without restart (`--hot-reload`)
- 🛡️ **Circuit Breaker** - Fail fast when backends are unhealthy
- 👁️ **Process Supervision** - Auto-restart crashed stdio servers
- ⏱️ **Rate Limiting** - Per-client request throttling
- 📝 **Structured Logging** - JSON format with configurable levels
- 📈 **Prometheus Metrics** - `/metrics` endpoint for monitoring

### MCP Protocol

- ✅ **StreamableHTTP** (`POST /mcp`) - Modern, stateless
- ✅ **SSE** (`GET /sse`) - Legacy fallback
- ✅ Full JSON-RPC implementation
- ✅ Compatible with all MCP clients

---

## 🚀 Quick Start

### Installation

```bash
# Clone and bootstrap
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway
./scripts/setup/bootstrap.sh
```

### Configure

```bash
# Copy example config
cp config.json.example config.json

# Edit to add your MCP servers
nano config.json
```

Example configuration:
```json
{
  "gateway": {
    "host": "127.0.0.1",
    "port": 3000
  },
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    },
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time"]
    }
  }
}
```

### Run

```bash
# Start the gateway
./scripts/run.sh

# Or with options
mcp-gateway --host 0.0.0.0 --port 3000 --hot-reload
```

### Connect Your Client

**llama.cpp webui:**
```json
[{
  "id": "mcp-gateway",
  "enabled": true,
  "url": "http://localhost:3000/mcp"
}]
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

---

## 📦 What's Changed

### Added
- Initial release of MCP Gateway
- Support for stdio, HTTP, SSE backends
- Tool namespacing with configurable separator
- Tool filtering per server
- Web dashboard with multiple themes
- Hot reload configuration
- Circuit breaker pattern
- Process supervision
- Rate limiting
- Authentication (API key / Bearer token)
- Prometheus metrics
- Structured JSON logging
- Admin API for runtime configuration

### Security
- **🛡️ Air Gap Architecture** - Additional security layer prevents MCP servers from directly accessing your system
- **⏱️ Time-Limited Access Approval** - Grant temporary, expiring access to critical system areas via Admin Dashboard or CLI
- Path approval for sensitive filesystem operations
- Configurable authentication
- Rate limiting per client
- Circuit breaker for backend protection

### Known Limitations (Beta)
This is a beta release with active development. The following improvements are planned:
- Connection pooling for better performance
- Request tracing for debugging
- Audit logging for security events
- Plugin system for extensibility
- Dynamic backend discovery
- Caching layer for expensive operations

---

## 🏗️ Architecture

```
┌─────────────────┐      ┌──────────────────────────────┐      ┌─────────────────┐
│  llama.cpp      │ MCP  │      MCP Gateway             │stdio │  MCP Servers    │
│    webui        │◄────►│  (ONE port: 3000)            │◄────►│ • memory        │
│  Claude Desktop │HTTP  │                              │      │ • time          │
│  Cursor         │      │ • StreamableHTTP primary     │HTTP  │ • filesystem    │
│  OpenWebUI      │      │ • SSE fallback               │◄────►│ • fetch         │
│  Any MCP client │      │ • Smart transport switching  │      │ • github        │
└─────────────────┘      └──────────────────────────────┘      └─────────────────┘
```

---

## 📚 Documentation

- [Full README](https://github.com/CrazyKoodaa/mcp-gateway/blob/main/README.md)
- [Configuration Guide](https://github.com/CrazyKoodaa/mcp-gateway/blob/main/config/examples/config.example.json)
- [API Reference](https://github.com/CrazyKoodaa/mcp-gateway#-api-reference)

---

## 🛠️ System Requirements

- Python 3.11+
- uv (recommended) or pip
- Node.js (for npx-based MCP servers)

---

## 🤝 Contributing

Contributions are welcome! Please see the [README](https://github.com/CrazyKoodaa/mcp-gateway#-development) for development setup.

---

## 📜 License

MIT - See [LICENSE](https://github.com/CrazyKoodaa/mcp-gateway/blob/main/LICENSE) for details.

---

**Built because the alternatives didn't cut it.** One port. All tools. Native MCP.
