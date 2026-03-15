# Security Patterns for MCP Gateway

This document describes security implementations and patterns used in MCP Gateway.

---

## Authentication

### API Key Authentication

Supports API key via `X-API-Key` header:

```json
{
  "gateway": {
    "apiKey": "your-secure-api-key"
  }
}
```

**Usage:**
```bash
curl -H "X-API-Key: your-secure-api-key" http://localhost:3000/mcp
```

### Bearer Token Authentication

Supports Bearer token via `Authorization` header:

```json
{
  "gateway": {
    "bearerToken": "your-secure-bearer-token"
  }
}
```

**Usage:**
```bash
curl -H "Authorization: Bearer your-secure-bearer-token" http://localhost:3000/mcp
```

### Excluded Paths

Paths excluded from authentication (default):
```python
["/health", "/metrics", "/docs", "/openapi.json"]
```

### Implementation

```python
class AuthMiddleware:
    def __init__(
        self,
        api_key: str | None = None,
        bearer_token: str | None = None,
        exclude_paths: list[str] | None = None,
    ):
        self._api_key = api_key
        self._bearer_token = bearer_token
        self._exclude_paths = set(exclude_paths or [])
    
    async def __call__(self, request: Request, call_next):
        # Skip auth for excluded paths
        if request.url.path in self._exclude_paths:
            return await call_next(request)
        
        # Check API key
        if self._api_key:
            api_key = request.headers.get("X-API-Key")
            if not api_key or api_key != self._api_key:
                raise HTTPException(status_code=401, detail="Invalid API key")
        
        # Check Bearer token
        if self._bearer_token:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing Authorization header")
            
            token = auth_header[7:]  # Remove "Bearer " prefix
            if token != self._bearer_token:
                raise HTTPException(status_code=401, detail="Invalid token")
        
        return await call_next(request)
```

---

## Rate Limiting

### Token Bucket Algorithm

Prevents brute-force attacks on approval endpoints:

```python
class MemoryRateLimiter:
    def __init__(
        self,
        requests_per_minute: int = 5,
        burst_size: int | None = None,
    ):
        self._requests_per_second = requests_per_minute / 60.0
        self._burst_size = burst_size or requests_per_minute
        self._buckets: dict[str, TokenBucket] = {}
    
    async def check(self, key: str) -> RateLimitResult:
        """Check if request is allowed and consume a token if so."""
        bucket = self._get_bucket(key)
        
        if not bucket.try_consume():
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=bucket.time_until_refill(),
            )
        
        return RateLimitResult(
            allowed=True,
            remaining=max(0, bucket.tokens - 1),
            reset_time=bucket.last_refill_time + (self._burst_size / self._requests_per_second),
        )
    
    def _get_bucket(self, key: str) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                rate=self._requests_per_second,
                capacity=self._burst_size,
            )
        return self._buckets[key]


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    rate: float  # Tokens per second
    capacity: int
    tokens: float = field(default_factory=lambda: 1.0)
    last_refill_time: float = field(default_factory=time.time)
    
    def try_consume(self) -> bool:
        """Try to consume a token. Returns True if successful."""
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill_time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill_time = now
    
    def time_until_refill(self) -> float:
        """Time until one token is available (if bucket empty)."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.rate
```

### Rate Limit Configuration

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

---

## Path Security

### Sensitive Path Detection

Platform-aware detection of sensitive filesystem paths:

#### Linux Patterns

```python
SENSITIVE_PATH_PATTERNS_LINUX = [
    "/",                    # Root directory (ultimate sensitive path)
    "/etc",                 # System configuration
    "/sys", "/proc",        # Kernel interfaces
    "/dev",                 # Device files
    "/boot",                # Boot files
    "/root",                # Root user home
    "/var/log",             # System logs
    "/usr/bin", "/usr/sbin", # Executables
    "/lib", "/lib64",       # Libraries
    "/home/*/.ssh",         # User SSH keys
]
```

#### macOS Patterns

```python
SENSITIVE_PATH_PATTERNS_MACOS = [
    "/",                    # Root directory
    "/etc",                 # System configuration
    "/System",              # System files (SIP-protected)
    "/Library",             # System libraries
    "/Users/*/.ssh",        # User SSH keys
]
```

