"""Explicit retry policy for orchestration boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior with exponential backoff.

    Attributes:
        max_attempts: Maximum number of attempts (including the initial call).
        initial_delay_seconds: Initial delay before first retry.
        max_delay_seconds: Maximum delay cap for exponential backoff.
        multiplier: Multiplier for exponential backoff (default 2.0).
    """

    max_attempts: int
    initial_delay_seconds: float
    max_delay_seconds: float
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise TypeError("max_attempts must be an integer")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not isinstance(self.initial_delay_seconds, (int, float)):
            raise TypeError("initial_delay_seconds must be a number")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be non-negative")
        if not isinstance(self.max_delay_seconds, (int, float)):
            raise TypeError("max_delay_seconds must be a number")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be at least initial_delay_seconds")
        if not isinstance(self.multiplier, (int, float)):
            raise TypeError("multiplier must be a number")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay for a given attempt (0-indexed).

        Args:
            attempt: The attempt number (0 for first retry).

        Returns:
            Delay in seconds before the next attempt.
        """
        if attempt < 0:
            raise ValueError("attempt must be non-negative")
        # Exponential backoff: delay = initial * multiplier^attempt
        delay = self.initial_delay_seconds * (self.multiplier**attempt)
        return min(delay, self.max_delay_seconds)

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if an error should trigger a retry.

        Args:
            error: The exception that occurred.
            attempt: Current attempt number (1-indexed, 1 = first call).

        Returns:
            True if the operation should be retried, False otherwise.
        """
        # Never catch CancelledError
        if isinstance(error, asyncio.CancelledError):
            return False
        # Check attempt limit
        if attempt >= self.max_attempts:
            return False
        # Check error type for retryable errors
        return self._is_retryable_error(error)

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable.

        Retryable errors:
        - Timeout errors
        - Connection errors
        - Temporary server errors (5xx)
        - Rate limit errors (429)

        Non-retryable errors:
        - Authentication errors (401)
        - Authorization errors (403)
        - Validation errors (400)
        - Not found errors (404)
        """
        error_type = type(error).__name__
        error_message = str(error).lower()

        # Timeout errors
        if "timeout" in error_type.lower() or "timeout" in error_message:
            return True

        # Connection errors
        if "connection" in error_type.lower() or "connection" in error_message:
            return True

        # Network errors
        if "network" in error_type.lower() or "network" in error_message:
            return True

        # Check for HTTP status indicators in error message
        # Retryable: 429 (rate limit), 500-504 (server errors)
        if "429" in error_message or "rate limit" in error_message:
            return True
        if any(str(code) in error_message for code in range(500, 505)):
            return True
        if "5xx" in error_message or "server error" in error_message:
            return True

        # Non-retryable: 401, 403, 400, 404
        if any(str(code) in error_message for code in (400, 401, 403, 404)):
            return False

        # Authentication/authorization errors
        if "auth" in error_type.lower() or "auth" in error_message:
            return False

        # Validation errors
        if "valid" in error_type.lower() or "valid" in error_message:
            return False

        # Default: retry for unknown errors (conservative approach)
        return True


async def execute_with_retry(
    operation: Callable[[], asyncio.coroutine],
    policy: RetryPolicy,
    *,
    sleeper: Callable[[float], asyncio.coroutine] | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> tuple[bool, Exception | None]:
    """Execute an operation with retry policy.

    Args:
        operation: Async callable to execute.
        policy: Retry policy configuration.
        sleeper: Optional async sleep function for testing (default: asyncio.sleep).
        on_retry: Optional callback called before each retry with (attempt, error, delay).

    Returns:
        Tuple of (success, error) where error is None on success.

    Raises:
        asyncio.CancelledError: If the operation or retry is cancelled.
    """
    sleeper = sleeper or asyncio.sleep
    attempt = 0

    while True:
        attempt += 1
        try:
            await operation()
            return True, None
        except asyncio.CancelledError:
            # Re-raise CancelledError without catching
            raise
        except Exception as e:
            if not policy.should_retry(e, attempt):
                return False, e
            if attempt >= policy.max_attempts:
                return False, e

            # Calculate delay and sleep
            delay = policy.delay_for_attempt(attempt - 1)
            if on_retry:
                on_retry(attempt, e, delay)
            await sleeper(delay)