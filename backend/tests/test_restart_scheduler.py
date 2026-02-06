"""Tests for restart scheduler service (app/services/restart_scheduler.py).

Tests intelligent container restart scheduling with APScheduler:
- Monitoring loop and job scheduling
- Container state checking and restart scheduling
- Exponential backoff retry logic
- Circuit breaker enforcement
- Max retries handling
- Restart execution
- Cleanup jobs for successful containers
- Event publishing and notifications
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import OperationalError

from app.models.restart_state import ContainerRestartState
from app.services.restart_scheduler import RestartSchedulerService


@pytest.fixture
def scheduler():
    """Create mock APScheduler."""
    mock_scheduler = MagicMock(spec=AsyncIOScheduler)
    mock_scheduler.add_job = MagicMock()
    return mock_scheduler


@pytest.fixture
def restart_scheduler(scheduler):
    """Create RestartSchedulerService instance."""
    return RestartSchedulerService(scheduler)


@pytest.fixture
def mock_settings():
    """Mock SettingsService."""
    with patch("app.services.restart_scheduler.SettingsService") as mock:
        mock.get_bool = AsyncMock(return_value=True)
        mock.get_int = AsyncMock(return_value=30)
        yield mock


@pytest.fixture
def mock_restart_service():
    """Mock restart_service."""
    with patch("app.services.restart_scheduler.restart_service") as mock:
        mock.get_or_create_restart_state = AsyncMock()
        mock.check_circuit_breaker = AsyncMock(return_value=(True, None))
        mock.calculate_backoff_delay = AsyncMock(return_value=60.0)
        mock.execute_restart = AsyncMock(return_value={"success": True})
        mock.check_and_reset_backoff = AsyncMock()
        yield mock


@pytest.fixture
def mock_container_monitor():
    """Mock container_monitor."""
    with patch("app.services.restart_scheduler.container_monitor") as mock:
        mock.get_container_state = AsyncMock(return_value={"running": True})
        mock.should_retry_restart = AsyncMock(return_value=(True, "container_error"))
        yield mock


@pytest.fixture
def mock_event_bus():
    """Mock event_bus."""
    with patch("app.services.restart_scheduler.event_bus") as mock:
        mock.publish = AsyncMock()
        yield mock


@pytest.fixture
def mock_async_session(db):
    """Mock AsyncSessionLocal to return test db session."""

    class MockAsyncContextManager:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.restart_scheduler.AsyncSessionLocal") as mock:
        mock.return_value = MockAsyncContextManager()
        yield mock


class TestStartMonitoring:
    """Test suite for start_monitoring() method."""

    async def test_starts_monitoring_when_enabled(
        self, restart_scheduler, scheduler, mock_settings, db
    ):
        """Test starts monitoring when enabled in settings."""
        mock_settings.get_bool.return_value = True
        mock_settings.get_int.return_value = 30

        await restart_scheduler.start_monitoring(db)

        # Should add two jobs: monitor loop and cleanup
        assert scheduler.add_job.call_count == 2

        # Check monitor job
        monitor_call = scheduler.add_job.call_args_list[0]
        assert monitor_call[1]["id"] == "restart_monitor"
        assert monitor_call[1]["seconds"] == 30
        assert monitor_call[1]["max_instances"] == 1

        # Check cleanup job
        cleanup_call = scheduler.add_job.call_args_list[1]
        assert cleanup_call[1]["id"] == "restart_cleanup"
        assert cleanup_call[1]["hours"] == 1

    async def test_skips_monitoring_when_disabled(
        self, restart_scheduler, scheduler, mock_settings, db
    ):
        """Test skips monitoring when disabled in settings."""
        mock_settings.get_bool.return_value = False

        await restart_scheduler.start_monitoring(db)

        # Should not add any jobs
        scheduler.add_job.assert_not_called()

    async def test_uses_custom_interval(self, restart_scheduler, scheduler, mock_settings, db):
        """Test uses custom monitoring interval from settings."""
        mock_settings.get_bool.return_value = True
        mock_settings.get_int.return_value = 120

        await restart_scheduler.start_monitoring(db)

        # Check interval
        monitor_call = scheduler.add_job.call_args_list[0]
        assert monitor_call[1]["seconds"] == 120

    async def test_replaces_existing_jobs(self, restart_scheduler, scheduler, mock_settings, db):
        """Test replaces existing jobs when called again."""
        mock_settings.get_bool.return_value = True

        await restart_scheduler.start_monitoring(db)

        # Both jobs should have replace_existing=True
        for call in scheduler.add_job.call_args_list:
            assert call[1]["replace_existing"] is True


class TestMonitorLoop:
    """Test suite for _monitor_loop() method."""

    async def test_monitors_containers_with_auto_restart_enabled(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_container_monitor,
        mock_restart_service,
        mock_async_session,
    ):
        """Test monitors containers with auto_restart_enabled=True."""
        container1 = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        container2 = make_container(
            name="db", image="postgres", current_tag="16", auto_restart_enabled=True
        )
        container3 = make_container(
            name="cache", image="redis", current_tag="7", auto_restart_enabled=False
        )
        db.add_all([container1, container2, container3])
        await db.commit()

        state = ContainerRestartState(
            container_id=container1.id,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {"running": True}

        await restart_scheduler._monitor_loop()

        # Should get state for enabled containers only
        assert mock_restart_service.get_or_create_restart_state.call_count == 2

    async def test_handles_database_errors(self, restart_scheduler, db, caplog, mock_async_session):
        """Test handles database errors gracefully."""
        with patch("app.services.restart_scheduler.select") as mock_select:
            mock_select.side_effect = OperationalError("statement", "params", Exception("orig"))

            # Should not raise
            await restart_scheduler._monitor_loop()

        # Should log error
        assert "Database error in restart monitor loop" in caplog.text


class TestCheckAndScheduleRestart:
    """Test suite for _check_and_schedule_restart() method."""

    async def test_skips_if_already_scheduled(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
    ):
        """Test skips container if already scheduled for restart."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        # State with future retry scheduled
        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=1,
            next_retry_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        mock_restart_service.get_or_create_restart_state.return_value = state

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should not check container state
        mock_container_monitor.get_container_state.assert_not_called()

    async def test_skips_if_circuit_breaker_open(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
    ):
        """Test skips restart if circuit breaker is open."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_restart_service.check_circuit_breaker.return_value = (
            False,
            "Too many failures",
        )

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should not check container state
        mock_container_monitor.get_container_state.assert_not_called()

    async def test_skips_if_container_is_running(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test skips restart if container is running."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        # Set last_successful_start far enough in past to make should_reset_backoff=True
        # Default success_window_seconds is 300, so use 400 seconds ago
        from datetime import datetime, timedelta

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=2,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=400),
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {"running": True}

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should check and reset backoff
        mock_restart_service.check_and_reset_backoff.assert_awaited_once()

    async def test_skips_if_max_retries_reached(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
    ):
        """Test skips restart if max retries already reached."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=5,
            max_retries_reached=True,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {"running": False}

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should not schedule restart
        scheduler.add_job.assert_not_called()

    async def test_skips_if_restart_disabled(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
    ):
        """Test skips restart if state is disabled."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=False,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {"running": False}

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should not schedule restart
        scheduler.add_job.assert_not_called()

    async def test_skips_non_retryable_failures(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
    ):
        """Test skips restart for non-retryable exit codes."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {
            "running": False,
            "exit_code": 0,
        }
        mock_container_monitor.should_retry_restart.return_value = (False, "Clean exit")

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should update state but not schedule restart
        scheduler.add_job.assert_not_called()
        assert state.last_failure_reason == "Clean exit"

    async def test_schedules_restart_with_backoff(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
        mock_event_bus,
    ):
        """Test schedules restart with exponential backoff."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=2,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {
            "running": False,
            "exit_code": 1,
            "oom_killed": False,
            "error": "",
        }
        mock_container_monitor.should_retry_restart.return_value = (
            True,
            "container_error",
        )
        mock_restart_service.calculate_backoff_delay.return_value = 120.0

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should schedule restart job
        scheduler.add_job.assert_called_once()
        call_args = scheduler.add_job.call_args[1]
        assert call_args["id"] == f"restart_{container.id}_3"  # consecutive_failures + 1
        assert "run_date" in call_args

        # Should publish event
        mock_event_bus.publish.assert_awaited_once()
        event = mock_event_bus.publish.call_args[0][0]
        assert event["type"] == "restart-scheduled"
        assert event["container_name"] == "web"
        assert event["delay_seconds"] == 120.0

    async def test_handles_max_retries_with_notification(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_settings,
        mock_event_bus,
        mock_async_session,
    ):
        """Test handles max retries reached with notification."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=3,
            consecutive_failures=2,  # Next failure will be 3rd
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {
            "running": False,
            "exit_code": 1,
        }
        mock_container_monitor.should_retry_restart.return_value = (
            True,
            "container_error",
        )
        mock_settings.get_bool.return_value = True

        with patch(
            "app.services.notifications.dispatcher.NotificationDispatcher"
        ) as mock_dispatcher:
            mock_notify = AsyncMock()
            mock_dispatcher.return_value.notify_max_retries_reached = mock_notify

            await restart_scheduler._check_and_schedule_restart(db, container)

            # Should mark max retries reached
            assert state.max_retries_reached is True

            # Should publish event
            event = mock_event_bus.publish.call_args[0][0]
            assert event["type"] == "restart-max-retries"

            # Should send notification
            mock_notify.assert_awaited_once()

    async def test_handles_container_not_found(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
    ):
        """Test handles container state not found gracefully."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = None

        # Should not raise
        await restart_scheduler._check_and_schedule_restart(db, container)


class TestExecuteRestart:
    """Test suite for _execute_restart() method."""

    async def test_executes_restart_successfully(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test executes restart successfully."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=2,
            last_failure_reason="container_error",
            last_exit_code=1,
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": False}
        mock_restart_service.execute_restart.return_value = {"success": True}

        await restart_scheduler._execute_restart(container.id, 2)

        # Should execute restart
        mock_restart_service.execute_restart.assert_awaited_once()
        call_args = mock_restart_service.execute_restart.call_args[0]
        assert call_args[1] == container
        assert call_args[2] == state
        assert call_args[3] == 2  # attempt_number

    async def test_skips_if_container_already_running(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test skips restart if container is already running."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=2,
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": True}

        await restart_scheduler._execute_restart(container.id, 2)

        # Should not execute restart
        mock_restart_service.execute_restart.assert_not_awaited()

        # Should reset state
        await db.refresh(state)
        assert state.consecutive_failures == 0
        assert state.next_retry_at is None

    async def test_handles_restart_failure_with_notification(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_settings,
        mock_async_session,
    ):
        """Test handles restart failure with notification."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=2,
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": False}
        mock_restart_service.execute_restart.return_value = {
            "success": False,
            "error": "Failed to start container",
        }
        mock_settings.get_bool.return_value = True

        with patch(
            "app.services.notifications.dispatcher.NotificationDispatcher"
        ) as mock_dispatcher:
            mock_notify = AsyncMock()
            mock_dispatcher.return_value.notify_restart_failure = mock_notify

            await restart_scheduler._execute_restart(container.id, 2)

            # Should send notification
            mock_notify.assert_awaited_once()

    async def test_handles_container_not_found_in_db(
        self, restart_scheduler, db, mock_restart_service, caplog, mock_async_session
    ):
        """Test handles container not found in database."""
        await restart_scheduler._execute_restart(99999, 1)

        # Should log error
        assert "Container 99999 not found for restart" in caplog.text

    async def test_handles_restart_state_not_found(
        self, restart_scheduler, db, make_container, caplog, mock_async_session
    ):
        """Test handles restart state not found."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        # No state in DB
        await restart_scheduler._execute_restart(container.id, 1)

        # Should log error
        assert f"Restart state not found for {container.name}" in caplog.text


class TestCleanupSuccessfulContainers:
    """Test suite for _cleanup_successful_containers() method."""

    async def test_resets_backoff_for_successful_containers(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test resets backoff for containers running successfully."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        # State with failures but should reset (400 seconds > 300 second success_window)
        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=3,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=400),
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": True}

        await restart_scheduler._cleanup_successful_containers()

        # Should reset backoff
        mock_restart_service.check_and_reset_backoff.assert_awaited_once()

    async def test_skips_containers_not_running(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test skips cleanup for containers not running."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=3,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=400),
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": False}

        await restart_scheduler._cleanup_successful_containers()

        # Should not reset backoff
        mock_restart_service.check_and_reset_backoff.assert_not_awaited()

    async def test_skips_states_not_needing_reset(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        mock_async_session,
    ):
        """Test skips states that don't need reset."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=100),
        )
        db.add(state)
        await db.commit()

        mock_container_monitor.get_container_state.return_value = {"running": True}

        await restart_scheduler._cleanup_successful_containers()

        # Should not reset backoff
        mock_restart_service.check_and_reset_backoff.assert_not_awaited()

    async def test_handles_deleted_containers(
        self, restart_scheduler, db, mock_restart_service, mock_async_session
    ):
        """Test handles restart states for deleted containers."""
        # State with no corresponding container
        state = ContainerRestartState(
            container_id=99999,
            success_window_seconds=300,
            container_name="deleted-container",
            enabled=True,
            max_attempts=5,
            consecutive_failures=3,
            last_successful_start=datetime.now(UTC) - timedelta(seconds=400),
        )
        db.add(state)
        await db.commit()

        # Should not crash
        await restart_scheduler._cleanup_successful_containers()

        # Should not reset backoff
        mock_restart_service.check_and_reset_backoff.assert_not_awaited()

    async def test_handles_database_errors(self, restart_scheduler, db, caplog, mock_async_session):
        """Test handles database errors gracefully."""
        from sqlalchemy.exc import OperationalError

        with patch("app.services.restart_scheduler.select") as mock_select:
            mock_select.side_effect = OperationalError(
                "Database error", None, Exception("db error")
            )

            # Should not raise
            await restart_scheduler._cleanup_successful_containers()

        # Should log error
        assert "Database error in cleanup job" in caplog.text


