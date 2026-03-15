"""Circuit breaker pattern implementation for resilient backend calls.

The circuit breaker pattern prevents cascading failures by stopping requests
to failing backends and allowing them time to recover.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from enum import Enum, auto
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from .exceptions import CircuitBreakerOpenError as CircuitBreakerOpen

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = auto()      # Normal operation, requests pass through
    OPEN = auto()        # Failure threshold reached, requests blocked
    HALF_OPEN = auto()   # Testing if service has recovered


class CircuitBreaker:
    """Circuit breaker for protecting backend calls.

    The circuit breaker monitors failures and opens when the failure threshold
    is reached, preventing further calls for a recovery period.

    Example:
        >>> breaker = CircuitBreaker("my_backend", failure_threshold=5)
        >>>
        >>> @breaker
        >>> async def call_backend():
        ...     return await make_request()
        >>>
        >>> try:
        ...     result = await call_backend()
        ... except CircuitBreakerOpen:
        ...     # Use fallback
        ...     pass
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type[Exception] = Exception,
        half_open_max_calls: int = 3,
    ):
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that counts as failure
            half_open_max_calls: Max calls allowed in half-open state
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Whether circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Whether circuit is open (failing fast)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Whether circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    async def call(
        self,
        func: Callable[P, Coroutine[Any, Any, T]],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> T:
        """Call a function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from func

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: Any exception raised by func
        """
        async with self._lock:
            current_state = self._state
            await self._update_state()

            if current_state != self._state:
                logger.info(
                    f"[CIRCUIT] State transition for '{self.name}': "
                    f"{current_state.name.upper()} -> {self._state.name.upper()}"
                )

            if self._state == CircuitState.OPEN:
                retry_after = self._get_retry_after()
                logger.warning(
                    f"[CIRCUIT] Circuit '{self.name}' OPEN - rejecting request. "
                    f"Failures: {self._failure_count}, Retry after: {retry_after:.1f}s"
                )
                raise CircuitBreakerOpen(
                    f"Circuit breaker '{self.name}' is open. Retry after {retry_after:.1f}s",
                    backend_name=self.name,
                    retry_after=retry_after,
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    retry_after = self._get_retry_after()
                    logger.warning(
                        f"[CIRCUIT] Circuit '{self.name}' HALF_OPEN max calls reached. "
                        f"Current calls: {self._half_open_calls}/{self.half_open_max_calls}"
                    )
                    raise CircuitBreakerOpen(
                        f"Circuit breaker '{self.name}' is open. Retry after {retry_after:.1f}s",
                        backend_name=self.name,
                        retry_after=retry_after,
                    )
                self._half_open_calls += 1
                logger.debug(
                    f"[CIRCUIT] Circuit '{self.name}' HALF_OPEN - call {self._half_open_calls} "
                    f"/ {self.half_open_max_calls}"
                )

        # Execute outside the lock
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.expected_exception as e:
            await self._on_failure()
            logger.warning(
                f"[CIRCUIT] Circuit '{self.name}' failure detected: {type(e).__name__}: {e}"
            )
            raise

    def __call__(
        self,
        func: Callable[P, Coroutine[Any, Any, T]]
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        """Decorator to wrap a function with circuit breaker."""
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await self.call(func, *args, **kwargs)

        # Attach circuit breaker reference for inspection
        wrapper._circuit_breaker = self  # type: ignore[attr-defined]
        return wrapper

    async def _update_state(self) -> None:
        """Update circuit state based on time and failures."""
        if (self._state == CircuitState.OPEN and
            self._last_failure_time is not None):
            # Check if recovery timeout has passed
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info(
                    f"[CIRCUIT] State transition for '{self.name}': "
                    f"OPEN -> HALF_OPEN (recovery timeout elapsed: {elapsed:.1f}s)"
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(
                    f"[CIRCUIT] Circuit '{self.name}' HALF_OPEN success #{self._success_count} "
                    f"/ {self.half_open_max_calls}"
                )
                # If we've had enough successes, close the circuit
                if self._success_count >= self.half_open_max_calls:
                    logger.info(
                        f"[CIRCUIT] State transition for '{self.name}': "
                        f"HALF_OPEN -> CLOSED (recovery successful after {self._failure_count} failures)"
                    )
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                if self._failure_count > 0:
                    old_count = self._failure_count
                    self._failure_count = 0
                    logger.debug(
                        f"[CIRCUIT] Circuit '{self.name}' failure count reset: {old_count} -> 0"
                    )

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            logger.debug(
                f"[CIRCUIT] Circuit '{self.name}' failure #{self._failure_count} "
                f"/ {self.failure_threshold}"
            )
            # Check if we should open the circuit
            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    logger.warning(
                        f"[CIRCUIT] State transition for '{self.name}': "
                        f"CLOSED -> OPEN (failure threshold reached: {self._failure_count}/{self.failure_threshold})"
                    )
                    self._state = CircuitState.OPEN
            elif self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open state immediately reopens the circuit
                logger.warning(
                    f"[CIRCUIT] State transition for '{self.name}': "
                    f"HALF_OPEN -> OPEN (failure during recovery test)"
                )
                self._state = CircuitState.OPEN
                self._half_open_calls = 0

    def _get_retry_after(self) -> float:
        """Calculate seconds until next retry attempt."""
        if self._last_failure_time is None:
            return 0.0

        elapsed = time.time() - self._last_failure_time
        remaining = self.recovery_timeout - elapsed
        return max(0.0, remaining)

    def get_stats(self) -> dict[str, object]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "retry_after": self._get_retry_after() if self.is_open else 0.0,
        }

    async def force_close(self) -> None:
        """Manually close the circuit (for testing/admin)."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            logger.info(f"Circuit breaker '{self.name}' manually closed")

    async def force_open(self) -> None:
        """Manually open the circuit (for maintenance)."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.time()
            logger.warning(f"Circuit breaker '{self.name}' manually opened")


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> CircuitBreaker:
        """Get existing circuit breaker or create new one."""
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
            return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Get circuit breaker by name."""
        return self._breakers.get(name)

    def get_all_stats(self) -> dict[str, dict[str, object]]:
        """Get stats for all circuit breakers."""
        return {name: cb.get_stats() for name, cb in self._breakers.items()}

    async def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.force_close()
