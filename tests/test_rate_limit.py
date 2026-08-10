"""Tests for rate limit policy."""

import asyncio

import pytest

from general_mini_agent.rate_limit import RateLimiter, RateLimitPolicy


class TestRateLimitPolicy:
    """Tests for RateLimitPolicy configuration."""

    def test_valid_policy_creation(self) -> None:
        """Valid policy can be created."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=10)
        assert policy.requests_per_minute == 60
        assert policy.burst == 10

    def test_requests_per_minute_must_be_positive(self) -> None:
        """requests_per_minute must be at least 1."""
        with pytest.raises(ValueError, match="at least 1"):
            RateLimitPolicy(requests_per_minute=0, burst=10)

        with pytest.raises(ValueError, match="at least 1"):
            RateLimitPolicy(requests_per_minute=-1, burst=10)

    def test_burst_must_be_positive(self) -> None:
        """burst must be at least 1."""
        with pytest.raises(ValueError, match="at least 1"):
            RateLimitPolicy(requests_per_minute=60, burst=0)

        with pytest.raises(ValueError, match="at least 1"):
            RateLimitPolicy(requests_per_minute=60, burst=-1)


class TestRateLimiter:
    """Tests for rate limiter."""

    def test_acquire_within_burst(self) -> None:
        """Can acquire tokens within burst capacity."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=5)
        limiter = RateLimiter(policy)

        # Should be able to acquire burst tokens immediately
        for _ in range(5):
            assert limiter.try_acquire() is True

        # 6th should fail
        assert limiter.try_acquire() is False

    def test_independent_instances(self) -> None:
        """Independent limiter instances have independent buckets."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=1)
        limiter1 = RateLimiter(policy)
        limiter2 = RateLimiter(policy)

        # Both can acquire once (independent buckets)
        assert limiter1.try_acquire() is True
        assert limiter2.try_acquire() is True

    def test_acquire_sync_with_timeout(self) -> None:
        """Acquire with timeout returns False if timed out."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=1)
        limiter = RateLimiter(policy)

        # Exhaust the bucket
        assert limiter.try_acquire() is True

        # Try to acquire with timeout - should fail
        result = limiter.acquire_sync(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_async_within_burst(self) -> None:
        """Can acquire tokens within burst capacity."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=5)
        limiter = RateLimiter(policy)

        for _ in range(5):
            assert await limiter.acquire_async() is True

    @pytest.mark.asyncio
    async def test_acquire_async_with_timeout(self) -> None:
        """Acquire with timeout returns False if timed out."""
        policy = RateLimitPolicy(requests_per_minute=60, burst=1)
        limiter = RateLimiter(policy)

        # Exhaust the bucket
        await limiter.acquire_async()

        # Try to acquire with timeout
        result = await limiter.acquire_async(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self) -> None:
        """Cancellation while waiting propagates."""
        policy = RateLimitPolicy(requests_per_minute=1, burst=1)
        limiter = RateLimiter(policy)

        # Exhaust the bucket
        await limiter.acquire_async()

        # Create a task that will be cancelled
        async def blocked_acquire():
            await limiter.acquire_async()

        task = asyncio.create_task(blocked_acquire())

        # Give it a moment to start waiting
        await asyncio.sleep(0.01)

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task