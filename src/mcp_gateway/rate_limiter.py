"""Rate limiting for MCP Gateway API endpoints.

Provides token bucket rate limiting for approval code attempts
to prevent brute force attacks.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed
        remaining: Number of remaining requests in window
        reset_time: Unix timestamp when the rate limit resets
        retry_after: Seconds to wait before retry (if denied)
    """

    allowed: bool
    remaining: int
    reset_time: float
    retry_after: float = 0.0


class RateLimiter(Protocol):
    """Protocol for rate limiters."""

    def check(self, key: str) -> RateLimitResult:
        """Check if a request is allowed for the given key."""
        ...

    def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        ...


@dataclass
class TokenBucket:
    """Token bucket for rate limiting.

    Simple token bucket that refills at a constant rate.

    Attributes:
        capacity: Maximum tokens in bucket
        tokens: Current tokens available
        last_update: Last time bucket was updated
        refill_rate: Tokens added per second
    """

    capacity: int
    tokens: float = field(default=0.0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = 1.0  # tokens per second

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self) -> None:
        """Refill bucket based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_update = now

    @property
    def available(self) -> int:
        """Current available tokens."""
        self._refill()
        return int(self.tokens)


class MemoryRateLimiter:
    """In-memory rate limiter using token buckets.

    This implementation stores rate limits in memory and is
    suitable for single-instance deployments.

    For multi-instance deployments, use a Redis-backed limiter.

    Example:
        >>> limiter = MemoryRateLimiter(
        ...     requests_per_minute=5,
        ...     burst_size=10
        ... )
        >>> result = limiter.check("approval_code_attempts")
        >>> if not result.allowed:
        ...     print(f"Retry after {result.retry_after} seconds")
    """

    def __init__(
        self,
        requests_per_minute: int = 5,
        burst_size: int | None = None,
        cleanup_interval_seconds: int = 300,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            requests_per_minute: Rate limit (default 5)
            burst_size: Maximum burst size (default 2x rate limit)
            cleanup_interval_seconds: How often to clean up stale entries
        """
        self._requests_per_minute = requests_per_minute
        self._burst_size = burst_size or requests_per_minute * 2
        self._refill_rate = requests_per_minute / 60.0

        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

        # Start cleanup task
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_interval = cleanup_interval_seconds
        self._start_cleanup()

    def _start_cleanup(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def start(self) -> None:
        """Start the rate limiter.

        Note: Cleanup task is already started in __init__.
        This method exists for lifecycle compatibility.
        """
        self._start_cleanup()

    async def stop(self) -> None:
        """Stop the cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def check(self, key: str) -> RateLimitResult:
        """Check if a request is allowed for the given key.

        Args:
            key: Identifier for the rate limit bucket (e.g., IP address, user ID)

        Returns:
            RateLimitResult with allowance status
        """
        async with self._lock:
            now = time.time()

            # Get or create bucket
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    capacity=self._burst_size,
                    tokens=self._burst_size,
                    last_update=now,
                    refill_rate=self._refill_rate,
                )

            bucket = self._buckets[key]

            # Try to consume token
            allowed = bucket.consume(1)
            remaining = bucket.available

            # Calculate reset time
            if allowed:
                reset_time = now + (1 - bucket.tokens) / self._refill_rate
                retry_after = 0.0
            else:
                # Need to wait for 1 token
                reset_time = now + 1 / self._refill_rate
                retry_after = 1 / self._refill_rate

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_time=reset_time,
                retry_after=retry_after,
            )

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key.

        Useful after successful authentication.
        """
        async with self._lock:
            if key in self._buckets:
                del self._buckets[key]

    async def _cleanup_loop(self) -> None:
        """Background cleanup of stale buckets."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_stale()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Don't let cleanup errors crash the service

    async def _cleanup_stale(self) -> None:
        """Remove buckets that haven't been used recently."""
        async with self._lock:
            now = time.time()
            stale_keys = [
                key
                for key, bucket in self._buckets.items()
                if now - bucket.last_update > 3600  # 1 hour stale
            ]
            for key in stale_keys:
                del self._buckets[key]


class RateLimitMiddleware:
    """Middleware for applying rate limits to API endpoints.

    Usage with FastAPI:
        >>> from fastapi import Request, HTTPException
        >>> limiter = MemoryRateLimiter(requests_per_minute=5)
        >>>
        >>> @app.post("/api/approve")
        >>> async def approve(request: Request):
        ...     client_ip = request.client.host
        ...     result = await limiter.check(f"approve:{client_ip}")
        ...     if not result.allowed:
        ...         raise HTTPException(
        ...             status_code=429,
        ...             detail=f"Rate limit exceeded. Retry after {result.retry_after}s"
        ...         )
        ...     # Process approval...
    """

    def __init__(
        self,
        limiter: RateLimiter,
        key_func: callable = None,
    ) -> None:
        """Initialize middleware.

        Args:
            limiter: Rate limiter instance
            key_func: Function to extract key from request (default: client IP)
        """
        self._limiter = limiter
        self._key_func = key_func or self._default_key_func

    @staticmethod
    def _default_key_func(request) -> str:
        """Default key extraction (client IP)."""
        if hasattr(request, "client") and request.client:
            return str(request.client.host)
        return "unknown"

    async def check(self, request) -> RateLimitResult:
        """Check rate limit for a request."""
        key = self._key_func(request)
        return await self._limiter.check(key)
