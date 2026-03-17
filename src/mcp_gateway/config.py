"""Configuration loading and validation using Pydantic.

This module provides Pydantic models for MCP Gateway configuration,
supporting both programatic creation and loading from JSON files.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class ServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Supports stdio servers (command-based) and remote servers (URL-based).

    Examples:
        >>> # For testing - minimal config with just name
        >>> config = ServerConfig(name="test-server")

        >>> # Stdio server with command
        >>> config = ServerConfig(
        ...     name="memory",
        ...     command="npx",
        ...     args=["-y", "@modelcontextprotocol/server-memory"]
        ... )

        >>> # Remote server with URL
        >>> config = ServerConfig(
        ...     name="remote",
        ...     url="https://example.com/mcp",
        ...     type="streamable-http"
        ... )
    """

    name: str = Field(description="Unique name for this server")

    # For stdio servers
    command: str | None = Field(default=None, description="Command to execute for stdio servers")
    args: list[str] = Field(default_factory=list, description="Arguments for the command")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables for the server"
    )

    # For remote servers
    url: str | None = Field(default=None, description="URL for remote MCP servers")
    type: Literal["stdio", "sse", "streamable-http", "streamablehttp"] | None = Field(
        default=None, description="Transport type for remote servers"
    )

    # Headers for remote connections
    headers: dict[str, str] = Field(
        default_factory=dict, description="HTTP headers for remote connections"
    )

    # Tool filtering
    disabled_tools: list[str] = Field(
        default_factory=list, description="List of tool names to disable"
    )

    # Server enable/disable
    enabled: bool = Field(default=True, description="Whether this server is enabled")

    @field_validator("args", mode="before")
    @classmethod
    def parse_args(cls, v: Any) -> list[str]:
        """Parse args from string or list."""
        if isinstance(v, str):
            return shlex.split(v)
        if v is None:
            return []
        return list(v)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: str | None) -> str | None:
        """Normalize transport type names."""
        if v is None:
            return None
        normalized = v.lower().replace("_", "-")
        if normalized == "streamablehttp":
            return "streamable-http"
        return normalized  # type: ignore[return-value]

    @field_validator("command", mode="before")
    @classmethod
    def parse_command(cls, v: Any) -> Any:
        """Parse command string that may contain args.

        If command contains spaces and args is empty, split the command
        and populate args with the remainder.
        """
        if isinstance(v, str) and " " in v:
            # Command contains spaces - we'll handle splitting in model_validator
            return v
        return v

    @model_validator(mode="after")
    def split_command_with_args(self) -> Self:
        """Split command string into command and args if needed."""
        if self.command is not None and " " in self.command:
            # Split command by spaces
            parts = shlex.split(self.command)
            if len(parts) > 1:
                self.command = parts[0]
                # Prepend parsed args to existing args
                self.args = parts[1:] + self.args
        return self

    @model_validator(mode="after")
    def validate_stdio_or_remote(self) -> Self:
        """Ensure server has either command or url when both are provided.

        Note: For testing, a server can be created with just a name.
        Validation only fails when trying to connect without command or url.
        """
        # Allow creation with just name (for testing)
        # Only validate when there's actual configuration
        if self.command is not None or self.url is not None:
            # At least one is provided, check for conflict
            if self.command is not None and self.url is not None:
                raise ValueError("Server cannot have both 'command' and 'url'")
        return self

    @model_validator(mode="after")
    def validate_command_not_empty(self) -> Self:
        """Ensure command is not empty if provided."""
        if self.command is not None and not self.command.strip():
            raise ValueError("Command cannot be empty")
        return self

    @model_validator(mode="after")
    def validate_url_format(self) -> Self:
        """Ensure URL has proper format for remote servers."""
        if self.url is not None:
            if not self.url.startswith(("http://", "https://")):
                raise ValueError("URL must start with http:// or https://")
        return self

    @property
    def is_stdio(self) -> bool:
        """Check if this is a stdio server."""
        return self.command is not None

    @property
    def is_remote(self) -> bool:
        """Check if this is a remote server."""
        return self.url is not None

    @property
    def transport_type(self) -> str:
        """Get the transport type."""
        if self.type:
            return self.type
        if self.url:
            return "streamable-http"
        return "stdio"


