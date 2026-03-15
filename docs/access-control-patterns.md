# Access Control Patterns for MCP Gateway

This document describes the access control patterns implemented in MCP Gateway for securing filesystem and sensitive path access.

## Security Model

### Threat Model

1. **Untrusted MCP Servers**: MCP servers may attempt to read/write arbitrary filesystem paths
2. **Path Traversal**: Attackers may try to access parent directories beyond allowed paths
3. **Sensitive Data Exposure**: Sensitive files (credentials, system configs) must be protected
4. **Configuration Tampering**: Server configurations should not be modified without approval

### Core Principles

1. **Default Deny**: No access granted unless explicitly allowed
2. **Time-Bounded Grants**: All access expires after a defined duration
3. **Approval Workflow**: Sensitive operations require explicit approval
4. **Audit Trail**: All access attempts logged with chain hashes
5. **Platform-Aware**: Path detection works across Windows, macOS, Linux

---

## Access Control Types

### 1. Runtime Path Access Control

Controls what paths an MCP server can access at runtime during tool execution.

#### Flow

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ MCP Client  │────►│ MCP Gateway      │────►│ MCP Server      │
│             │     │                  │     │                 │
│             │     │ • Check allowed  │     │ • Read file     │
│ read_file   │     │   paths          │     │ • Write file    │
│             │     │ • Check grants   │     │                 │
└─────────────┘     │ • Create request │     └─────────────────┘
                    └──────────────────┘
                          │
                          ▼
                   ┌──────────────────┐
                   │ Admin UI / CLI   │
                   │ • View requests  │
                   │ • Approve/Deny   │
                   │ • Set duration   │
                   └──────────────────┘
```

#### Approval Code Format

- **Format**: `XXXX-XXXX` (e.g., `ABCD-1234`)
- **Generation**: Cryptographically secure random
- **Letters**: 4 uppercase letters
- **Numbers**: 4 digits
- **Entropy**: ~50 bits of entropy

### 2. Configuration Change Control

Controls modifications to server configurations that may introduce new sensitive path access.

#### Flow

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Web Admin   │────►│ MCP Gateway      │     │ Config Manager  │
│ Panel       │     │                  │     │                 │
│             │     │ • Validate config│     │ • Store config  │
│ Update FS   │     │ • Check paths    │     │ • Restart backend│
│ Server      │     │ • Create request │     │                 │
│             │     │ • Apply safe     │     └─────────────────┘
│             │     │   paths          │
└─────────────┘     └──────────────────┘
                          │
                          ▼
                   ┌──────────────────┐
                   │ Approval Required│
                   │ for sensitive    │
                   │ paths only       │
                   └──────────────────┘
```

---

## Sensitive Path Detection

### Platform-Specific Patterns

#### Linux/Unix

```python
SENSITIVE_PATH_PATTERNS = [
    "/",                    # Root directory
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

#### macOS

```python
SENSITIVE_PATH_PATTERNS = [
    "/",                    # Root directory
    "/etc",                 # System configuration
    "/System",              # System files (SIP-protected)
    "/usr",                 # Unix utilities
    "/bin", "/sbin",        # Essential binaries
    "/Library",             # System libraries
    "/Users/*/.ssh",        # User SSH keys
    "/Users/*/Library/Keychains",  # Keychain data
]
```

#### Windows

```python
SENSITIVE_PATH_PATTERNS = [
    r"C:\",                 # C: drive root
    r"C:\Windows",          # Windows directory
    r"C:\Windows\System32", # System binaries
    r"C:\Program Files",    # Installed programs
    r"C:\ProgramData",      # Application data
    r"C:\Users\*\.ssh",     # User SSH keys
    "*.pem", "*.key",       # Certificate files
    "NTUSER.DAT",           # User registry hive
    "SAM", "SECURITY",      # Security databases
]
```

### Pattern Matching Algorithm

1. **Normalization**: Convert paths to lowercase with forward slashes
2. **Exact Match**: Check if path equals pattern exactly
3. **Wildcard Match**: Use `fnmatch` for patterns with `*` or `?`
4. **Prefix Match**: Check if path is under a sensitive directory
5. **Resolved Path**: Handle symlinks by comparing resolved paths

---

## Data Structures

### Access Request

```python
@dataclass
class AccessRequest:
    id: str                    # UUID for grant tracking
    mcp_name: str              # Name of MCP server
    tool_name: str             # Tool requesting access
    path: str                  # Path being accessed
    code: str                  # Human-readable approval code (XXXX-XXXX)
    status: AccessRequestStatus
    created_at: datetime
    expires_at: datetime       # Request expiry (default: 10 min)
    metadata: dict[str, Any]
