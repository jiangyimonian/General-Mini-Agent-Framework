"""Rate limit policy for model request governance."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateLimitPolicy:
    """Configuration for rate limiting with token bucket algorithm.

    Attributes:
        requests_per_minute: Maximum requests allowed per minute.
        burst: Maximum burst capacity (tokens in bucket).
    """

    requests_per_minute: int
    burst: int

    def __post_init__(self) -> None:
        if not isinstance(self.requests_per_minute, int):
            raise TypeError("requests_per_minute must be an integer")
        if isinstance(self.requests_per_minute, bool):
            raise TypeError("requests_per_minute must be an integer")
        if self.requests_per_minute < 1:
            raise ValueError("requests_per_minute must be at least 1")
        if not isinstance(self.burst, int):
            raise TypeError("burst must be an integer")
        if isinstance(self.burst, bool):
            raise TypeError("burst must be an integer")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")

    def _create_bucket(self) -> _TokenBucket:
        """Create a token bucket for this policy."""
        return _TokenBucket(
            capacity=self.burst,
            refill_rate=self.requests_per_minute / 60.0,  # tokens per second
        )


@dataclass
class _TokenBucket:
    """Token bucket for rate limiting."""

    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        # Start with full bucket
        self.tokens = self.capacity

    def _refill(self, now: float) -> None:
        """Refill tokens based on elapsed time."""
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

    def try_acquire(self, now: float) -> bool:
        """Try to acquire a token. Returns True if successful."""
        with self.lock:
            self._refill(now)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    def time_until_available(self, now: float) -> float:
        """Get time until a token is available."""
        with self.lock:
            self._refill(now)
            if self.tokens >= 1.0:
                return 0.0
            # Time until we have 1 token
            tokens_needed = 1.0 - self.tokens
            return tokens_needed / self.refill_rate


class RateLimiter:
    """Rate limiter instance with acquire methods."""

    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy
        self._bucket = policy._create_bucket()
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

    def try_acquire(self) -> bool:
        """Try to acquire a token without blocking.

        Returns:
            True if a token was acquired, False if rate limited.
        """
        with self._sync_lock:
            now = time.monotonic()
            return self._bucket.try_acquire(now)

    def acquire_sync(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Acquire a token, blocking if necessary.

        Args:
            clock: Optional clock function for testing (default: time.monotonic).
            sleeper: Optional sleep function for testing (default: time.sleep).
            timeout: Maximum time to wait (default: None = forever).

        Returns:
            True if acquired, False if timeout.
        """
        clock = clock or time.monotonic
        sleeper = sleeper or time.sleep
        start = clock()

        while True:
            with self._sync_lock:
                now = clock()
                if self._bucket.try_acquire(now):
                    return True

                wait_time = self._bucket.time_until_available(now)
                if timeout is not None:
                    elapsed = now - start
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        return False
                    wait_time = min(wait_time, remaining)

            if wait_time > 0:
                sleeper(wait_time)

    async def acquire_async(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], asyncio.coroutine] | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Acquire a token asynchronously, blocking if necessary.

        Args:
            clock: Optional clock function for testing (default: time.monotonic).
            sleeper: Optional async sleep function for testing (default: asyncio.sleep).
            timeout: Maximum time to wait (default: None = forever).

        Returns:
            True if acquired, False if timeout.

        Raises:
            asyncio.CancelledError: If the wait is cancelled.
        """
        clock = clock or time.monotonic
        sleeper = sleeper or asyncio.sleep
        start = clock()

        while True:
            async with self._async_lock:
                now = clock()
                if self._bucket.try_acquire(now):
                    return True

                wait_time = self._bucket.time_until_available(now)
                if timeout is not None:
                    elapsed = now - start
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        return False
                    wait_time = min(wait_time, remaining)

            if wait_time > 0:
                await sleeper(wait_time)