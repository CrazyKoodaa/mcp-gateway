# MCP Gateway Architecture Patterns

This document describes the architectural patterns and principles used in MCP Gateway.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Gateway                               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    HTTP Layer                            │  │
│  │                                                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │  │
│  │  │   Auth      │  │   Rate      │  │    CORS     │     │  │
│  │  │ Middleware  │  │ Limiter     │  │ Middleware  │     │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘     │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              FastAPI Router                      │   │  │
│  │  │  /mcp (StreamableHTTP)                           │   │  │
│  │  │  /sse (SSE Fallback)                             │   │  │
│  │  │  /health, /metrics, /docs                        │   │  │
│  │  │  /api/* (Admin endpoints)                        │   │  │
│  │  │  /* (Web dashboards)                             │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 Service Layer                            │  │
│  │                                                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │  │
│  │  │  Backend    │  │  Circuit    │  │  Config     │     │  │
│  │  │  Manager    │  │  Breaker    │  │  Approval   │     │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘     │  │
│  │                                                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │  │
│  │  │  Audit      │  │  Path       │  │  Metrics    │     │  │
│  │  │  Service    │  │ Security    │  │ Collector   │     │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   MCP Protocol Layer                     │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              FastMCP (mcp SDK)                   │   │  │
│  │  │  • Session management                            │   │  │
│  │  │  • Tool registration                             │   │  │
│  │  │  • JSON-RPC handling                             │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  Process Supervision                     │  │
│  │                                                          │  │
│  │  ┌─────────────┐  ┌─────────────┐                       │  │
│  │  │  Stdio      │  │  Auto       │                       │  │
│  │  │  Servers    │  │  Restart    │                       │  │
│  │  └─────────────┘  └─────────────┘                       │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            ┌─────────────┐     ┌─────────────┐
            │ Local MCP   │     │ Remote MCP  │
            │ Servers     │     │ Servers     │
            │ (npx/uvx)   │     │ (HTTP/SSE)  │
            └─────────────┘     └─────────────┘
```

---

## Design Patterns Used

### 1. Dependency Injection

**Purpose**: Achieve loose coupling and testability

**Implementation**:
```python
@dataclass
class ServerDependencies:
    """Container for all server dependencies."""
    config: GatewayConfig
    backend_manager: BackendManager
    config_manager: ConfigManager | None = None
    supervisor: ProcessSupervisor | None = None
    audit_service: AuditService | None = None
    path_security: PathSecurityService | None = None
    config_approval: ConfigApprovalService | None = None
    rate_limiter: MemoryRateLimiter | None = None
    circuit_breaker_registry: CircuitBreakerRegistry = field(
        default_factory=CircuitBreakerRegistry
    )
    metrics: MetricsCollector | None = None
    auth: AuthMiddleware | None = None
    templates: Jinja2Templates | None = None


class McpGatewayServer:
    def __init__(
        self,
        dependencies: ServerDependencies,  # Explicit injection
        enable_access_control: bool = True,
        audit_log_path: Path | None = None,
    ):
        self.deps = dependencies
```

**Benefits**:
- Easy to mock for testing
- Clear dependencies
- No global state
- Flexible composition

---

### 2. Service Layer Pattern

**Purpose**: Separate business logic from HTTP handling

**Implementation**:
```python
# services/config_approval_service.py
class ConfigApprovalService:
    """Handles config change approval workflow."""
    
    def __init__(
        self,
        audit_service: AuditService,      # Injected dependency
        path_security: PathSecurityService | None = None,
        request_timeout_minutes: int = 10,
        default_grant_duration: int = 1,
    ):
        self._audit = audit_service
        self._path_security = path_security or PathSecurityService()
        self._pending_requests: dict[str, PendingRequestInfo] = {}
        self._active_grants: dict[str, ActiveGrantInfo] = {}
    
    async def check_config_change(
        self,
        server_name: str,
        change_type: str,
        original_config: dict[str, Any],
        new_config: dict[str, Any],
    ) -> ApprovalResult:
        """Check if config change requires approval."""
        # Business logic here
        pass
    
    async def approve(
        self,
        code: str,
        duration_minutes: int,
        approved_by: str,
    ) -> tuple[bool, str, ActiveGrantInfo | None]:
        """Approve a config change request."""
        # Business logic here
        pass
```

**Services**:
- `AuditService`: Structured audit logging
- `PathSecurityService`: Platform-aware path detection
- `ConfigApprovalService`: Config change workflow
- `MetricsCollector`: Prometheus metrics
- `RateLimiter`: Token bucket rate limiting

---

### 3. Circuit Breaker Pattern

**Purpose**: Prevent cascading failures when backends are unhealthy

**States**:
```
CLOSED ──(failures >= threshold)──► OPEN ──(timeout elapsed)──► HALF_OPEN
   │                                   │                           │
   │                                   ▼                           ▼
   └─────────────(success)─────────────┴──────────(success)───────┘
```

**Implementation**:
```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type[Exception] = Exception,
    ):
        self._state = "CLOSED"
        self._failure_count = 0
        self._last_failure_time: float | None = None
    
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self._state == "OPEN":
            if time.time() - self._last_failure_time > self._recovery_timeout:
                self._state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpen(f"Circuit is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self._expected_exception as e:
            self._on_failure()
            raise


class CircuitBreakerRegistry:
    """Manages circuit breakers per backend."""
    
    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
            )
        return self._breakers[name]
```

---

### 4. Factory Pattern

**Purpose**: Create backend connections based on configuration

**Implementation**:
```python
class BackendManager:
    async def add_backend(self, config: ServerConfig) -> BackendConnection:
        """Create and connect a backend connection."""
        backend = BackendConnection(
            config,
            self._connection_timeout,
            self._request_timeout
        )
        await backend.connect()
        
        async with self._lock:
            self._backends[config.name] = backend
        
        return backend
    
    async def _connect_stdio(self, config: ServerConfig) -> StdioTransport:
        """Create stdio transport for local server."""
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env={**os.environ, **config.env},
        )
        return await stdio_client(server_params)
    
    async def _connect_remote(self, config: ServerConfig) -> RemoteTransport:
        """Create remote transport (StreamableHTTP or SSE)."""
        if config.transport_type == "streamable-http":
            return await streamablehttp_client(
                url=config.url,
                headers=config.headers,
            )
        else:
            return await sse_client(
                url=config.url,
                headers=config.headers,
            )
```

---

### 5. Observer Pattern

**Purpose**: Notify components of events without tight coupling

**Implementation**:
```python
class AccessControlManager:
    def __init__(self):
        self._notification_callbacks: list[Callable] = []
    
    def register_notification_callback(self, callback: Callable) -> None:
        """Register a callback for access request notifications."""
        self._notification_callbacks.append(callback)
    
    def _notify(self, event_type: str, data: dict) -> None:
        """Notify all registered callbacks."""
        for callback in self._notification_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event_type, data))
                else:
                    callback(event_type, data)
            except Exception as e:
                logger.error(f"Notification callback failed: {e}")
    
    # Event types:
    # - request_created
    # - request_approved
    # - request_expired
    # - config_request_created
    # - config_request_approved
    # - config_reverted
```

---

### 6. Strategy Pattern

**Purpose**: Select transport mechanism at runtime

**Implementation**:
```python
class BackendConnection:
    async def _connect_remote(self) -> None:
        """Connect to remote MCP server via HTTP/SSE."""
        url: str = self.config.url
        
        # Try StreamableHTTP first, fallback to SSE
        if self.config.transport_type == "streamable-http":
            try:
                await self._connect_streamable_http(url)
            except Exception as e:
                logger.warning(f"StreamableHTTP failed, trying SSE: {e}")
                await self._connect_sse(url)
        elif self.config.transport_type == "sse":
            await self._connect_sse(url)
        else:
            # Default: try StreamableHTTP first
            try:
                await self._connect_streamable_http(url)
            except Exception as e:
                logger.warning(f"StreamableHTTP failed, trying SSE: {e}")
                await self._connect_sse(url)
    
    async def _connect_streamable_http(self, url: str) -> None:
        """Use StreamableHTTP transport strategy."""
        ...
    
    async def _connect_sse(self, url: str) -> None:
        """Use SSE transport strategy."""
        ...
```

---

### 7. Repository Pattern (Simplified)

**Purpose**: Manage configuration persistence

**Implementation**:
```python
class ConfigManager:
    def __init__(self, config_path: Path, initial_config: GatewayConfig):
        self._config_path = config_path
        self.gateway_config = initial_config
    
    def update_server(self, name: str, config: dict[str, Any]) -> None:
        """Update server configuration."""
        if name not in self.gateway_config.servers:
            raise ValueError(f"Server '{name}' not found")
        
        # Validate and update
        new_config = ServerConfig(**{
            **self.gateway_config.servers[name].model_dump(),
            **config
        })
        self.gateway_config.servers[name] = new_config
    
    async def save(self) -> None:
        """Atomically save configuration to disk."""
        temp_path = self._config_path.with_suffix(".tmp")
        
        with open(temp_path, "w") as f:
            json.dump(save_config(self.gateway_config), f, indent=2)
        
        # Atomic rename
        temp_path.replace(self._config_path)
    
    async def reload(self) -> None:
        """Reload configuration from disk."""
        self.gateway_config = load_config(self._config_path)
```

---

## Communication Between Layers

### HTTP → Service Layer

```python
@app.post("/api/config-changes/{code}/approve")
async def approve_change(
    code: str,
    request: Request,
    deps: ServerDependencies = Depends(get_dependencies),
):
    """Approve a config change request."""
    # Rate limiting
    if deps.rate_limiter:
        client_ip = request.client.host
        limit_result = await deps.rate_limiter.check(f"approve:{client_ip}")
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Delegate to service
    success, message, grant = await deps.config_approval.approve(
        code=code,
        duration_minutes=5,
        approved_by="web",
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "grant": grant}
```

### Service → Backend Layer

```python
class ConfigApprovalService:
    async def approve(
        self,
        code: str,
        duration_minutes: int,
        approved_by: str,
    ) -> tuple[bool, str, ActiveGrantInfo | None]:
        """Approve a config change request."""
        # Find and validate request
        request = self._pending_requests.get(code)
        if not request or request.status != AccessRequestStatus.PENDING:
            return False, "Invalid or expired request", None
        
        # Create grant
        grant = ActiveGrantInfo(...)
        self._active_grants[grant.id] = grant
        request.status = AccessRequestStatus.APPROVED
        
        # Register revert callback for expiration
        self._register_revert_callback(grant)
        
        return True, f"Approved for {duration_minutes} minutes", grant
    
    def _register_revert_callback(self, grant: ActiveGrantInfo) -> None:
        """Schedule config revert on grant expiration."""
        async def on_expire():
            if time.time() > grant.expires_at.timestamp():
                await self._on_grant_expired(grant)
        
        asyncio.create_task(on_expire())
```

### Backend → MCP Protocol Layer

```python
class McpGatewayServer:
    def _sync_tools_to_mcp(self) -> None:
        """Synchronize tools from all backends to FastMCP."""
        if not hasattr(self, 'mcp_server') or self.mcp_server is None:
            return
        
        # Clear existing tools
        tool_names = list(self.mcp_server._tool_manager._tools.keys())
        for name in tool_names:
            self.mcp_server._tool_manager.remove_tool(name)
        
        # Register tools from each backend
        for backend in self.backend_manager.backends.values():
            for tool in backend.tools:
                namespaced_name = f"{backend.name}__{tool.name}"
                
                # Create wrapper that routes to correct backend
                async def make_wrapper(b=backend, t=tool.name):
                    async def wrapper(**kwargs):
                        return await b.call_tool(t, kwargs)
                    return wrapper
                
                self.mcp_server._tool_manager.add_tool(
                    make_wrapper(),
                    name=namespaced_name,
                    description=f"[{backend.name}] {tool.description}",
                )
```

---

## Threading and Concurrency

### Async-First Design

The entire codebase uses `async/await` for non-blocking I/O:

```python
# ✓ Correct: Async operations are awaited
async def handle_request(self):
    result = await self.backend.call_tool("read_file", {"path": "/etc"})
    return result

# ✗ Wrong: Blocking operations in async context
async def handle_request_bad(self):
    time.sleep(1)  # Blocks event loop!
    result = self.backend.call_tool(...)  # Returns coroutine, not awaited
    return result
```

### Thread-Safe Data Structures

For shared state, use `asyncio.Lock`:

```python
class BackendManager:
    def __init__(self):
        self._backends: dict[str, BackendConnection] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
    
    async def add_backend(self, config: ServerConfig) -> None:
        async with self._lock:
            self._backends[config.name] = backend
```

### Task Management

Track background tasks to prevent garbage collection:

```python
class McpGatewayServer:
    def __init__(self):
        self._background_tasks: set[asyncio.Task] = set()
    
    def _run_background_task(self, coro, name: str | None = None) -> asyncio.Task:
        """Run a coroutine and track it."""
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        
        def on_done(t):
            self._background_tasks.discard(t)
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Background task {name} failed: {e}")
        
        task.add_done_callback(on_done)
        return task
```

---

## Error Handling Strategy

### Specific Exceptions

Avoid bare `except`:

```python
# ✓ Correct: Catch specific exceptions
try:
    result = await some_operation()
except FileNotFoundError:
    logger.warning("File not found")
except PermissionError:
    logger.warning("Permission denied")
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise

# ✗ Wrong: Bare except catches everything including KeyboardInterrupt
try:
    result = await some_operation()
except:
    pass  # Dangerous!
```

### Circuit Breaker Integration

```python
async def call_backend_tool(
    self,
    backend_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    """Call a tool on a backend with circuit breaker protection."""
    cb = self.deps.circuit_breaker_registry.get(backend_name)
    
    try:
        return await cb.call(
            self.backend_manager.backends[backend_name].call_tool,
            tool_name,
            arguments
        )
    except CircuitBreakerOpen:
        logger.warning(f"Circuit open for {backend_name}")
        raise HTTPException(
            status_code=503,
            detail=f"Backend {backend_name} is unavailable"
        )
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        raise
```

---

## Logging Strategy

### Structured Logging

Use `structlog` for JSON logs in production:

```python
from structlog import get_logger

logger = get_logger(__name__)

# ✓ Correct: Structured logging
logger.info(
    "Backend connected",
    backend_name=backend.name,
    tools=len(backend.tools),
    transport_type=backend.config.transport_type,
)

# ✗ Wrong: String formatting (noisy, hard to query)
logger.info(f"Backend {backend.name} connected with {len(backend.tools)} tools")
```

### Log Levels

| Level | Use Case |
|-------|----------|
| DEBUG | Detailed debugging information |
| INFO | Normal operational events |
| WARNING | Unexpected but handled conditions |
| ERROR | Errors that affect functionality |
| CRITICAL | Severe errors requiring immediate attention |

---

## Configuration Management

### Pydantic Models

Use Pydantic for validation and type safety:

```python
class ServerConfig(BaseModel):
    name: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    type: Literal["stdio", "sse", "streamable-http"] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    disabled_tools: list[str] = Field(default_factory=list)
    
    @field_validator("args", mode="before")
    @classmethod
    def parse_args(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return shlex.split(v)
        return list(v) if v else []
```

### Hot Reload

Watch config file changes and apply updates:

```python
class HotReloadManager:
    async def start(self, use_polling: bool = False) -> None:
        """Start watching config file for changes."""
        if use_polling:
            await self._start_polling()
        else:
            await self._start_watchdog()
    
    async def _on_config_changed(self) -> None:
        """Handle config file change."""
        try:
            new_config = load_config(self._config_path)
            
            # Notify callback
            if self._reconnect_callback:
                await self._reconnect_callback(new_config)
            
            logger.info("Configuration reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")
```

---

## References

- [Python Data Classes](https://docs.python.org/3/library/dataclasses.html)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Dependency Injection in Python](https://www.pythonismy.com/di-in-python)