#### Windows Patterns

```python
SENSITIVE_PATH_PATTERNS_WINDOWS = [
    r"C:\",                 # C: drive root
    r"C:\Windows",          # Windows directory
    r"C:\Program Files",    # Installed programs
    r"C:\ProgramData",      # Application data
    r"C:\Users\*\.ssh",     # User SSH keys
    "*.pem", "*.key",       # Certificate files
]
```

### Implementation

```python
class PathSecurityService:
    def __init__(self, platform: Literal["windows", "darwin", "linux"] | None = None):
        self._platform = platform or self._detect_platform()
        self._patterns = self._get_patterns_for_platform(self._platform)
    
    def _detect_platform(self) -> str:
        """Auto-detect the running platform."""
        if sys.platform == "win32":
            return "windows"
        elif sys.platform == "darwin":
            return "darwin"
        else:
            return "linux"
    
    def check_path(self, path: str) -> PathCheckResult:
        """Check if a path is sensitive.
        
        Returns:
            PathCheckResult with is_sensitive flag and matched pattern
        """
        normalized = self._normalize_path(path)
        
        for pattern in self._patterns:
            if self._matches_pattern(normalized, pattern):
                return PathCheckResult(
                    path=path,
                    is_sensitive=True,
                    matched_pattern=pattern,
                    platform=self._platform,
                )
        
        return PathCheckResult(
            path=path,
            is_sensitive=False,
            matched_pattern=None,
            platform=self._platform,
        )
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for cross-platform comparison."""
        # Expand home directory
        try:
            path = Path(path).expanduser().as_posix()
        except (OSError, ValueError):
            pass
        
        # Normalize separators and lowercase
        return path.replace('\\', '/').lower()
    
    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches a sensitivity pattern."""
        # Handle root paths specially
        if pattern == "/":
            return path == "/" or path == ""
        
        # Wildcard patterns
        if "*" in pattern or "?" in pattern:
            return fnmatch.fnmatch(path, pattern.lower())
        
        # Exact match
        if path == pattern.lower():
            return True
        
        # Prefix match (path is under sensitive directory)
        return path.startswith(pattern.lower() + "/")
```

---

## Approval Code Security

### Code Generation

Uses cryptographically secure random generation:

```python
import secrets
import string

class ConfigApprovalService:
    def _generate_code(self) -> str:
        """Generate an 8-char approval code like 'ABCD-1234'."""
        # 4 uppercase letters + 4 digits
        letters = ''.join(
            secrets.choice(string.ascii_uppercase) for _ in range(4)
        )
        numbers = ''.join(
            secrets.choice(string.digits) for _ in range(4)
        )
        return f"{letters}-{numbers}"
```

**Entropy Analysis:**
- Letters: 26^4 ≈ 458,000 combinations (~19 bits)
- Numbers: 10^4 = 10,000 combinations (~13 bits)
- **Total**: ~32 bits of entropy

This provides adequate protection against brute-force attacks when combined with rate limiting.

### Timing-Safe Comparison

When comparing approval codes or checksums, use `hmac.compare_digest`:

```python
import hmac

# ✓ Correct: Timing-safe comparison
if hmac.compare_digest(provided_code, stored_code):
    grant_access()

# ✗ Wrong: Vulnerable to timing attacks
if provided_code == stored_code:
    grant_access()
```

---

## Race Condition Prevention

### Config Drift Detection

Prevents race conditions where config changes between request creation and approval:

```python
class ConfigApprovalService:
    def compute_config_checksum(self, config: dict[str, Any]) -> str:
        """Compute a SHA256 checksum of the config."""
        config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]
    
    async def approve(
        self,
        code: str,
        duration_minutes: int,
        approved_by: str,
        current_config: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str, ActiveGrantInfo | None]:
        """Approve a config change with drift detection."""
        request = self._pending_requests.get(code)
        if not request:
            return False, "Invalid code", None
        
        # Detect config drift (race condition)
        if current_config is not None and request.original_config_checksum:
            current_checksum = self.compute_config_checksum(current_config)
            if current_checksum != request.original_config_checksum:
                # Config changed since request was created
                request.status = AccessRequestStatus.EXPIRED
                return False, "Config changed since request was created", None
        
        # Proceed with approval...
```

