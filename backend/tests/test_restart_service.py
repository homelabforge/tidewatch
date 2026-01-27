"""Tests for restart service (app/services/restart_service.py).

Tests intelligent container restart with exponential backoff:
- Exponential backoff calculations
- Linear backoff calculations
- Fixed delay calculations
- Jitter variance (±20%)
- Retry state management
- Max attempts enforcement
- Circuit breaker logic
- Success window reset
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.models.restart_state import ContainerRestartState
from app.services.restart_service import RestartService


class TestExponentialBackoff:
    """Test suite for exponential backoff calculations."""

    def test_exponential_backoff_attempt_0(self):
        """Test backoff at attempt 0 is base_delay."""
        delay = RestartService.calculate_exponential_backoff(
            attempt=0, base_delay=2.0, multiplier=1.0, max_delay=300.0, jitter=False
        )

        # 2.0 * 1.0 * 2^0 = 2.0
        assert delay == pytest.approx(2.0, abs=0.01)

    def test_exponential_backoff_doubles_each_attempt(self):
        """Test backoff doubles each attempt."""
        delays = []
        for attempt in range(5):
            delay = RestartService.calculate_exponential_backoff(
                attempt=attempt,
                base_delay=2.0,
                multiplier=1.0,
                max_delay=300.0,
                jitter=False,
            )
            delays.append(delay)

        # Each delay should be double the previous
        assert delays[0] == pytest.approx(2.0)  # 2 * 1 * 2^0 = 2
        assert delays[1] == pytest.approx(4.0)  # 2 * 1 * 2^1 = 4
        assert delays[2] == pytest.approx(8.0)  # 2 * 1 * 2^2 = 8
        assert delays[3] == pytest.approx(16.0)  # 2 * 1 * 2^3 = 16
        assert delays[4] == pytest.approx(32.0)  # 2 * 1 * 2^4 = 32

    def test_exponential_backoff_respects_max_delay(self):
        """Test backoff is capped at max_delay."""
        delay = RestartService.calculate_exponential_backoff(
            attempt=10,  # Very large attempt
            base_delay=2.0,
            multiplier=1.0,
            max_delay=60.0,
            jitter=False,
        )

        # Should be capped at max_delay
        assert delay == pytest.approx(60.0)

    def test_exponential_backoff_with_multiplier(self):
        """Test multiplier scales the backoff."""
        delay = RestartService.calculate_exponential_backoff(
            attempt=3,
            base_delay=2.0,
            multiplier=2.0,  # Double the rate
            max_delay=300.0,
            jitter=False,
        )

        # 2.0 * 2.0 * 2^3 = 2.0 * 2.0 * 8 = 32.0
        assert delay == pytest.approx(32.0)

    def test_exponential_backoff_jitter_adds_randomness(self):
        """Test jitter adds ±20% randomness."""
        delays = []
        for _ in range(10):
            delay = RestartService.calculate_exponential_backoff(
                attempt=3, base_delay=10.0, multiplier=1.0, max_delay=300.0, jitter=True
            )
            delays.append(delay)

        # Base delay at attempt 3: 10.0 * 1.0 * 2^3 = 80.0
        # Jitter: ±20% = ±16.0 → range [64.0, 96.0]
        # But never below base_delay (10.0)

        expected_base = 80.0
        jitter_range = expected_base * 0.2  # ±16.0

        for delay in delays:
            assert delay >= expected_base - jitter_range
            assert delay <= expected_base + jitter_range

        # Should have variance (not all same)
        assert len(set(delays)) > 1

    def test_exponential_backoff_jitter_never_below_base(self):
        """Test jitter never reduces delay below base_delay."""
        base_delay = 10.0

        for attempt in range(5):
            for _ in range(10):
                delay = RestartService.calculate_exponential_backoff(
                    attempt=attempt,
                    base_delay=base_delay,
                    multiplier=1.0,
                    max_delay=300.0,
                    jitter=True,
                )

                # Never below base delay
                assert delay >= base_delay

    def test_exponential_backoff_realistic_parameters(self):
        """Test with realistic restart parameters."""
        # Typical: start at 5s, max 5 minutes
        delays = []
        for attempt in range(10):
            delay = RestartService.calculate_exponential_backoff(
                attempt=attempt,
                base_delay=5.0,
                multiplier=1.0,
                max_delay=300.0,  # 5 minutes
                jitter=False,
            )
            delays.append(delay)

        # First few attempts
        assert delays[0] == pytest.approx(5.0)  # 5s
        assert delays[1] == pytest.approx(10.0)  # 10s
        assert delays[2] == pytest.approx(20.0)  # 20s
        assert delays[3] == pytest.approx(40.0)  # 40s
        assert delays[4] == pytest.approx(80.0)  # 1m 20s
        assert delays[5] == pytest.approx(160.0)  # 2m 40s
        assert delays[6] == pytest.approx(300.0)  # 5m (capped)


class TestLinearBackoff:
    """Test suite for linear backoff calculations."""

    def test_linear_backoff_attempt_0(self):
        """Test linear backoff at attempt 0 is base_delay."""
        delay = RestartService.calculate_linear_backoff(
            attempt=0, base_delay=5.0, increment=10.0, max_delay=300.0
        )

        # 5.0 + (10.0 * 0) = 5.0
        assert delay == pytest.approx(5.0)

    def test_linear_backoff_increases_linearly(self):
        """Test backoff increases by increment each attempt."""
        delays = []
        for attempt in range(5):
            delay = RestartService.calculate_linear_backoff(
                attempt=attempt, base_delay=5.0, increment=10.0, max_delay=300.0
            )
            delays.append(delay)

        assert delays[0] == pytest.approx(5.0)  # 5 + 10*0 = 5
        assert delays[1] == pytest.approx(15.0)  # 5 + 10*1 = 15
        assert delays[2] == pytest.approx(25.0)  # 5 + 10*2 = 25
        assert delays[3] == pytest.approx(35.0)  # 5 + 10*3 = 35
        assert delays[4] == pytest.approx(45.0)  # 5 + 10*4 = 45

    def test_linear_backoff_respects_max_delay(self):
        """Test linear backoff is capped at max_delay."""
        delay = RestartService.calculate_linear_backoff(
            attempt=50, base_delay=5.0, increment=10.0, max_delay=60.0
        )

        # Would be 5 + 10*50 = 505, but capped at 60
        assert delay == pytest.approx(60.0)

    def test_linear_backoff_realistic_parameters(self):
        """Test with realistic linear backoff parameters."""
        # Start at 10s, add 15s each attempt, max 5 minutes
        delays = []
        for attempt in range(10):
            delay = RestartService.calculate_linear_backoff(
                attempt=attempt, base_delay=10.0, increment=15.0, max_delay=300.0
            )
            delays.append(delay)

        assert delays[0] == pytest.approx(10.0)  # 10s
        assert delays[1] == pytest.approx(25.0)  # 25s
        assert delays[2] == pytest.approx(40.0)  # 40s
        assert delays[5] == pytest.approx(85.0)  # 1m 25s


class TestFixedBackoff:
    """Test suite for fixed backoff."""

    def test_fixed_backoff_returns_constant_delay(self):
        """Test fixed backoff always returns same delay."""
        delay1 = RestartService.calculate_fixed_backoff(delay=30.0)
        delay2 = RestartService.calculate_fixed_backoff(delay=30.0)
        delay3 = RestartService.calculate_fixed_backoff(delay=30.0)

        assert delay1 == delay2 == delay3 == 30.0

    def test_fixed_backoff_default_delay(self):
        """Test fixed backoff uses default 30s."""
        delay = RestartService.calculate_fixed_backoff()

        assert delay == 30.0


class TestCalculateBackoffDelay:
    """Test suite for calculate_backoff_delay with state."""

    @pytest.mark.asyncio
    async def test_exponential_strategy(self):
        """Test exponential strategy is used correctly."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            consecutive_failures=3,
            backoff_strategy="exponential",
            base_delay_seconds=5.0,
            max_delay_seconds=300.0,
        )

        delay = await RestartService.calculate_backoff_delay(state, mock_db)

        # Should use exponential backoff
        # 5.0 * 1.0 * 2^3 = 40.0 (with jitter variance)
        assert 32.0 <= delay <= 48.0  # ±20% jitter

    @pytest.mark.asyncio
    async def test_linear_strategy(self):
        """Test linear strategy is used correctly."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            consecutive_failures=4,
            backoff_strategy="linear",
            base_delay_seconds=5.0,
            max_delay_seconds=300.0,
        )

        delay = await RestartService.calculate_backoff_delay(state, mock_db)

        # 5.0 + (10.0 * 4) = 45.0
        assert delay == pytest.approx(45.0)

    @pytest.mark.asyncio
    async def test_fixed_strategy(self):
        """Test fixed strategy returns base_delay."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            consecutive_failures=10,  # Shouldn't matter
            backoff_strategy="fixed",
            base_delay_seconds=30.0,
            max_delay_seconds=300.0,
        )

        delay = await RestartService.calculate_backoff_delay(state, mock_db)

        assert delay == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_unknown_strategy_falls_back_to_exponential(self):
        """Test unknown strategy defaults to exponential."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            consecutive_failures=2,
            backoff_strategy="unknown_strategy",
            base_delay_seconds=5.0,
            max_delay_seconds=300.0,
        )

        delay = await RestartService.calculate_backoff_delay(state, mock_db)

        # Should fall back to exponential
        # 5.0 * 1.0 * 2^2 = 20.0 (with jitter)
        assert 16.0 <= delay <= 24.0


class TestCircuitBreaker:
    """Test suite for circuit breaker logic."""

    @pytest.mark.asyncio
    async def test_no_state_allows_restart(self):
        """Test missing state allows restart."""
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=mock_result)

        allow, reason = await RestartService.check_circuit_breaker(
            mock_db, container_id=1
        )

        assert allow is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_paused_container_blocks_restart(self):
        """Test paused container blocks restart."""
        mock_db = AsyncMock()

        future_time = datetime.now(UTC) + timedelta(hours=1)
        state = ContainerRestartState(
            id=1,
            container_id=1,
            paused_until=future_time,
            pause_reason="Manual investigation",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = state

        mock_db.execute = AsyncMock(return_value=mock_result)

        allow, reason = await RestartService.check_circuit_breaker(
            mock_db, container_id=1
        )

        assert allow is False
        assert "Paused until" in reason
        assert "Manual investigation" in reason

    @pytest.mark.asyncio
    async def test_expired_pause_clears_and_allows(self):
        """Test expired pause is cleared automatically."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        past_time = datetime.now(UTC) - timedelta(hours=1)
        state = ContainerRestartState(
            id=1,
            container_id=1,
            paused_until=past_time,
            pause_reason="Temporary",
            max_retries_reached=False,
            enabled=True,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = state

        # Mock for concurrent count check
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        # Mock for settings
        with patch("app.services.restart_service.SettingsService") as mock_settings:
            mock_settings.get_int = AsyncMock(return_value=10)

            mock_db.execute = AsyncMock(side_effect=[mock_result, mock_count_result])

            allow, reason = await RestartService.check_circuit_breaker(
                mock_db, container_id=1
            )

            assert allow is True
            assert reason is None
            assert state.paused_until is None
            assert state.pause_reason is None

    @pytest.mark.asyncio
    async def test_max_retries_reached_blocks_restart(self):
        """Test max retries reached blocks restart."""
        mock_db = AsyncMock()

        state = ContainerRestartState(id=1, container_id=1, max_retries_reached=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = state

        mock_db.execute = AsyncMock(return_value=mock_result)

        allow, reason = await RestartService.check_circuit_breaker(
            mock_db, container_id=1
        )

        assert allow is False
        assert "Maximum retry attempts reached" in reason

    @pytest.mark.asyncio
    async def test_disabled_container_blocks_restart(self):
        """Test disabled auto-restart blocks restart."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1, container_id=1, enabled=False, max_retries_reached=False
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = state

        mock_db.execute = AsyncMock(return_value=mock_result)

        allow, reason = await RestartService.check_circuit_breaker(
            mock_db, container_id=1
        )

        assert allow is False
        assert "Auto-restart disabled" in reason

    @pytest.mark.asyncio
    async def test_concurrent_limit_blocks_restart(self):
        """Test concurrent restart limit blocks restart."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            enabled=True,
            max_retries_reached=False,
            paused_until=None,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = state

        # Mock concurrent count at limit
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 10

        with patch("app.services.restart_service.SettingsService") as mock_settings:
            mock_settings.get_int = AsyncMock(return_value=10)

            mock_db.execute = AsyncMock(side_effect=[mock_result, mock_count_result])

            allow, reason = await RestartService.check_circuit_breaker(
                mock_db, container_id=1
            )

            assert allow is False
            assert "Concurrent restart limit" in reason
            assert "10/10" in reason


class TestCheckAndResetBackoff:
    """Test suite for success window reset logic."""

    @pytest.mark.asyncio
    async def test_no_last_successful_start_no_reset(self):
        """Test no reset if container never started successfully."""
        mock_db = AsyncMock()

        state = ContainerRestartState(id=1, container_id=1, last_successful_start=None)

        container = Container(name="test")

        was_reset = await RestartService.check_and_reset_backoff(
            mock_db, state, container
        )

        assert was_reset is False

    @pytest.mark.asyncio
    async def test_no_uptime_no_reset(self):
        """Test no reset if uptime cannot be calculated."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            last_successful_start=datetime.now(UTC),
            success_window_seconds=300,
        )
        # Mock uptime_seconds property
        with patch.object(ContainerRestartState, "uptime_seconds", None):
            container = Container(name="test")

            was_reset = await RestartService.check_and_reset_backoff(
                mock_db, state, container
            )

            assert was_reset is False

    @pytest.mark.asyncio
    async def test_uptime_exceeds_success_window_resets(self):
        """Test backoff is reset when uptime exceeds success window."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=400),
            success_window_seconds=300,  # 5 minutes
            consecutive_failures=5,
            current_backoff_seconds=120.0,
            max_retries_reached=True,
            last_exit_code=1,
            last_failure_reason="OOMKilled",
        )

        # Mock uptime_seconds property
        with patch.object(ContainerRestartState, "uptime_seconds", 400):
            container = Container(name="test")

            was_reset = await RestartService.check_and_reset_backoff(
                mock_db, state, container
            )

            assert was_reset is True
            assert state.consecutive_failures == 0
            assert state.current_backoff_seconds == 0.0
            assert state.next_retry_at is None
            assert state.max_retries_reached is False
            assert state.last_exit_code is None
            assert state.last_failure_reason is None

    @pytest.mark.asyncio
    async def test_uptime_below_success_window_no_reset(self):
        """Test no reset when uptime is below success window."""
        mock_db = AsyncMock()

        state = ContainerRestartState(
            id=1,
            container_id=1,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=200),
            success_window_seconds=300,  # 5 minutes
            consecutive_failures=2,
        )

        with patch.object(ContainerRestartState, "uptime_seconds", 200):
            container = Container(name="test")

            was_reset = await RestartService.check_and_reset_backoff(
                mock_db, state, container
            )

            assert was_reset is False
            assert state.consecutive_failures == 2  # Not reset


