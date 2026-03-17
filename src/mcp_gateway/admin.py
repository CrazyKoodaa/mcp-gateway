"""Admin functionality for managing MCP server configurations.

Uses aiofiles for non-blocking file I/O operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import GatewayConfig, ServerConfig, load_config

logger = logging.getLogger(__name__)

security = HTTPBasic(auto_error=False)


@dataclass
class AdminConfig:
    """Admin panel configuration."""

    username: str = "admin"
    password: str | None = None
    enabled: bool = False
    secret_key: str | None = None


class ConfigManager:
    """Manages the gateway configuration file with persistence.

    All file operations are async using aiofiles to prevent blocking
    the event loop.
    """

    def __init__(self, config_path: Path, gateway_config: GatewayConfig):
        self.config_path = Path(config_path)
        self.gateway_config = gateway_config
        self._lock = asyncio.Lock()

    async def reload(self) -> GatewayConfig:
        """Reload configuration from disk."""
        self.gateway_config = load_config(self.config_path)
        return self.gateway_config

    async def save(self) -> None:
        """Save current configuration to disk asynchronously."""
        async with self._lock:
            # Use aiofiles for async file I/O
            temp_path = self.config_path.with_suffix(".tmp")

            # Write to temp file
            async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
                config_data = self._serialize_config()
                await f.write(json.dumps(config_data, indent=2))

            # Atomic rename
            temp_path.replace(self.config_path)

            logger.info(f"Configuration saved to {self.config_path}")

    def _serialize_config(self) -> dict[str, Any]:
        """Serialize current config to dict for JSON."""
        return {
            "gateway": {
                "host": self.gateway_config.host,
                "port": self.gateway_config.port,
                "logLevel": self.gateway_config.log_level,
                "enableNamespacing": self.gateway_config.enable_namespacing,
                "namespaceSeparator": self.gateway_config.namespace_separator,
                "apiKey": self.gateway_config.api_key,
                "bearerToken": self.gateway_config.bearer_token,
                "authExcludePaths": self.gateway_config.auth_exclude_paths,
                "connectionTimeout": self.gateway_config.connection_timeout,
                "requestTimeout": self.gateway_config.request_timeout,
            },
            "mcpServers": {
                name: self._serialize_server(server)
                for name, server in self.gateway_config.servers.items()
            },
        }

    def _serialize_server(self, server: ServerConfig) -> dict[str, Any]:
        """Serialize a server config."""
        data: dict[str, Any] = {}

        if server.command:
            data["command"] = server.command
        if server.args is not None:
            data["args"] = server.args
        if server.env:
            data["env"] = server.env
        if server.url:
            data["url"] = server.url
        if server.type:
            data["type"] = server.type
        if server.headers:
            data["headers"] = server.headers
        if server.disabled_tools is not None:
            data["disabledTools"] = server.disabled_tools
        if server.enabled is not None and server.enabled is False:
            data["enabled"] = False

        return data

    async def add_server(self, name: str, config: dict[str, Any]) -> ServerConfig:
        """Add a new MCP server."""
        if name in self.gateway_config.servers:
            raise ValueError(f"Server '{name}' already exists")

        server = self._parse_server_config(name, config)
        self.gateway_config.servers[name] = server
        await self.save()

        logger.info(f"Added server '{name}' to configuration")
        return server

    async def update_server(self, name: str, config: dict[str, Any]) -> ServerConfig:
        """Update an existing MCP server."""
        if name not in self.gateway_config.servers:
            raise ValueError(f"Server '{name}' not found")

        logger.info(f"ConfigManager.update_server for '{name}' with args: {config.get('args', [])}")
        server = self._parse_server_config(name, config)
        logger.info(f"Parsed config for '{name}': command={server.command}, args={server.args}")
        self.gateway_config.servers[name] = server
        await self.save()

        logger.info(f"Updated server '{name}' in configuration")
        return server

    async def remove_server(self, name: str) -> None:
        """Remove an MCP server."""
        if name not in self.gateway_config.servers:
            raise ValueError(f"Server '{name}' not found")

        del self.gateway_config.servers[name]
        await self.save()

        logger.info(f"Removed server '{name}' from configuration")

    def _parse_server_config(self, name: str, config: dict[str, Any]) -> ServerConfig:
        """Parse server config from dict."""
        # Handle both disabledTools formats
        disabled = config.get("disabledTools") or config.get("disabled_tools", [])

        # Parse args
        args = config.get("args", [])
        if isinstance(args, str):
            import shlex

            args = shlex.split(args)

        # Parse command
        cmd = config.get("command")
        if cmd and " " in cmd and not args:
            import shlex

            parts = shlex.split(cmd)
            cmd = parts[0]
            args = parts[1:]

        return ServerConfig(
            name=name,
            command=cmd,
            args=args,
            env=config.get("env", {}),
            url=config.get("url"),
            type=config.get("type"),
            headers=config.get("headers", {}),
            disabled_tools=disabled if isinstance(disabled, list) else [],
            enabled=config.get("enabled", True),
        )


class AdminAuth:
    """Admin authentication handler."""

    def __init__(self, config: AdminConfig):
        self.config = config

    async def __call__(
        self,
        request: Request,
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> bool:
        """Verify admin credentials."""
        # If admin is not enabled, check for API key as fallback
        if not self.config.enabled:
            # Check if API key auth is enabled
            api_key = request.headers.get("X-API-Key")
            if api_key:
                from .auth import AuthConfig

                auth_config = getattr(request.app.state, "auth_config", AuthConfig())
                if auth_config.api_key and secrets.compare_digest(api_key, auth_config.api_key):
                    return True

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin panel is disabled",
            )

        # Require credentials
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )

        # Verify credentials
        if not self.config.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin password not configured",
                headers={"WWW-Authenticate": "Basic"},
            )

        is_correct_username = secrets.compare_digest(credentials.username, self.config.username)
        is_correct_password = secrets.compare_digest(credentials.password, self.config.password)

        if not (is_correct_username and is_correct_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

        return True


def setup_admin(config: GatewayConfig) -> tuple[AdminConfig, ConfigManager | None]:
    """Setup admin configuration and config manager.

    Returns:
        Tuple of (admin_config, config_manager or None if no config path)
    """
    # Create admin config
    admin_config = AdminConfig(
        username=getattr(config, "admin_username", "admin"),
        password=getattr(config, "admin_password", None),
        enabled=bool(getattr(config, "admin_password", None)),
    )

    # Config manager needs a file path
    config_manager = None

    return admin_config, config_manager


def validate_server_config(config: dict[str, Any]) -> tuple[bool, str]:
    """Validate a server configuration.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for required fields
    has_command = bool(config.get("command"))
    has_url = bool(config.get("url"))

    if not has_command and not has_url:
        return (False, "Must specify either 'command' (for stdio) or 'url' (for remote)")

    # Validate type if specified
    server_type = config.get("type", "").lower()
    if server_type and server_type not in ("stdio", "sse", "streamable-http", "streamablehttp"):
        return (False, f"Invalid type '{server_type}'. Must be: stdio, sse, streamable-http")

    # Validate URL format for remote servers
    if has_url:
        url = config.get("url", "")
        if not url.startswith(("http://", "https://")):
            return False, "URL must start with http:// or https://"

    # Validate command is not empty for stdio
    if has_command and not str(config.get("command", "")).strip():
        return False, "Command cannot be empty"

    return True, ""
