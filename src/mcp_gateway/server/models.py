"""Pydantic models for MCP Gateway server API.

This module contains all Pydantic models used for request/response
validation in the MCP Gateway HTTP API.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CallToolRequest(BaseModel):
    """Request body for tool calls.

    Attributes:
        name: Name of the tool to call
        arguments: Arguments for the tool
    """

    name: str = Field(description="Name of the tool to call")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the tool"
    )


class ServerConfigResponse(BaseModel):
    """Server configuration response model.

    Attributes:
        name: Server name
        command: Command to execute (for stdio servers)
        args: Command arguments
        url: Server URL (for remote servers)
        type: Transport type
        disabled_tools: List of disabled tool names
        available_tools: List of available tool names
    """

    name: str
    command: str | None
    args: list[str]
    url: str | None
    type: str | None
    disabled_tools: list[str] = Field(alias="disabledTools")
    available_tools: list[str] = Field(alias="availableTools")

    model_config = {"populate_by_name": True}


class BackendStatusResponse(BaseModel):
    """Backend status response model.

    Attributes:
        name: Backend name
        connected: Whether the backend is connected
        tools: Number of tools available
        type: Transport type (stdio or remote)
        circuit_breaker_state: Current circuit breaker state
    """

    name: str
    connected: bool
    tools: int
    type: str
    circuit_breaker_state: str = Field(default="CLOSED")


class HealthCheckResponse(BaseModel):
    """Health check response model.

    Attributes:
        status: Overall status string
        healthy: Whether the gateway is healthy
        total_backends: Total number of backends
        connected_backends: Number of connected backends
        total_tools: Total number of tools
        backends: List of backend status details
    """

    status: str
    healthy: bool
    total_backends: int
    connected_backends: int
    total_tools: int
    backends: list[BackendStatusResponse]


class CircuitBreakerStats(BaseModel):
    """Circuit breaker statistics.

    Attributes:
        name: Backend name
        state: Current state (CLOSED, OPEN, HALF_OPEN)
        failure_count: Number of consecutive failures
        success_count: Number of consecutive successes
        last_failure_time: Timestamp of last failure (optional)
        retry_after: Seconds until next retry attempt
    """

    name: str
    state: str
    failure_count: int
    success_count: int
    last_failure_time: float | None = None
    retry_after: float
