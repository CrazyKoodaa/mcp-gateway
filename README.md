# MCP Gateway

> **One endpoint. All your MCP tools.**

A production-ready gateway that aggregates multiple MCP (Model Context Protocol) servers into a single endpoint. Supports local stdio servers (npx, uvx), remote HTTP/SSE servers, and everything in between.

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

## 📚 Table of Contents

- [Why This Project Exists](#-why-this-project-exists)
- [Features](#-features)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the Gateway](#-running-the-gateway)
- [Client Integration](#-client-integration)
- [Admin Dashboard](#-admin-dashboard)
- [CLI Commands](#-cli-commands)
- [API Reference](#-api-reference)
- [Architecture](#-architecture)
- [Available MCP Servers](#-available-mcp-servers)
- [Production Deployment](#-production-deployment)
- [Troubleshooting](#-troubleshooting)
- [Development](#-development)

---

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
- ❌ OpenWebUI speaks **MCP protocol**, not OpenAPI

**Result**: mcpo is incompatible with standard MCP clients.

---

## ✨ Features

### 1. **Instant Config Changes — No Restart Required**

Edit servers in the **Admin Dashboard** (`/admin`) and changes are **live immediately**:

```bash
# Start with hot reload enabled
mcp-gateway --hot-reload

# Or edit via the web UI — changes apply instantly
# No restart, no downtime, no lost connections
```

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
    "memory": {
      "command": "npx -y @modelcontextprotocol/server-memory"
    },
    "github": {
      "type": "streamable-http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {"Authorization": "Bearer token"}
    },
    "custom-api": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

### 7. **Smart Transport Selection**

Like llama.cpp webui, we use the modern **StreamableHTTP** first, with automatic **SSE fallback**.

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

### 9. **Built-in Features**

- 🔐 **Authentication** - API key and Bearer token support
- 📊 **Metrics** - Prometheus-compatible `/metrics` endpoint
- 🔄 **Hot Reload** - Config changes without restart
- 🛡️ **Circuit Breaker** - Fail fast when backends are down
- 👁️ **Process Supervision** - Auto-restart crashed stdio servers
- 📝 **Structured Logging** - JSON format with configurable levels
- 🎨 **Web Dashboard** - Multiple themes (Standard, Blue Box, Retro 80s CRT)
- ⏱️ **Rate Limiting** - Per-client request throttling

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Node.js (for npx-based MCP servers)

### 1. Clone & Bootstrap

```bash
# Clone the repository
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway

# Run the bootstrap script (installs deps, creates config)
./bootstrap.sh
```

The bootstrap script will:
- ✅ Check Python version (3.11+ required)
- ✅ Check/install `uv`
- ✅ Create virtual environment (`.venv`)
- ✅ Install all dependencies
- ✅ Create `config.json` from template
- ✅ Create necessary directories (`logs/`, `ai/logs/`)
- ✅ Run basic tests

### 2. Start the Gateway

```bash
# Using the run script
./run.sh

# Or directly with uv
uv run python -m mcp_gateway

# Or after pip install
mcp-gateway
```

### 3. Test It

```bash
# Check health
curl http://localhost:3000/health

# List all tools
curl http://localhost:3000/backends

# Open web dashboard
open http://localhost:3000
```

---

## 📦 Installation

### Option 1: Development Install (Recommended)

```bash
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway
./bootstrap.sh
```

### Option 2: Update Existing Installation

```bash
./bootstrap.sh update
```

This will:
- Pull latest git changes
- Update dependencies
- Run tests

### Option 3: Manual Install with pip

```bash
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway
pip install -e ".[dev]"
```

### Option 4: Using uv

```bash
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway
uv venv .venv
uv pip install -e ".[dev]"
```

---

## ⚙️ Configuration

### Basic Config (`config.json`)

```json
{
  "gateway": {
    "host": "127.0.0.1",
    "port": 3000,
    "logLevel": "INFO",
    "enableNamespacing": true,
    "namespaceSeparator": "__"
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

### Configuration Options

#### Gateway Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | Host to bind to |
| `port` | integer | `3000` | Port to listen on |
| `logLevel` | string | `"INFO"` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `enableNamespacing` | boolean | `true` | Prefix tools with server name |
| `namespaceSeparator` | string | `"__"` | Separator for namespacing |
| `connectionTimeout` | number | `30` | Connection timeout in seconds |
| `requestTimeout` | number | `60` | Request timeout in seconds |
| `apiKey` | string | `null` | API key for authentication |
| `bearerToken` | string | `null` | Bearer token for authentication |
| `authExcludePaths` | array | `[]` | Paths excluded from auth |

#### Stdio Server Formats

**Format 1: Separate command and args (Recommended)**

```json
{
  "time": {
    "command": "uvx",
    "args": ["mcp-server-time", "--local-timezone=Europe/Berlin"],
    "disabledTools": ["convert_time"]
  }
}
```

**Format 2: One-liner (Auto-parsed)**

```json
{
  "filesystem": {
    "command": "npx -y @modelcontextprotocol/server-filesystem /home/user/projects"
  }
}
```

**Format 3: With environment variables**

```json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx"
    }
  }
}
```

#### Remote StreamableHTTP Server

```json
{
  "github-copilot": {
    "type": "streamable-http",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {
      "Authorization": "Bearer YOUR_TOKEN"
    }
  }
}
```

#### Remote SSE Server

```json
{
  "custom-server": {
    "type": "sse",
    "url": "http://localhost:8001/sse"
  }
}
```

### Advanced Configuration Examples

**With Authentication:**

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 3000,
    "apiKey": "mg_prod_your_secure_key",
    "bearerToken": "your_bearer_token",
    "authExcludePaths": ["/health", "/metrics"]
  }
}
```

**With Rate Limiting:**

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

**With Circuit Breaker:**

```json
{
  "gateway": {
    "circuitBreakerEnabled": true,
    "circuitBreakerFailureThreshold": 5,
    "circuitBreakerRecoveryTimeout": 30
  }
}
```

**With Process Supervision:**

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

**With Sensitive Path Protection:**

```json
{
  "gateway": {
    "sensitivePaths": ["/etc", "/home", "/var", "/root"],
    "pathApprovalTimeout": 300
  }
}
```

---

## ▶️ Running the Gateway

### Basic Usage

```bash
# Start with default config (config.json)
mcp-gateway

# With custom config
mcp-gateway --config /path/to/config.json

# With host/port overrides
mcp-gateway --host 0.0.0.0 --port 8080

# With debug logging
mcp-gateway --log-level DEBUG
```

### With Hot Reload

```bash
# Enable config file watching
mcp-gateway --hot-reload

# Use polling instead of inotify (for network filesystems)
mcp-gateway --hot-reload --poll
```

### Process Supervision

```bash
# Disable auto-restart of crashed servers
mcp-gateway --no-supervision
```

### Logging Options

```bash
# Console logging (development)
mcp-gateway --console-log

# JSON logging (production, default)
mcp-gateway
```

### Complete Example

```bash
mcp-gateway \
  --config ./config.json \
  --host 0.0.0.0 \
  --port 3000 \
  --log-level INFO \
  --hot-reload \
  --console-log
```

---

## 🔌 Client Integration

### llama.cpp webui

Add to your llama.cpp webui configuration:

```json
[
  {
    "id": "mcp-gateway",
    "enabled": true,
    "url": "http://localhost:3000/mcp",
    "useProxy": false
  }
]
```

Location depends on your llama.cpp webui setup:
- **Docker**: Mount the config to `/app/mcp-config.json`
- **Native**: Check your webui's settings directory

### OpenWebUI

In OpenWebUI, go to **Settings** → **Tools** → **MCP Servers**:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

Or use the SSE endpoint for older versions:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "type": "sse",
      "url": "http://localhost:3000/sse"
    }
  }
}
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%/Claude/claude_desktop_config.json` (Windows):

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

### Cursor

In Cursor, go to **Settings** → **AI** → **MCP**:

```json
{
  "mcpServers": {
    "gateway": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

### Kimi CLI

```bash
# Add MCP gateway to Kimi CLI
kimi mcp add gateway http://localhost:3000/mcp

# Or with authentication
kimi mcp add gateway http://localhost:3000/mcp --api-key YOUR_API_KEY
```

### Generic HTTP Client

```bash
# Get all tools
curl http://localhost:3000/backends

# Call a tool (StreamableHTTP)
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "time__get_current_time",
      "arguments": {}
    },
    "id": 1
  }'
```

---

## 🎨 Admin Dashboard

MCP Gateway includes multiple themed web dashboards:

| URL | Theme | Description |
|-----|-------|-------------|
| `/` | Standard | Clean modern dashboard |
| `/admin` | Admin Panel | Server configuration management |
| `/blue-box` | Blue Box | Cyberpunk blue terminal theme |
| `/retro` | Retro 80s | CRT terminal nostalgia |
| `/retro-admin` | Retro Admin | CRT terminal admin panel |

### Dashboard Features

- 📊 **Real-time backend status** - See all connected MCP servers
- 🔧 **Server management** - Add, edit, remove servers via web UI
- 🛠️ **Tool inspection** - View available tools per server
- 📝 **Live logs** - View gateway logs in real-time
- ⚙️ **Config editing** - Edit configuration directly in the browser

---

## 🖥️ CLI Commands

### Approve Access Requests

When a tool tries to access a sensitive path, you must approve it:

```bash
# Interactive mode (recommended)
mcp-gateway approve

# Quick approve with code
mcp-gateway approve ABCD-1234

# Approve with custom duration (minutes)
mcp-gateway approve ABCD-1234 -d 30
```

### List Pending Requests

```bash
mcp-gateway list
```

### CLI Options

```bash
# Use different gateway URL
mcp-gateway --api-url http://gateway:3000 approve
```

---

## 🔌 API Reference

### MCP Protocol Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | Primary StreamableHTTP endpoint |
| `/sse` | GET | SSE fallback endpoint |
| `/message` | POST | SSE message handler |

### Management Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + backend status |
| `/metrics` | GET | Prometheus metrics |
| `/backends` | GET | List connected backends |
| `/circuit-breakers` | GET | Circuit breaker statistics |
| `/supervision` | GET | Process supervision status |
| `/backends/{name}/restart` | POST | Restart a backend |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers` | GET | List all configured servers |
| `/api/servers/{name}/tools` | GET | Get tools for a server |
| `/api/servers/{name}` | PUT | Update server configuration |
| `/api/config-changes/pending` | GET | List pending config changes |
| `/api/config-changes/{code}/approve` | POST | Approve a config change |
| `/api/access/requests/pending` | GET | List pending access requests |
| `/api/access/requests/{code}/approve` | POST | Approve an access request |

---

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

### Project Structure

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

---

## 🔧 Troubleshooting

### Gateway Won't Start

```bash
# Check Python version
python3 --version  # Must be 3.11+

# Check config is valid JSON
python3 -m json.tool config.json

# Check dependencies are installed
uv pip list | grep mcp-gateway
```

### No Tools Showing

```bash
# Check backend status
curl http://localhost:3000/backends

# Check individual server logs
# Logs are in logs/ directory
```

### Authentication Errors

```bash
# Test with curl
curl -H "X-API-Key: your-key" http://localhost:3000/mcp

# Or with Bearer token
curl -H "Authorization: Bearer your-token" http://localhost:3000/mcp
```

### Stdio Servers Crashing

```bash
# Check process supervision status
curl http://localhost:3000/supervision

# Restart a specific backend
curl -X POST http://localhost:3000/backends/{name}/restart
```

### Hot Reload Not Working

```bash
# Use polling mode instead
mcp-gateway --hot-reload --poll
```

### Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `uv pip install -e ".[dev]"` |
| `Address already in use` | Change port: `mcp-gateway --port 3001` |
| `Permission denied` | Check file permissions or use sudo for ports < 1024 |
| `Backend disconnected` | Check server logs, restart with `/backends/{name}/restart` |

---

## 🛠️ Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/CrazyKoodaa/mcp-gateway.git
cd mcp-gateway

# Install with dev dependencies
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_config.py

# Run with coverage
uv run pytest --cov=mcp_gateway

# Run benchmark tests
uv run pytest tests/test_benchmark.py
```

### Code Quality

```bash
# Run type checker
uv run mypy src/mcp_gateway

# Run linter
uv run ruff check src/mcp_gateway

# Format code
uv run ruff format src/mcp_gateway
```

### Load Testing

```bash
# Install locust
uv pip install locust

# Run load tests
uv run locust -f tests/load/locustfile.py
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`uv run pytest`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

---

## 📊 Comparison in Detail

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

---

## 🛣️ Roadmap

### ✅ Completed

- [x] StreamableHTTP primary transport
- [x] SSE fallback transport
- [x] stdio backend support
- [x] Remote HTTP/SSE backend support
- [x] Tool namespacing
- [x] Tool filtering
- [x] CORS support
- [x] Configurable timeouts
- [x] Per-backend health check
- [x] Authentication
- [x] Metrics endpoint
- [x] Circuit breaker
- [x] Structured logging
- [x] Web Dashboard (multiple themes)
- [x] Hot reload
- [x] Process supervision
- [x] Config approval
- [x] Rate limiting

### 🔜 Planned

- [ ] Connection pooling
- [ ] Request tracing
- [ ] Audit logging
- [ ] Plugin system
- [ ] Dynamic tool discovery
- [ ] Caching layer
- [ ] Load balancing

---

## 🤝 Contributing

Contributions welcome! This is a community project to fill a genuine gap in the MCP ecosystem.

## 📜 License

MIT - See [LICENSE](LICENSE) for details.

---

## 📦 Available MCP Servers

Here are popular MCP servers you can use with mcp-gateway:

### Official Servers

| Server | Install | Description |
|--------|---------|-------------|
| **memory** | `npx -y @modelcontextprotocol/server-memory` | Persistent knowledge graph |
| **filesystem** | `npx -y @modelcontextprotocol/server-filesystem /path` | File operations |
| **github** | `npx -y @modelcontextprotocol/server-github` | GitHub API access |
| **gitlab** | `npx -y @modelcontextprotocol/server-gitlab` | GitLab API access |
| **postgres** | `npx -y @modelcontextprotocol/server-postgres` | PostgreSQL queries |
| **sqlite** | `npx -y @modelcontextprotocol/server-sqlite` | SQLite operations |
| **slack** | `npx -y @modelcontextprotocol/server-slack` | Slack integration |
| **puppeteer** | `npx -y @modelcontextprotocol/server-puppeteer` | Browser automation |

### Community Servers (uvx)

| Server | Install | Description |
|--------|---------|-------------|
| **time** | `uvx mcp-server-time` | Time and timezone utilities |
| **fetch** | `uvx mcp-server-fetch` | HTTP requests |
| **weather** | `uvx mcp-server-weather` | Weather data |
| **sequential-thinking** | `uvx mcp-server-sequential-thinking` | Step-by-step reasoning |

### Example Configurations

**Development Setup**:
```json
{
  "mcpServers": {
    "memory": {
      "command": "npx -y @modelcontextprotocol/server-memory"
    },
    "time": {
      "command": "uvx mcp-server-time --local-timezone=Europe/Berlin"
    },
    "filesystem": {
      "command": "npx -y @modelcontextprotocol/server-filesystem /home/user/projects"
    },
    "fetch": {
      "command": "uvx mcp-server-fetch"
    }
  }
}
```

**With Database**:
```json
{
  "mcpServers": {
    "postgres": {
      "command": "npx -y @modelcontextprotocol/server-postgres",
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost/db"
      }
    },
    "sqlite": {
      "command": "npx -y @modelcontextprotocol/server-sqlite /path/to/db.sqlite"
    }
  }
}
```

**With GitHub**:
```json
{
  "mcpServers": {
    "github": {
      "command": "npx -y @modelcontextprotocol/server-github",
      "env": {
        "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx"
      }
    }
  }
}
```

---

## 🖥️ Production Deployment

### Systemd Service

Create `/etc/systemd/system/mcp-gateway.service`:

```ini
[Unit]
Description=MCP Gateway
After=network.target

[Service]
Type=simple
User=mcp-gateway
Group=mcp-gateway
WorkingDirectory=/opt/mcp-gateway
Environment=PYTHONPATH=src
ExecStart=/opt/mcp-gateway/.venv/bin/python -m mcp_gateway --config /opt/mcp-gateway/config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-gateway
sudo systemctl start mcp-gateway
sudo systemctl status mcp-gateway
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e "."

EXPOSE 3000
CMD ["mcp-gateway", "--host", "0.0.0.0", "--config", "/app/config.json"]
```

```bash
docker build -t mcp-gateway .
docker run -p 3000:3000 -v $(pwd)/config.json:/app/config.json mcp-gateway
```

---

**Built because the alternatives didn't cut it.** One port. All tools. Native MCP.