class GatewaySettings(BaseModel):
    """Gateway-wide settings.

    This model contains all gateway configuration options that are
    not specific to individual MCP servers.
    """

    host: str = Field(default="127.0.0.1", description="Host to bind to")
    port: int = Field(default=3000, ge=1, le=65535, description="Port to listen on")
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")

    # Tool namespacing options
    enable_namespacing: bool = Field(default=True, description="Enable tool namespacing")
    namespace_separator: str = Field(
        default="__", description="Separator for namespaced tool names"
    )

    # Authentication
    api_key: str | None = Field(default=None, description="API key for authentication")
    bearer_token: str | None = Field(default=None, description="Bearer token for authentication")
    auth_exclude_paths: list[str] = Field(
        default_factory=lambda: ["/health", "/metrics", "/docs", "/openapi.json"],
        description="Paths excluded from authentication",
    )

    # Timeouts
    connection_timeout: float = Field(
        default=30.0, ge=0, description="Connection timeout in seconds"
    )
    request_timeout: float = Field(default=60.0, ge=0, description="Request timeout in seconds")

    # Admin panel
    admin_username: str = Field(default="admin", description="Admin panel username")
    admin_password: str | None = Field(default=None, description="Admin panel password")

    # Circuit breaker settings
    circuit_breaker_enabled: bool = Field(default=True, description="Enable circuit breaker")
    circuit_breaker_failure_threshold: int = Field(
        default=5, ge=1, description="Failures before opening circuit"
    )
    circuit_breaker_recovery_timeout: float = Field(
        default=30.0, ge=0, description="Seconds before attempting recovery"
    )
    circuit_breaker_expected_exception: str = Field(
        default="Exception", description="Exception type that triggers circuit breaker"
    )

    # Structured logging
    structured_logging: bool = Field(default=True, description="Enable structured JSON logging")

    model_config = {"extra": "forbid"}  # Reject unknown fields


