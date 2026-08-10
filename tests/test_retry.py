"""Tests for retry policy."""

import asyncio

import pytest

from general_mini_agent.retry import RetryPolicy, execute_with_retry


class TestRetryPolicy:
    """Tests for RetryPolicy configuration."""

    def test_valid_policy_creation(self) -> None:
        """Valid policy can be created."""
        policy = RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.1,
            max_delay_seconds=10.0,
            multiplier=2.0,
        )
        assert policy.max_attempts == 3
        assert policy.initial_delay_seconds == 0.1
        assert policy.max_delay_seconds == 10.0
        assert policy.multiplier == 2.0

    def test_max_attempts_must_be_positive(self) -> None:
        """max_attempts must be at least 1."""
        with pytest.raises(ValueError, match="at least 1"):
            RetryPolicy(max_attempts=0, initial_delay_seconds=0.1, max_delay_seconds=10.0)

        with pytest.raises(ValueError, match="at least 1"):
            RetryPolicy(max_attempts=-1, initial_delay_seconds=0.1, max_delay_seconds=10.0)

    def test_initial_delay_must_be_non_negative(self) -> None:
        """initial_delay_seconds must be non-negative."""
        with pytest.raises(ValueError, match="non-negative"):
            RetryPolicy(max_attempts=3, initial_delay_seconds=-0.1, max_delay_seconds=10.0)

    def test_max_delay_must_be_at_least_initial(self) -> None:
        """max_delay_seconds must be at least initial_delay_seconds."""
        with pytest.raises(ValueError, match="at least initial"):
            RetryPolicy(max_attempts=3, initial_delay_seconds=1.0, max_delay_seconds=0.5)

    def test_multiplier_must_be_at_least_one(self) -> None:
        """multiplier must be at least 1."""
        with pytest.raises(ValueError, match="at least 1"):
            RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=0.1,
                max_delay_seconds=10.0,
                multiplier=0.5,
            )

    def test_delay_for_first_attempt(self) -> None:
        """Delay for attempt 0 is initial_delay."""
        policy = RetryPolicy(
            max_attempts=3, initial_delay_seconds=0.5, max_delay_seconds=10.0
        )
        assert policy.delay_for_attempt(0) == 0.5

    def test_delay_for_second_attempt(self) -> None:
        """Delay for attempt 1 is initial * multiplier."""
        policy = RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.5,
            max_delay_seconds=10.0,
            multiplier=2.0,
        )
        assert policy.delay_for_attempt(1) == 1.0

    def test_delay_capped_at_max(self) -> None:
        """Delay is capped at max_delay_seconds."""
        policy = RetryPolicy(
            max_attempts=10,
            initial_delay_seconds=1.0,
            max_delay_seconds=5.0,
            multiplier=2.0,
        )
        # Attempt 0: 1.0
        # Attempt 1: 2.0
        # Attempt 2: 4.0
        # Attempt 3: 8.0 -> capped to 5.0
        assert policy.delay_for_attempt(2) == 4.0
        assert policy.delay_for_attempt(3) == 5.0
        assert policy.delay_for_attempt(10) == 5.0

    def test_delay_negative_attempt_raises(self) -> None:
        """Negative attempt raises ValueError."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        with pytest.raises(ValueError, match="non-negative"):
            policy.delay_for_attempt(-1)


class TestShouldRetry:
    """Tests for should_retry logic."""

    def test_cancelled_error_never_retried(self) -> None:
        """CancelledError is never retried."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        assert policy.should_retry(asyncio.CancelledError(), 1) is False
        assert policy.should_retry(asyncio.CancelledError(), 2) is False

    def test_exceeds_max_attempts(self) -> None:
        """Errors after max_attempts are not retried."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = TimeoutError("timeout")
        assert policy.should_retry(error, 1) is True
        assert policy.should_retry(error, 2) is True
        assert policy.should_retry(error, 3) is False

    def test_timeout_error_is_retryable(self) -> None:
        """Timeout errors are retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        assert policy.should_retry(TimeoutError(), 1) is True

    def test_connection_error_is_retryable(self) -> None:
        """Connection errors are retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)

        class ConnectionError(Exception):
            pass

        assert policy.should_retry(ConnectionError("connection failed"), 1) is True

    def test_rate_limit_429_is_retryable(self) -> None:
        """Rate limit (429) errors are retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("429 Too Many Requests")
        assert policy.should_retry(error, 1) is True

    def test_server_error_5xx_is_retryable(self) -> None:
        """Server errors (5xx) are retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("500 Internal Server Error")
        assert policy.should_retry(error, 1) is True

    def test_authentication_error_not_retryable(self) -> None:
        """Authentication errors (401) are not retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("401 Unauthorized")
        assert policy.should_retry(error, 1) is False

    def test_authorization_error_not_retryable(self) -> None:
        """Authorization errors (403) are not retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("403 Forbidden")
        assert policy.should_retry(error, 1) is False

    def test_validation_error_not_retryable(self) -> None:
        """Validation errors (400) are not retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("400 Bad Request")
        assert policy.should_retry(error, 1) is False

    def test_not_found_error_not_retryable(self) -> None:
        """Not found errors (404) are not retryable."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=10.0)
        error = Exception("404 Not Found")
        assert policy.should_retry(error, 1) is False


class TestExecuteWithRetry:
    """Tests for execute_with_retry helper."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self) -> None:
        """Successful operation doesn't retry."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.01, max_delay_seconds=1.0)
        calls = []

        async def operation():
            calls.append(1)

        success, error = await execute_with_retry(operation, policy)
        assert success is True
        assert error is None
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self) -> None:
        """Transient errors trigger retry."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.01, max_delay_seconds=1.0)
        attempts = [0]

        async def operation():
            attempts[0] += 1
            if attempts[0] < 3:
                raise TimeoutError("timeout")

        success, error = await execute_with_retry(operation, policy)
        assert success is True
        assert error is None
        assert attempts[0] == 3

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self) -> None:
        """Non-retryable errors fail immediately."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.01, max_delay_seconds=1.0)
        calls = []

        async def operation():
            calls.append(1)
            raise Exception("401 Unauthorized")

        success, error = await execute_with_retry(operation, policy)
        assert success is False
        assert "401" in str(error)
        assert calls == [1]  # Only called once

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError is not caught and propagates."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.01, max_delay_seconds=1.0)

        async def operation():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await execute_with_retry(operation, policy)

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self) -> None:
        """All attempts exhausted returns final error."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.01, max_delay_seconds=1.0)
        calls = []

        async def operation():
            calls.append(1)
            raise TimeoutError("always fails")

        success, error = await execute_with_retry(operation, policy)
        assert success is False
        assert isinstance(error, TimeoutError)
        assert str(error) == "always fails"
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_custom_sleeper_for_testing(self) -> None:
        """Custom sleeper allows testing without wall-clock wait."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=100.0, max_delay_seconds=1000.0)
        sleeps = []

        async def fake_sleep(delay: float):
            sleeps.append(delay)

        attempts = [0]

        async def operation():
            attempts[0] += 1
            if attempts[0] < 3:
                raise TimeoutError("timeout")

        success, error = await execute_with_retry(operation, policy, sleeper=fake_sleep)
        assert success is True
        # First retry at 100.0, second retry at 200.0 (100 * 2)
        assert sleeps == [100.0, 200.0]

    @pytest.mark.asyncio
    async def test_on_retry_callback(self) -> None:
        """on_retry callback receives attempt, error, and delay."""
        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.5, max_delay_seconds=10.0)
        retries = []

        def on_retry(attempt: int, error: Exception, delay: float):
            retries.append((attempt, type(error).__name__, delay))

        attempts = [0]

        async def operation():
            attempts[0] += 1
            if attempts[0] < 3:
                raise TimeoutError("timeout")

        success, error = await execute_with_retry(operation, policy, on_retry=on_retry)
        assert success is True
        # First retry: attempt=1, delay=0.5
        # Second retry: attempt=2, delay=1.0 (0.5 * 2)
        assert retries == [(1, "TimeoutError", 0.5), (2, "TimeoutError", 1.0)]