### Thread-Safe Data Structures

Use `asyncio.Lock` for shared state:

```python
class ConfigApprovalService:
    def __init__(self):
        self._pending_requests: dict[str, PendingRequestInfo] = {}
        self._active_grants: dict[str, ActiveGrantInfo] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
    
    async def get_pending_requests(self) -> list[PendingRequestInfo]:
        """Thread-safe access to pending requests."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            return [
                req for req in self._pending_requests.values()
                if req.status == AccessRequestStatus.PENDING 
                and req.expires_at > now
            ]
```

---

## Audit Logging

### Structured JSON Logs

All security events are logged with structured JSON:

```python
class AuditService:
    def log_access_request_created(
        self,
        mcp_name: str,
        tool_name: str,
        path: str,
        request_code: str,
        client_ip: str | None = None,
    ) -> None:
        """Log an access request being created."""
        self._logger.info(
            "access_request_created",
            event_type="access_request_created",
            mcp_name=mcp_name,
            tool_name=tool_name,
            path=path,
            request_code=request_code,
            client_ip=client_ip,
        )
```

**Example Output:**
```json
{
  "timestamp": "2024-01-01T10:00:00.000Z",
  "event_type": "access_request_created",
  "mcp_name": "filesystem",
  "tool_name": "read_file",
  "path": "/etc/passwd",
  "request_code": "ABCD-1234",
  "client_ip": "192.168.1.100"
}
```

### Tamper-Evident Chain (Future Enhancement)

For enhanced security, implement chain hashing:

```python
class AuditService:
    def __init__(self, log_path: Path):
        self._log_path = log_path
        self._last_hash: str | None = None
    
    async def _get_last_hash(self) -> str | None:
        """Get the hash of the last log entry."""
        if not self._log_path.exists():
            return None
        
        with open(self._log_path, "r") as f:
            lines = f.readlines()
            if lines:
                last_entry = json.loads(lines[-1])
                return last_entry.get("chain_hash")
        
        return None
    
    def log_with_chain(
        self,
        event_type: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Log an event with chain hash for tamper detection."""
        previous_hash = asyncio.run(self._get_last_hash())
        
        # Create entry
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "previous_hash": previous_hash or "",
            **kwargs,
        }
        
        # Compute this entry's hash
        entry_str = json.dumps(entry, sort_keys=True)
        entry["chain_hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
        
        # Append to log file
        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        self._last_hash = entry["chain_hash"]
        
        return entry
```

---

## Security Best Practices Checklist

- [ ] Use `hmac.compare_digest` for all sensitive comparisons
- [ ] Implement rate limiting on approval endpoints
- [ ] Validate and sanitize all user inputs
- [ ] Use parameterized queries (not applicable here - no SQL)
- [ ] Implement proper error handling without leaking sensitive info
- [ ] Log all security events with structured JSON
- [ ] Use cryptographically secure random generation (`secrets` module)
- [ ] Implement CSRF protection (if using cookies)
- [ ] Set secure cookie flags if using sessions
- [ ] Use HTTPS in production
- [ ] Implement CORS properly
- [ ] Regularly update dependencies
- [ ] Run security audits regularly

---

## Vulnerabilities Mitigated

| Vulnerability | Mitigation |
|---------------|------------|
| **Brute-force attacks** | Rate limiting on approval endpoints |
| **Timing attacks** | `hmac.compare_digest` for code comparison |
| **Path traversal** | Resolved path comparison before granting access |
| **Config drift** | Checksum verification on approval |
| **Race conditions** | Locks for shared state, checksum validation |
| **Unauthorized access** | API key / Bearer token authentication |
| **Information disclosure** | Structured logging without sensitive data |
| **Cascading failures** | Circuit breaker pattern |
| **DoS attacks** | Rate limiting, timeouts, circuit breakers |

---

## References

- [Python `secrets` module](https://docs.python.org/3/library/secrets.html)
- [Python `hmac` module](https://docs.python.org/3/library/hmac.html)
- [OWASP Security Cheat Sheets](https://cheatsheetseries.owasp.org/)
- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)