class TestGetOrCreateRestartState:
    """Test suite for state initialization."""

    @pytest.mark.asyncio
    async def test_creates_new_state_when_missing(self):
        """Test creates new state for container without one."""
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()  # add() is synchronous, not async
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        container = Container(id=1, name="test")

        state = await RestartService.get_or_create_restart_state(mock_db, container)

        assert state is not None
        assert state.container_id == container.id

    @pytest.mark.asyncio
    async def test_returns_existing_state(self):
        """Test returns existing state if found."""
        mock_db = AsyncMock()

        existing_state = ContainerRestartState(
            id=1, container_id=1, consecutive_failures=3
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_state

        mock_db.execute = AsyncMock(return_value=mock_result)

        container = Container(id=1, name="test")

        state = await RestartService.get_or_create_restart_state(mock_db, container)

        assert state == existing_state
        assert state.consecutive_failures == 3


class TestBackoffIntegration:
    """Integration tests for complete backoff scenarios."""

    def test_realistic_exponential_backoff_progression(self):
        """Test realistic exponential backoff over 10 failures."""
        delays = []

        for attempt in range(10):
            delay = RestartService.calculate_exponential_backoff(
                attempt=attempt,
                base_delay=5.0,
                multiplier=1.0,
                max_delay=300.0,
                jitter=False,
            )
            delays.append(delay)

        # Verify exponential growth
        assert delays[0] == pytest.approx(5.0)  # 5s
        assert delays[1] == pytest.approx(10.0)  # 10s
        assert delays[2] == pytest.approx(20.0)  # 20s
        assert delays[3] == pytest.approx(40.0)  # 40s
        assert delays[4] == pytest.approx(80.0)  # 1m 20s
        assert delays[5] == pytest.approx(160.0)  # 2m 40s
        assert delays[6] == pytest.approx(300.0)  # 5m (capped)
        assert delays[7] == pytest.approx(300.0)  # Still capped
        assert delays[8] == pytest.approx(300.0)  # Still capped
        assert delays[9] == pytest.approx(300.0)  # Still capped

    def test_realistic_linear_backoff_progression(self):
        """Test realistic linear backoff over 10 failures."""
        delays = []

        for attempt in range(10):
            delay = RestartService.calculate_linear_backoff(
                attempt=attempt, base_delay=10.0, increment=15.0, max_delay=300.0
            )
            delays.append(delay)

        assert delays[0] == pytest.approx(10.0)  # 10s
        assert delays[1] == pytest.approx(25.0)  # 25s
        assert delays[2] == pytest.approx(40.0)  # 40s
        assert delays[5] == pytest.approx(85.0)  # 1m 25s
        assert delays[9] == pytest.approx(145.0)  # 2m 25s

    def test_jitter_prevents_thundering_herd(self):
        """Test jitter creates variance to prevent thundering herd."""
        # Simulate 100 containers failing simultaneously
        delays = []

        for _ in range(100):
            delay = RestartService.calculate_exponential_backoff(
                attempt=3, base_delay=10.0, multiplier=1.0, max_delay=300.0, jitter=True
            )
            delays.append(delay)

        # Should have significant variance
        unique_delays = len(set(delays))
        assert unique_delays > 50  # At least 50 different delay values

        # All within expected range
        for delay in delays:
            assert 64.0 <= delay <= 96.0  # Base 80 ± 20%