class GatewayConfig(BaseModel):
    """Complete gateway configuration.

    This is the top-level configuration model that combines
    gateway settings and MCP server configurations.

    Examples:
        >>> # Default configuration
        >>> config = GatewayConfig()

        >>> # With custom values using property forwarding
        >>> config = GatewayConfig(
        ...     host="0.0.0.0",
        ...     port=8080,
        ...     log_level="DEBUG"
        ... )

        >>> # With nested structure
        >>> config = GatewayConfig(
        ...     gateway=GatewaySettings(host="0.0.0.0", port=8080),
        ...     mcp_servers={"memory": ServerConfig(name="memory", command="npx")}
        ... )
    """

    gateway: GatewaySettings = Field(
        default_factory=GatewaySettings, description="Gateway-wide settings"
    )
    mcp_servers: dict[str, ServerConfig] = Field(
        default_factory=dict, description="MCP server configurations", alias="servers"
    )

    model_config = {"extra": "forbid", "populate_by_name": True}  # Reject unknown fields

    def __init__(self, **data: Any) -> None:
        """Initialize GatewayConfig with property forwarding support.

        Allows direct setting of gateway properties at the top level:
        GatewayConfig(host="0.0.0.0", port=8080) works via property forwarding.
        """
        # Extract gateway-specific fields for forwarding
        gateway_fields = {
            "host",
            "port",
            "log_level",
            "enable_namespacing",
            "namespace_separator",
            "api_key",
            "bearer_token",
            "auth_exclude_paths",
            "connection_timeout",
            "request_timeout",
            "admin_username",
            "admin_password",
            "circuit_breaker_enabled",
            "circuit_breaker_failure_threshold",
            "circuit_breaker_recovery_timeout",
            "circuit_breaker_expected_exception",
            "structured_logging",
        }

        # Separate gateway fields from other data
        gateway_overrides: dict[str, Any] = {}
        other_data: dict[str, Any] = {}

        for key, value in data.items():
            if key in gateway_fields:
                gateway_overrides[key] = value
            else:
                other_data[key] = value

        # If gateway object was provided, merge with overrides
        if "gateway" in other_data:
            existing_gateway = other_data["gateway"]
            if isinstance(existing_gateway, dict):
                # Merge overrides with existing gateway dict
                merged_gateway = {**existing_gateway, **gateway_overrides}
                other_data["gateway"] = merged_gateway
            elif isinstance(existing_gateway, GatewaySettings):
                # Can't easily merge with existing GatewaySettings object
                # Just use overrides if provided, otherwise keep existing
                if gateway_overrides:
                    other_data["gateway"] = GatewaySettings(
                        **{**existing_gateway.model_dump(), **gateway_overrides}
                    )
        elif gateway_overrides:
            # Create new gateway settings with overrides
            other_data["gateway"] = GatewaySettings(**gateway_overrides)

        super().__init__(**other_data)

    @property
    def host(self) -> str:
        """Shortcut to gateway host."""
        return self.gateway.host

    @host.setter
    def host(self, value: str) -> None:
        self.gateway.host = value

    @property
    def port(self) -> int:
        """Shortcut to gateway port."""
        return self.gateway.port

    @port.setter
    def port(self, value: int) -> None:
        self.gateway.port = value

    @property
    def log_level(self) -> str:
        """Shortcut to gateway log level."""
        return self.gateway.log_level

    @log_level.setter
    def log_level(self, value: str) -> None:
        self.gateway.log_level = value

    @property
    def enable_namespacing(self) -> bool:
        """Shortcut to namespacing setting."""
        return self.gateway.enable_namespacing

    @property
    def namespace_separator(self) -> str:
        """Shortcut to namespace separator."""
        return self.gateway.namespace_separator

    @namespace_separator.setter
    def namespace_separator(self, value: str) -> None:
        self.gateway.namespace_separator = value

    @property
    def api_key(self) -> str | None:
        """Shortcut to API key."""
        return self.gateway.api_key

    @property
    def bearer_token(self) -> str | None:
        """Shortcut to bearer token."""
        return self.gateway.bearer_token

    @property
    def auth_exclude_paths(self) -> list[str]:
        """Shortcut to auth excluded paths."""
        return self.gateway.auth_exclude_paths

    @property
    def connection_timeout(self) -> float:
        """Shortcut to connection timeout."""
        return self.gateway.connection_timeout

    @property
    def request_timeout(self) -> float:
        """Shortcut to request timeout."""
        return self.gateway.request_timeout

    @property
    def admin_username(self) -> str:
        """Shortcut to admin username."""
        return self.gateway.admin_username

    @property
    def admin_password(self) -> str | None:
        """Shortcut to admin password."""
        return self.gateway.admin_password

    @property
    def servers(self) -> dict[str, ServerConfig]:
        """Shortcut to mcp_servers."""
        return self.mcp_servers