```

### Access Grant

```python
@dataclass
class AccessGrant:
    id: str                    # UUID
    request_id: str            # Reference to original request
    mcp_name: str              # Server name
    tool_name: str             # Tool name
    path: str                  # Granted path
    granted_at: datetime
    expires_at: datetime       # Grant expiry
    duration_minutes: int      # Duration in minutes
    approved_by: str           # "cli" or "web"
```

### Config Change Request

```python
@dataclass
class ConfigChangeRequest:
    id: str                    # UUID
    server_name: str           # Server being modified
    change_type: str           # 'add', 'modify', 'remove'
    code: str                  # Approval code (XXXX-XXXX)
    status: AccessRequestStatus
    created_at: datetime
    expires_at: datetime
    sensitive_path: str        # Specific path requiring approval
    path_index: int            # Index in args array
    target_args: list[str]     # Complete new args array
    original_config: dict      # Snapshot before change
    original_config_checksum: str  # SHA256 for race detection
```

---

## API Endpoints

### Create Access Request

When an MCP tool attempts to access a non-allowed path, the gateway creates a pending request.

**Response:**
```json
{
  "allowed": false,
  "request_code": "ABCD-1234"
}
```

### List Pending Requests

```http
GET /api/access/requests/pending
```

**Response:**
```json
{
  "requests": [
    {
      "id": "uuid",
      "code": "ABCD-1234",
      "mcp_name": "filesystem",
      "tool_name": "read_file",
      "path": "/etc/passwd",
      "created_at": "2024-01-01T10:00:00Z",
      "expires_at": "2024-01-01T10:10:00Z"
    }
  ]
}
```

### Approve Access Request

```http
POST /api/access/requests/{code}/approve
Content-Type: application/json

{
  "duration_minutes": 5,
  "approved_by": "cli"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Access granted for 5 minutes",
  "grant": {
    "id": "uuid",
    "mcp_name": "filesystem",
    "path": "/etc/passwd",
    "expires_at": "2024-01-01T10:05:00Z"
  }
}
```

### List Active Grants

```http
GET /api/access/grants/active
```

**Response:**
```json
{
  "grants": [
    {
      "id": "uuid",
      "mcp_name": "filesystem",
      "tool_name": "read_file",
      "path": "/etc/passwd",
      "expires_at": "2024-01-01T10:05:00Z",
      "duration_minutes": 5,
      "approved_by": "cli"
    }
  ]
}
```

---

## Rate Limiting

To prevent brute-force attacks on approval codes:

```python
# Default rate limit: 5 requests per minute per IP
rate_limiter = MemoryRateLimiter(
    requests_per_minute=5,
    burst_size=10
)
```

**Implementation:**
- Token bucket algorithm
- Per-client tracking (by IP address)
- Returns retry-after time when exceeded

---

## Audit Logging

All access events are logged with structured JSON:

```json
{
  "timestamp": "2024-01-01T10:00:00.000Z",
  "event": "access_request_created",
  "mcp_name": "filesystem",
  "tool_name": "read_file",
  "path": "/etc/passwd",
  "request_code": "ABCD-1234",
  "client_ip": "192.168.1.100"
}
```

### Tamper-Evident Chain

Each log entry includes a hash of the previous entry:

```json
{
  "sequence_number": 12345,
  "previous_hash": "abc123...",
  "entry_hash": "def456..."
}
```

This enables verification that the audit log has not been modified.

---

## Security Considerations

### Timing Attacks

When comparing approval codes or checksums:

**❌ Vulnerable:**
```python
if code == stored_code:  # Timing attack possible
    grant_access()
```

**✅ Secure:**
```python
import hmac
if hmac.compare_digest(code, stored_code):
    grant_access()
```

### Race Conditions

When config changes are approved, verify no drift occurred:

```python
current_checksum = compute_config_checksum(current_config)
if current_checksum != request.original_config_checksum:
    return False, "Config changed since request was created"
```

### Path Traversal Prevention

Always resolve paths before comparison:

```python
from pathlib import Path
requested = Path(path).expanduser().resolve()
allowed = Path(allowed_path).expanduser().resolve()
# Compare resolved paths to handle symlinks
```

---

## CLI Approval Command

```bash
# Interactive mode
mcp-gateway approve

# Quick approve with code
mcp-gateway approve ABCD-1234 -d 30

# List pending requests
mcp-gateway list
```

---

## References

- [Python `hmac` module](https://docs.python.org/3/library/hmac.html)
- [Python `pathlib` documentation](https://docs.python.org/3/library/pathlib.html)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