class TestRestartSchedulerEdgeCases:
    """Test edge cases and real-world scenarios."""

    async def test_handles_timezone_aware_comparisons(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
    ):
        """Test handles timezone-aware datetime comparisons."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        # State with naive datetime (SQLite returns naive)
        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=1,
            next_retry_at=datetime.now() + timedelta(minutes=5),  # Naive
        )
        mock_restart_service.get_or_create_restart_state.return_value = state

        # Should not crash on timezone comparison
        await restart_scheduler._check_and_schedule_restart(db, container)

    async def test_handles_oom_killed_containers(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
    ):
        """Test handles OOM-killed containers."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {
            "running": False,
            "exit_code": 137,
            "oom_killed": True,
        }
        mock_container_monitor.should_retry_restart.return_value = (True, "OOM killed")

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Should schedule restart
        scheduler.add_job.assert_called_once()
        assert state.last_failure_reason == "OOM killed"

    async def test_concurrent_monitor_loops_prevented(
        self, restart_scheduler, scheduler, mock_settings, db
    ):
        """Test concurrent monitor loops are prevented."""
        mock_settings.get_bool.return_value = True

        await restart_scheduler.start_monitoring(db)

        # Check max_instances=1 and coalesce=True
        monitor_call = scheduler.add_job.call_args_list[0]
        assert monitor_call[1]["max_instances"] == 1
        assert monitor_call[1]["coalesce"] is True

    async def test_misfire_grace_time_for_restart_jobs(
        self,
        restart_scheduler,
        db,
        make_container,
        mock_restart_service,
        mock_container_monitor,
        scheduler,
    ):
        """Test restart jobs have misfire grace time."""
        container = make_container(
            name="web", image="nginx", current_tag="latest", auto_restart_enabled=True
        )
        db.add(container)
        await db.commit()

        state = ContainerRestartState(
            container_id=container.id,
            success_window_seconds=300,
            container_name=container.name,
            enabled=True,
            max_attempts=5,
            consecutive_failures=0,
        )
        mock_restart_service.get_or_create_restart_state.return_value = state
        mock_container_monitor.get_container_state.return_value = {
            "running": False,
            "exit_code": 1,
        }
        mock_container_monitor.should_retry_restart.return_value = (True, "error")

        await restart_scheduler._check_and_schedule_restart(db, container)

        # Check misfire_grace_time
        call_args = scheduler.add_job.call_args[1]
        assert call_args["misfire_grace_time"] == 60
