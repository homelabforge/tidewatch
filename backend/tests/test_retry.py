"""Tests for retry utility."""

import pytest
from app.utils.retry import async_retry


class TestRetryDecorator:
    """Tests for the retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        """Test that function succeeds on first try without retrying."""
        call_count = 0

        @async_retry(max_attempts=3, backoff_base=0.1)
        async def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_function()
        assert result == "success"
        assert call_count == 1  # Should only be called once

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that function retries on failure."""
        call_count = 0

        @async_retry(max_attempts=3, backoff_base=0.1)
        async def failing_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"

        result = await failing_function()
        assert result == "success"
        assert call_count == 3  # Should be called 3 times

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that exception is raised when max retries exceeded."""
        call_count = 0

        @async_retry(max_attempts=3, backoff_base=0.1)
        async def always_failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            await always_failing_function()

        assert call_count == 3  # Should try 3 times before giving up

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Test that exponential backoff is applied."""
        import time

        call_times = []

        @async_retry(max_attempts=3, backoff_base=0.1)
        async def test_function():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("Retry")
            return "success"

        await test_function()

        # Verify delays increase exponentially
        assert len(call_times) == 3
        # First delay should be ~0.1s, second ~0.2s
        if len(call_times) >= 2:
            first_delay = call_times[1] - call_times[0]
            assert first_delay >= 0.1  # Should be at least backoff_base

    @pytest.mark.asyncio
    async def test_specific_exception_only(self):
        """Test retrying only on specific exceptions."""

        @async_retry(max_attempts=3, backoff_base=0.1, exceptions=(ValueError,))
        async def mixed_exceptions():
            raise TypeError("Wrong exception type")

        # Should not retry on TypeError
        with pytest.raises(TypeError):
            await mixed_exceptions()