def load_config(path: str | Path) -> GatewayConfig:
    """Load configuration from JSON file.

    Supports both camelCase (legacy) and snake_case field names.
    Handles automatic conversion between formats for backward compatibility.

    Args:
        path: Path to the configuration file

    Returns:
        Validated GatewayConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config is invalid
        json.JSONDecodeError: If file contains invalid JSON

    Example:
        >>> config = load_config("config.json")
        >>> print(f"Gateway on {config.host}:{config.port}")
        >>> for name, server in config.servers.items():
        ...     print(f"  Server: {name}")
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Handle legacy config format where settings are under "gateway" key
    # but servers are under "mcpServers" key
    config_data: dict[str, Any] = {}

    if "gateway" in data:
        # New format or mixed format
        gateway_data = data["gateway"].copy()

        # Normalize field names (camelCase to snake_case)
        field_mapping = {
            "logLevel": "log_level",
            "enableNamespacing": "enable_namespacing",
            "namespaceSeparator": "namespace_separator",
            "apiKey": "api_key",
            "api_key": "api_key",  # Already snake_case
            "bearerToken": "bearer_token",
            "bearer_token": "bearer_token",
            "authExcludePaths": "auth_exclude_paths",
            "auth_exclude_paths": "auth_exclude_paths",
            "connectionTimeout": "connection_timeout",
            "connection_timeout": "connection_timeout",
            "requestTimeout": "request_timeout",
            "request_timeout": "request_timeout",
            "adminUsername": "admin_username",
            "admin_username": "admin_username",
            "adminPassword": "admin_password",
            "admin_password": "admin_password",
            "circuitBreakerEnabled": "circuit_breaker_enabled",
            "circuit_breaker_enabled": "circuit_breaker_enabled",
            "circuitBreakerFailureThreshold": "circuit_breaker_failure_threshold",
            "circuitBreakerRecoveryTimeout": "circuit_breaker_recovery_timeout",
            "structuredLogging": "structured_logging",
            "structured_logging": "structured_logging",
        }

        for old_key, new_key in field_mapping.items():
            if old_key in gateway_data and old_key != new_key:
                gateway_data[new_key] = gateway_data.pop(old_key)

        config_data["gateway"] = gateway_data
    else:
        config_data["gateway"] = {}

    # Handle servers
    if "mcpServers" in data:
        servers: dict[str, Any] = {}
        for name, server_data in data["mcpServers"].items():
            server_copy = server_data.copy()
            server_copy["name"] = name

            # Normalize server field names
            if "disabledTools" in server_copy:
                server_copy["disabled_tools"] = server_copy.pop("disabledTools")
            if "disabled_tools" not in server_copy:
                server_copy["disabled_tools"] = []

            # Handle enabled field (default to True if not specified)
            if "enabled" not in server_copy:
                server_copy["enabled"] = True

            servers[name] = server_copy
        config_data["mcp_servers"] = servers
    else:
        config_data["mcp_servers"] = {}

    return GatewayConfig.model_validate(config_data)


def save_config(config: GatewayConfig, path: str | Path) -> None:
    """Save configuration to JSON file.

    Saves in the legacy format (camelCase) for backward compatibility.

    Args:
        config: Configuration to save
        path: Path to save to

    Example:
        >>> config = GatewayConfig()
        >>> save_config(config, "config.json")
    """
    path = Path(path)

    # Convert to dict
    data = config.model_dump(by_alias=False)

    # Convert back to legacy format for backward compatibility
    output: dict[str, Any] = {"gateway": {}, "mcpServers": {}}

    # Gateway settings with camelCase keys
    gw = data["gateway"]
    output["gateway"] = {
        "host": gw["host"],
        "port": gw["port"],
        "logLevel": gw["log_level"],
        "enableNamespacing": gw["enable_namespacing"],
        "namespaceSeparator": gw["namespace_separator"],
        "apiKey": gw["api_key"],
        "bearerToken": gw["bearer_token"],
        "authExcludePaths": gw["auth_exclude_paths"],
        "connectionTimeout": gw["connection_timeout"],
        "requestTimeout": gw["request_timeout"],
        "adminUsername": gw["admin_username"],
        "adminPassword": gw["admin_password"],
    }

    # Remove None values
    output["gateway"] = {k: v for k, v in output["gateway"].items() if v is not None}

    # Servers
    for name, server in data["mcp_servers"].items():
        server_output: dict[str, Any] = {}

        if server.get("command"):
            server_output["command"] = server["command"]
        if server.get("args"):
            server_output["args"] = server["args"]
        if server.get("env"):
            server_output["env"] = server["env"]
        if server.get("url"):
            server_output["url"] = server["url"]
        if server.get("type"):
            server_output["type"] = server["type"]
        if server.get("headers"):
            server_output["headers"] = server["headers"]
        if server.get("disabled_tools"):
            server_output["disabledTools"] = server["disabled_tools"]
        if server.get("enabled") is not None and server.get("enabled") is False:
            server_output["enabled"] = False

        output["mcpServers"][name] = server_output

    # Write atomically
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    temp_path.replace(path)
