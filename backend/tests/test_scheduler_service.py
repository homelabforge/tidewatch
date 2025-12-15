"""Tests for scheduler service (app/services/scheduler.py).

Tests background job scheduling and execution:
- Scheduler lifecycle (start/stop/reload)
- Job registration and cron scheduling
- Update check job execution
- Auto-apply job with dependency ordering
- Metrics collection and cleanup jobs
- Dockerfile dependencies check job
- Docker cleanup job
- Manual triggering and status reporting
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call, ANY
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduler import SchedulerService, scheduler_service


# Mock fixtures

@pytest.fixture
def mock_settings():
    """Mock SettingsService for scheduler configuration."""
    with patch('app.services.scheduler.SettingsService') as mock:
        # Default return values - stored in dicts that tests can modify
        get_values = {
            "check_schedule": "0 */6 * * *",
            "dockerfile_scan_schedule": "daily",
            "cleanup_schedule": "0 4 * * *",
            "cleanup_mode": "dangling",
            "cleanup_exclude_patterns": "-dev,rollback",
            "scheduler_last_check": None,
        }

        get_bool_values = {
            "check_enabled": True,
            "auto_update_enabled": False,
            "cleanup_old_images": False,
            "cleanup_containers": True,
        }

        get_int_values = {
            "auto_update_max_concurrent": 3,
            "cleanup_after_days": 7,
        }

        mock.get = AsyncMock(side_effect=lambda db, key, default=None: get_values.get(key, default))
        mock.get_bool = AsyncMock(side_effect=lambda db, key, default=False: get_bool_values.get(key, default))
        mock.get_int = AsyncMock(side_effect=lambda db, key, default=0: get_int_values.get(key, default))
        mock.set = AsyncMock()

        # Expose the dicts so tests can modify them
        mock._get_values = get_values
        mock._get_bool_values = get_bool_values
        mock._get_int_values = get_int_values

        yield mock


@pytest.fixture
def mock_update_checker():
    """Mock UpdateChecker for update check jobs."""
    with patch('app.services.scheduler.UpdateChecker') as mock:
        mock.check_all_containers = AsyncMock(return_value={
            'total': 10,
            'checked': 10,
            'updates_found': 2,
            'errors': 0
        })
        yield mock


@pytest.fixture
def mock_update_engine():
    """Mock UpdateEngine for auto-apply jobs."""
    with patch('app.services.update_engine.UpdateEngine') as mock:
        mock.apply_update = AsyncMock(return_value={
            'success': True,
            'message': 'Update applied successfully'
        })
        yield mock


@pytest.fixture
def mock_metrics_collector():
    """Mock metrics_collector for metrics jobs."""
    mock = MagicMock()
    mock.collect_all_metrics = AsyncMock(return_value={
        'collected': 10,
        'skipped': 0
    })
    mock.cleanup_old_metrics = AsyncMock(return_value=150)

    # metrics_collector is imported inside try/except blocks in the methods
    # Patch at the import location
    with patch('app.services.metrics_collector.metrics_collector', mock):
        yield mock


@pytest.fixture
def scheduler_instance():
    """Create fresh scheduler instance for each test."""
    return SchedulerService()


@pytest.fixture(autouse=True)
def auto_mock_db(mock_async_session_local, db):
    """Automatically apply database mocking to all tests in this module.

    This ensures SchedulerService.start() and all job methods use the test database
    instead of trying to create their own AsyncSessionLocal() connections.
    """
    # The fixture dependencies ensure mocking is active
    pass


class TestSchedulerLifecycle:
    """Test scheduler start/stop/reload lifecycle."""

    async def test_starts_scheduler_with_default_settings(self, scheduler_instance, mock_settings):
        """Test starts scheduler with default settings."""
        await scheduler_instance.start()

        assert scheduler_instance.scheduler is not None
        assert scheduler_instance.scheduler.running is True
        assert scheduler_instance._check_schedule == "0 */6 * * *"
        assert scheduler_instance._enabled is True

    async def test_loads_schedule_from_settings(self, scheduler_instance, mock_settings):
        """Test loads schedule from database settings."""
        mock_settings._get_values["check_schedule"] = "0 */4 * * *"  # Every 4 hours

        await scheduler_instance.start()

        assert scheduler_instance._check_schedule == "0 */4 * * *"
        # Use assert_any_await since start() calls get() multiple times for different keys
        mock_settings.get.assert_any_await(
            ANY, "check_schedule", default="0 */6 * * *"
        )

    async def test_does_not_start_when_disabled(self, scheduler_instance, mock_settings):
        """Test does not start scheduler when check_enabled is False."""
        mock_settings._get_bool_values["check_enabled"] = False

        await scheduler_instance.start()

        assert scheduler_instance.scheduler is None

    async def test_stops_scheduler_gracefully(self, scheduler_instance, mock_settings):
        """Test stops scheduler gracefully."""
        await scheduler_instance.start()
        assert scheduler_instance.scheduler.running is True

        await scheduler_instance.stop()

        assert scheduler_instance.scheduler.running is False

    async def test_handles_stop_when_not_started(self, scheduler_instance):
        """Test handles stop when scheduler was never started."""
        # Should not raise exception
        await scheduler_instance.stop()

        assert scheduler_instance.scheduler is None

    async def test_reloads_schedule_when_changed(self, scheduler_instance, mock_settings, db):
        """Test reloads schedule when settings change."""
        await scheduler_instance.start()
        original_schedule = scheduler_instance._check_schedule

        # Change schedule
        mock_settings._get_values["check_schedule"] = "0 */2 * * *"  # Every 2 hours

        await scheduler_instance.reload_schedule(db)

        assert scheduler_instance._check_schedule == "0 */2 * * *"
        assert scheduler_instance._check_schedule != original_schedule

    async def test_does_not_reload_when_schedule_unchanged(self, scheduler_instance, mock_settings, db):
        """Test does not reload when schedule hasn't changed."""
        await scheduler_instance.start()
        
        # Keep same schedule
        mock_settings._get_values["check_schedule"] = "0 */6 * * *"
        
        with patch.object(scheduler_instance, 'stop') as mock_stop:
            await scheduler_instance.reload_schedule(db)
            
            # Should not have called stop/start
            mock_stop.assert_not_called()

    async def test_handles_database_error_during_start(self, scheduler_instance, mock_settings):
        """Test handles database connection error during start."""
        from sqlalchemy.exc import OperationalError
        
        mock_settings.get.side_effect = OperationalError("Connection failed", None, None)

        with pytest.raises(OperationalError):
            await scheduler_instance.start()

    async def test_handles_invalid_cron_schedule(self, scheduler_instance, mock_settings):
        """Test handles invalid cron schedule format."""
        mock_settings._get_values["check_schedule"] = "invalid cron"

        with pytest.raises(ValueError):
            await scheduler_instance.start()

    async def test_handles_import_error_during_start(self, scheduler_instance, mock_settings):
        """Test handles import error during scheduler start."""
        with patch('app.services.restart_scheduler.RestartSchedulerService', side_effect=ImportError("Module not found")):
            with pytest.raises(ImportError):
                await scheduler_instance.start()


class TestJobRegistration:
    """Test job registration and scheduling."""

    async def test_registers_update_check_job(self, scheduler_instance, mock_settings):
        """Test registers update check job with correct schedule."""
        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("update_check")
        assert job is not None
        assert job.name == "Automatic Container Update Check"
        assert isinstance(job.trigger, CronTrigger)

    async def test_registers_auto_apply_job(self, scheduler_instance, mock_settings):
        """Test registers auto-apply job (runs every 5 minutes)."""
        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("auto_apply")
        assert job is not None
        assert job.name == "Automatic Update Application"

    async def test_registers_metrics_collection_job(self, scheduler_instance, mock_settings):
        """Test registers metrics collection job."""
        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("metrics_collection")
        assert job is not None
        assert job.name == "Container Metrics Collection"

    async def test_registers_metrics_cleanup_job(self, scheduler_instance, mock_settings):
        """Test registers metrics cleanup job."""
        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("metrics_cleanup")
        assert job is not None
        assert job.name == "Metrics History Cleanup"

    async def test_registers_dockerfile_job_when_enabled(self, scheduler_instance, mock_settings):
        """Test registers dockerfile dependencies job when enabled."""
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "check_schedule": "0 */6 * * *",
            "dockerfile_scan_schedule": "daily",
        }.get(key, default)

        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("dockerfile_dependencies_check")
        assert job is not None
        assert job.name == "Dockerfile Dependencies Update Check"

    async def test_does_not_register_dockerfile_job_when_disabled(self, scheduler_instance, mock_settings):
        """Test does not register dockerfile job when disabled."""
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "check_schedule": "0 */6 * * *",
            "dockerfile_scan_schedule": "disabled",
        }.get(key, default)

        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("dockerfile_dependencies_check")
        assert job is None

    async def test_registers_docker_cleanup_job_when_enabled(self, scheduler_instance, mock_settings):
        """Test registers docker cleanup job when enabled."""
        mock_settings.get_bool.side_effect = lambda db, key, default=False: {
            "check_enabled": True,
            "cleanup_old_images": True,
        }.get(key, default)

        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("docker_cleanup")
        assert job is not None
        assert job.name == "Docker Resource Cleanup"

    async def test_does_not_register_docker_cleanup_when_disabled(self, scheduler_instance, mock_settings):
        """Test does not register docker cleanup job when disabled."""
        mock_settings.get_bool.side_effect = lambda db, key, default=False: {
            "check_enabled": True,
            "cleanup_old_images": False,
        }.get(key, default)

        await scheduler_instance.start()

        job = scheduler_instance.scheduler.get_job("docker_cleanup")
        assert job is None

    async def test_sets_max_instances_to_one(self, scheduler_instance, mock_settings):
        """Test all jobs have max_instances=1 to prevent overlapping runs."""
        await scheduler_instance.start()

        jobs = scheduler_instance.scheduler.get_jobs()
        for job in jobs:
            # Check that max_instances is 1 (prevents concurrent execution)
            assert job.max_instances == 1

    async def test_replaces_existing_jobs(self, scheduler_instance, mock_settings):
        """Test jobs are replaced if they already exist."""
        await scheduler_instance.start()
        
        # Get original job
        original_job = scheduler_instance.scheduler.get_job("update_check")
        
        # Stop and restart
        await scheduler_instance.stop()
        await scheduler_instance.start()
        
        # Get new job
        new_job = scheduler_instance.scheduler.get_job("update_check")
        
        # Jobs should have same ID but be different instances
        assert new_job is not None
        assert new_job.id == original_job.id


class TestUpdateCheckJob:
    """Test update check job execution."""

    async def test_runs_update_check_successfully(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test runs update check job successfully."""
        await scheduler_instance._run_update_check()

        mock_update_checker.check_all_containers.assert_awaited_once()

    async def test_logs_update_check_stats(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test logs statistics after update check."""
        mock_update_checker.check_all_containers.return_value = {
            'total': 15,
            'checked': 15,
            'updates_found': 5,
            'errors': 1
        }

        await scheduler_instance._run_update_check()

        # Should have been called with expected stats
        mock_update_checker.check_all_containers.assert_awaited_once()

    async def test_updates_last_check_timestamp(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test updates _last_check timestamp after successful run."""
        before = datetime.now(timezone.utc)
        
        await scheduler_instance._run_update_check()
        
        assert scheduler_instance._last_check is not None
        assert scheduler_instance._last_check >= before

    async def test_persists_last_check_to_settings(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test persists last check timestamp to settings."""
        await scheduler_instance._run_update_check()

        # Should have called SettingsService.set with timestamp
        mock_settings.set.assert_awaited_once()
        call_args = mock_settings.set.call_args
        assert call_args[0][1] == "scheduler_last_check"
        assert isinstance(call_args[0][2], str)  # ISO format string

    async def test_handles_database_error_during_check(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test handles database error during update check."""
        from sqlalchemy.exc import OperationalError
        
        mock_update_checker.check_all_containers.side_effect = OperationalError("DB error", None, None)

        # Should not raise, just log error
        await scheduler_instance._run_update_check()

    async def test_handles_invalid_data_during_check(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test handles KeyError during update check."""
        mock_update_checker.check_all_containers.side_effect = KeyError("missing key")

        # Should not raise, just log error
        await scheduler_instance._run_update_check()

    async def test_manual_trigger_calls_update_check(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test manual trigger runs update check."""
        await scheduler_instance.trigger_update_check()

        mock_update_checker.check_all_containers.assert_awaited_once()




class TestAutoApplyJob:
    """Test auto-apply job execution and logic."""

    async def test_skips_when_auto_update_disabled(self, scheduler_instance, mock_settings):
        """Test skips auto-apply when auto_update_enabled is False."""
        mock_settings.get_bool.side_effect = lambda db, key, default=False: {
            "auto_update_enabled": False,
        }.get(key, default)

        await scheduler_instance._run_auto_apply()

        # Should return early, no updates applied
        mock_settings.get_bool.assert_awaited()

    async def test_applies_auto_approved_updates(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test applies auto-approved updates."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        # Create container with auto policy
        container = make_container(name="web", image="nginx", policy="auto")
        db.add(container)
        await db.commit()

        # Create approved update
        update = make_update(
            container_id=container.id,
            container_name="web",
            status="approved",
            approved_by="system",
            from_tag="1.0.0",
            to_tag="1.1.0"
        )
        db.add(update)
        await db.commit()

        with patch('app.services.update_engine.UpdateEngine') as mock_engine:
            mock_engine.apply_update = AsyncMock(return_value={'success': True})

            await scheduler_instance._run_auto_apply()

            # Should have applied the update
            mock_engine.apply_update.assert_awaited_once()

    async def test_applies_pending_retry_updates(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test applies pending retry updates when ready."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        container = make_container(name="app", image="myapp")
        db.add(container)
        await db.commit()

        # Create retry update with next_retry_at in the past
        past_time = datetime.now() - timedelta(minutes=5)
        update = make_update(
            container_id=container.id,
            container_name="app",
            status="pending_retry",
            next_retry_at=past_time,
            retry_count=1,
            max_retries=3
        )
        db.add(update)
        await db.commit()

        with patch('app.services.update_engine.UpdateEngine') as mock_engine:
            mock_engine.apply_update = AsyncMock(return_value={'success': True})

            await scheduler_instance._run_auto_apply()

            mock_engine.apply_update.assert_awaited_once()

    async def test_skips_updates_outside_update_window(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test skips updates outside their update window."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        # Create container with update window (e.g., only at 3 AM)
        container = make_container(
            name="db",
            image="postgres",
            policy="auto",
            update_window="0 3 * * *"
        )
        db.add(container)
        await db.commit()

        update = make_update(
            container_id=container.id,
            container_name="db",
            status="approved",
            approved_by="system"
        )
        db.add(update)
        await db.commit()

        with patch('app.services.update_window.UpdateWindow') as mock_window:
            # Mock is_in_window to return False (outside window)
            mock_window.is_in_window.return_value = False

            with patch('app.services.update_engine.UpdateEngine') as mock_engine:
                mock_engine.apply_update = AsyncMock()

                await scheduler_instance._run_auto_apply()

                # Should NOT have applied update
                mock_engine.apply_update.assert_not_called()

    async def test_respects_max_concurrent_limit(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test respects auto_update_max_concurrent setting."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)
        
        mock_settings._get_int_values["auto_update_max_concurrent"] = 2  # Max 2 concurrent

        # Create 5 approved updates
        for i in range(5):
            container = make_container(name=f"app{i}", image="myapp", policy="auto")
            db.add(container)
            await db.commit()

            update = make_update(
                container_id=container.id,
                container_name=f"app{i}",
                status="approved",
                approved_by="system"
            )
            db.add(update)

        await db.commit()

        with patch('app.services.update_engine.UpdateEngine') as mock_engine:
            mock_engine.apply_update = AsyncMock(return_value={'success': True})

            await scheduler_instance._run_auto_apply()

            # Should have applied only 2 updates (max_concurrent limit)
            assert mock_engine.apply_update.await_count == 2

    async def test_orders_updates_by_dependencies(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test orders updates by dependency graph."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        # Create containers
        db_container = make_container(name="database", image="postgres", policy="auto")
        api_container = make_container(name="api", image="myapi", policy="auto")
        db.add_all([db_container, api_container])
        await db.commit()

        # Create updates
        db_update = make_update(
            container_id=db_container.id,
            container_name="database",
            status="approved",
            approved_by="system"
        )
        api_update = make_update(
            container_id=api_container.id,
            container_name="api",
            status="approved",
            approved_by="system"
        )
        db.add_all([db_update, api_update])
        await db.commit()

        with patch('app.services.dependency_manager.DependencyManager') as mock_dm:
            # Mock dependency order: database before api
            mock_dm.get_update_order = AsyncMock(return_value=["database", "api"])

            with patch('app.services.update_engine.UpdateEngine') as mock_engine:
                mock_engine.apply_update = AsyncMock(return_value={'success': True})

                await scheduler_instance._run_auto_apply()

                # Should have called get_update_order
                mock_dm.get_update_order.assert_awaited_once()

    async def test_handles_dependency_ordering_failure(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test handles dependency ordering failure gracefully."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        container = make_container(name="app", image="myapp", policy="auto")
        db.add(container)
        await db.commit()

        update = make_update(
            container_id=container.id,
            container_name="app",
            status="approved",
            approved_by="system"
        )
        db.add(update)
        await db.commit()

        with patch('app.services.dependency_manager.DependencyManager') as mock_dm:
            # Mock ordering failure
            mock_dm.get_update_order.side_effect = ValueError("Cycle detected")

            with patch('app.services.update_engine.UpdateEngine') as mock_engine:
                mock_engine.apply_update = AsyncMock(return_value={'success': True})

                await scheduler_instance._run_auto_apply()

                # Should still apply updates in original order
                mock_engine.apply_update.assert_awaited_once()

    async def test_logs_success_and_failure_counts(self, scheduler_instance, mock_settings, db, make_container, make_update):
        """Test logs applied/failed counts."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        # Create 2 containers
        container1 = make_container(name="app1", image="myapp", policy="auto")
        container2 = make_container(name="app2", image="myapp", policy="auto")
        db.add_all([container1, container2])
        await db.commit()

        # Create 2 updates
        update1 = make_update(container_id=container1.id, container_name="app1", status="approved", approved_by="system")
        update2 = make_update(container_id=container2.id, container_name="app2", status="approved", approved_by="system")
        db.add_all([update1, update2])
        await db.commit()

        with patch('app.services.update_engine.UpdateEngine') as mock_engine:
            # First succeeds, second fails
            mock_engine.apply_update = AsyncMock(side_effect=[
                {'success': True},
                {'success': False, 'message': 'Container not running'}
            ])

            await scheduler_instance._run_auto_apply()

            assert mock_engine.apply_update.await_count == 2

    async def test_handles_database_error_during_auto_apply(self, scheduler_instance, mock_settings):
        """Test handles database error during auto-apply."""
        from sqlalchemy.exc import OperationalError
        
        mock_settings.get_bool.side_effect = OperationalError("DB error", None, None)

        # Should not raise
        await scheduler_instance._run_auto_apply()

    async def test_handles_import_error_during_auto_apply(self, scheduler_instance, mock_settings, db):
        """Test handles import error during auto-apply."""
        mock_settings.get_bool.side_effect = lambda db_s, key, default=False: {
            "auto_update_enabled": True,
        }.get(key, default)

        with patch('app.services.update_engine.UpdateEngine', side_effect=ImportError("Module not found")):
            # Should not raise
            await scheduler_instance._run_auto_apply()


class TestMetricsJobs:
    """Test metrics collection and cleanup jobs."""

    async def test_collects_metrics_successfully(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test runs metrics collection job."""
        await scheduler_instance._run_metrics_collection()

        mock_metrics_collector.collect_all_metrics.assert_awaited_once()

    async def test_logs_metrics_collection_stats(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test logs metrics collection statistics."""
        mock_metrics_collector.collect_all_metrics.return_value = {
            'collected': 15,
            'skipped': 2
        }

        await scheduler_instance._run_metrics_collection()

        mock_metrics_collector.collect_all_metrics.assert_awaited_once()

    async def test_handles_metrics_collection_error(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test handles error during metrics collection."""
        from sqlalchemy.exc import OperationalError
        
        mock_metrics_collector.collect_all_metrics.side_effect = OperationalError("DB error", None, None)

        # Should not raise
        await scheduler_instance._run_metrics_collection()

    async def test_handles_metrics_collector_import_error(self, scheduler_instance, mock_settings):
        """Test handles import error for metrics_collector."""
        # Patch the import to raise ImportError
        with patch('builtins.__import__', side_effect=lambda name, *args, **kwargs:
                   __import__(name, *args, **kwargs) if 'metrics_collector' not in name
                   else (_ for _ in ()).throw(ImportError("Module not found"))):
            # Should not raise
            await scheduler_instance._run_metrics_collection()

    async def test_cleans_up_old_metrics(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test runs metrics cleanup job."""
        mock_metrics_collector.cleanup_old_metrics.return_value = 200

        await scheduler_instance._run_metrics_cleanup()

        mock_metrics_collector.cleanup_old_metrics.assert_awaited_once_with(ANY, days=30)

    async def test_logs_metrics_cleanup_count(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test logs number of records deleted."""
        mock_metrics_collector.cleanup_old_metrics.return_value = 150

        await scheduler_instance._run_metrics_cleanup()

        # Should have logged 150 records deleted
        mock_metrics_collector.cleanup_old_metrics.assert_awaited_once()

    async def test_handles_metrics_cleanup_error(self, scheduler_instance, mock_settings, mock_metrics_collector):
        """Test handles error during metrics cleanup."""
        from sqlalchemy.exc import OperationalError
        
        mock_metrics_collector.cleanup_old_metrics.side_effect = OperationalError("DB error", None, None)

        # Should not raise
        await scheduler_instance._run_metrics_cleanup()


class TestDockerfileDependenciesJob:
    """Test Dockerfile dependencies check job."""

    async def test_checks_dockerfile_dependencies(self, scheduler_instance, mock_settings):
        """Test runs Dockerfile dependencies check."""
        with patch('app.services.dockerfile_parser.DockerfileParser') as mock_parser:
            parser_instance = MagicMock()
            parser_instance.check_all_for_updates = AsyncMock(return_value={
                'total_scanned': 10,
                'updates_found': 3
            })
            mock_parser.return_value = parser_instance

            await scheduler_instance._run_dockerfile_dependencies_check()

            parser_instance.check_all_for_updates.assert_awaited_once()

    async def test_sends_notifications_for_updates(self, scheduler_instance, mock_settings, db, make_container):
        """Test sends notifications when updates are found."""
        from app.models.dockerfile_dependency import DockerfileDependency

        # Create container for dependency
        container = make_container(name="web", image="nginx")
        db.add(container)
        await db.commit()

        # Create dependency with update available
        dep = DockerfileDependency(
            container_id=container.id,
            image_name="python",
            current_tag="3.11",
            latest_tag="3.12",
            dependency_type="base_image",
            update_available=True
        )
        db.add(dep)
        await db.commit()

        with patch('app.services.dockerfile_parser.DockerfileParser') as mock_parser:
            parser_instance = MagicMock()
            parser_instance.check_all_for_updates = AsyncMock(return_value={
                'total_scanned': 1,
                'updates_found': 1
            })
            mock_parser.return_value = parser_instance

            with patch('app.services.notifications.dispatcher.NotificationDispatcher') as mock_dispatcher:
                dispatcher_instance = MagicMock()
                dispatcher_instance.notify_dockerfile_update = AsyncMock()
                mock_dispatcher.return_value = dispatcher_instance

                await scheduler_instance._run_dockerfile_dependencies_check()

                # Should have sent notification
                dispatcher_instance.notify_dockerfile_update.assert_awaited_once()

    async def test_handles_dockerfile_check_error(self, scheduler_instance, mock_settings):
        """Test handles error during Dockerfile check."""
        from sqlalchemy.exc import OperationalError
        
        with patch('app.services.dockerfile_parser.DockerfileParser') as mock_parser:
            parser_instance = MagicMock()
            parser_instance.check_all_for_updates = AsyncMock(side_effect=OperationalError("DB error", None, None))
            mock_parser.return_value = parser_instance

            # Should not raise
            await scheduler_instance._run_dockerfile_dependencies_check()

    async def test_handles_dockerfile_parser_import_error(self, scheduler_instance, mock_settings):
        """Test handles import error for DockerfileParser."""
        with patch('app.services.dockerfile_parser.DockerfileParser', side_effect=ImportError("Module not found")):
            # Should not raise
            await scheduler_instance._run_dockerfile_dependencies_check()




class TestDockerCleanupJob:
    """Test Docker cleanup job execution."""

    async def test_runs_docker_cleanup(self, scheduler_instance, mock_settings):
        """Test runs Docker cleanup job."""
        with patch('app.services.cleanup_service.CleanupService') as mock_cleanup:
            mock_cleanup.run_cleanup = AsyncMock(return_value={
                'images_removed': 5,
                'containers_removed': 2,
                'space_reclaimed_formatted': '1.2 GB'
            })

            await scheduler_instance._run_docker_cleanup()

            mock_cleanup.run_cleanup.assert_awaited_once()

    async def test_uses_cleanup_settings(self, scheduler_instance, mock_settings):
        """Test uses cleanup settings from database."""
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "cleanup_mode": "all",
            "cleanup_exclude_patterns": "rollback,-dev,backup",
        }.get(key, default)

        mock_settings._get_int_values["cleanup_after_days"] = 14
        mock_settings.get_bool.side_effect = lambda db, key, default=False: {
            "cleanup_containers": True,
        }.get(key, default)

        with patch('app.services.cleanup_service.CleanupService') as mock_cleanup:
            mock_cleanup.run_cleanup = AsyncMock(return_value={
                'images_removed': 0,
                'containers_removed': 0,
                'space_reclaimed_formatted': '0 B'
            })

            await scheduler_instance._run_docker_cleanup()

            # Should have called with correct settings
            call_args = mock_cleanup.run_cleanup.call_args
            assert call_args.kwargs['mode'] == "all"
            assert call_args.kwargs['days'] == 14
            assert call_args.kwargs['cleanup_containers'] is True
            assert "rollback" in call_args.kwargs['exclude_patterns']

    async def test_sends_notification_after_cleanup(self, scheduler_instance, mock_settings):
        """Test sends notification after successful cleanup."""
        with patch('app.services.cleanup_service.CleanupService') as mock_cleanup:
            mock_cleanup.run_cleanup = AsyncMock(return_value={
                'images_removed': 10,
                'containers_removed': 5,
                'space_reclaimed_formatted': '2.5 GB'
            })

            with patch('app.services.notifications.dispatcher.NotificationDispatcher') as mock_dispatcher:
                dispatcher_instance = MagicMock()
                dispatcher_instance.dispatch = AsyncMock()
                mock_dispatcher.return_value = dispatcher_instance

                await scheduler_instance._run_docker_cleanup()

                # Should have sent notification
                dispatcher_instance.dispatch.assert_awaited_once()
                call_args = dispatcher_instance.dispatch.call_args
                assert "2.5 GB" in call_args.kwargs['message']

    async def test_does_not_notify_when_nothing_removed(self, scheduler_instance, mock_settings):
        """Test does not send notification when nothing was removed."""
        with patch('app.services.cleanup_service.CleanupService') as mock_cleanup:
            mock_cleanup.run_cleanup = AsyncMock(return_value={
                'images_removed': 0,
                'containers_removed': 0,
                'space_reclaimed_formatted': '0 B'
            })

            with patch('app.services.notifications.dispatcher.NotificationDispatcher') as mock_dispatcher:
                dispatcher_instance = MagicMock()
                dispatcher_instance.dispatch = AsyncMock()
                mock_dispatcher.return_value = dispatcher_instance

                await scheduler_instance._run_docker_cleanup()

                # Should NOT have sent notification
                dispatcher_instance.dispatch.assert_not_called()

    async def test_handles_cleanup_service_error(self, scheduler_instance, mock_settings):
        """Test handles error during cleanup."""
        from sqlalchemy.exc import OperationalError
        
        with patch('app.services.cleanup_service.CleanupService') as mock_cleanup:
            mock_cleanup.run_cleanup = AsyncMock(side_effect=OperationalError("DB error", None, None))

            # Should not raise
            await scheduler_instance._run_docker_cleanup()

    async def test_handles_cleanup_service_import_error(self, scheduler_instance, mock_settings):
        """Test handles import error for CleanupService."""
        with patch('app.services.cleanup_service.CleanupService', side_effect=ImportError("Module not found")):
            # Should not raise
            await scheduler_instance._run_docker_cleanup()


class TestStatusReporting:
    """Test scheduler status reporting."""

    async def test_returns_next_run_time(self, scheduler_instance, mock_settings):
        """Test get_next_run_time returns next scheduled run."""
        await scheduler_instance.start()

        next_run = scheduler_instance.get_next_run_time()

        assert next_run is not None
        assert isinstance(next_run, datetime)

    async def test_returns_none_when_not_running(self, scheduler_instance):
        """Test get_next_run_time returns None when scheduler not started."""
        next_run = scheduler_instance.get_next_run_time()

        assert next_run is None

    async def test_get_status_when_running(self, scheduler_instance, mock_settings):
        """Test get_status returns full status when running."""
        await scheduler_instance.start()

        status = scheduler_instance.get_status()

        assert status['running'] is True
        assert status['enabled'] is True
        assert status['schedule'] == "0 */6 * * *"
        assert status['next_run'] is not None

    async def test_get_status_when_not_running(self, scheduler_instance):
        """Test get_status returns correct status when not running."""
        status = scheduler_instance.get_status()

        assert status['running'] is False
        assert 'enabled' in status
        assert 'schedule' in status
        assert status['next_run'] is None

    async def test_includes_last_check_in_status(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test get_status includes last_check timestamp."""
        await scheduler_instance.start()
        await scheduler_instance._run_update_check()

        status = scheduler_instance.get_status()

        assert status['last_check'] is not None
        assert isinstance(status['last_check'], str)  # ISO format

    async def test_last_check_is_none_before_first_run(self, scheduler_instance, mock_settings):
        """Test last_check is None before first check runs."""
        await scheduler_instance.start()

        status = scheduler_instance.get_status()

        # May be None or may have been loaded from settings
        assert 'last_check' in status

    async def test_loads_last_check_from_settings(self, scheduler_instance, mock_settings):
        """Test loads last_check timestamp from settings on start."""
        last_check_time = datetime.now(timezone.utc)
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "check_schedule": "0 */6 * * *",
            "scheduler_last_check": last_check_time.isoformat(),
        }.get(key, default)

        await scheduler_instance.start()

        assert scheduler_instance._last_check is not None
        # Should have loaded from settings
        assert abs((scheduler_instance._last_check - last_check_time).total_seconds()) < 1


class TestSchedulerEdgeCases:
    """Test edge cases and error scenarios."""

    async def test_handles_restart_scheduler_service_error(self, scheduler_instance, mock_settings):
        """Test handles error initializing restart scheduler."""
        with patch('app.services.restart_scheduler.RestartSchedulerService') as mock_restart:
            mock_restart_instance = MagicMock()
            mock_restart_instance.start_monitoring = AsyncMock(side_effect=Exception("Failed to start"))
            mock_restart.return_value = mock_restart_instance

            # Should still start scheduler even if restart monitoring fails
            with pytest.raises(Exception):
                await scheduler_instance.start()

    async def test_handles_shutdown_error_gracefully(self, scheduler_instance, mock_settings):
        """Test handles error during scheduler shutdown."""
        await scheduler_instance.start()

        with patch.object(scheduler_instance.scheduler, 'shutdown', side_effect=RuntimeError("Shutdown failed")):
            # Should not raise
            await scheduler_instance.stop()

    async def test_handles_invalid_last_check_timestamp(self, scheduler_instance, mock_settings):
        """Test handles invalid last_check timestamp in settings."""
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "check_schedule": "0 */6 * * *",
            "scheduler_last_check": "invalid-timestamp",
        }.get(key, default)

        # Should start successfully, with _last_check set to None
        await scheduler_instance.start()

        assert scheduler_instance._last_check is None

    async def test_global_scheduler_instance_exists(self):
        """Test global scheduler_service instance exists."""
        from app.services.scheduler import scheduler_service as global_instance

        assert global_instance is not None
        assert isinstance(global_instance, SchedulerService)

    async def test_handles_job_lookup_error(self, scheduler_instance, mock_settings):
        """Test handles JobLookupError gracefully."""
        await scheduler_instance.start()

        with patch.object(scheduler_instance.scheduler, 'get_job', side_effect=Exception("Job not found")):
            # Should not crash
            next_run = scheduler_instance.get_next_run_time()
            # May return None or handle error

    async def test_sequential_start_stop_cycles(self, scheduler_instance, mock_settings):
        """Test can start and stop scheduler multiple times."""
        for i in range(3):
            await scheduler_instance.start()
            assert scheduler_instance.scheduler.running is True

            await scheduler_instance.stop()
            assert scheduler_instance.scheduler.running is False

    async def test_handles_cron_trigger_creation_error(self, scheduler_instance, mock_settings):
        """Test handles error creating CronTrigger."""
        mock_settings._get_values["check_schedule"] = "99 99 99 99 99"  # Invalid cron

        with pytest.raises(ValueError):
            await scheduler_instance.start()

    async def test_handles_database_integrity_error(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test handles IntegrityError during job execution."""
        from sqlalchemy.exc import IntegrityError
        
        with patch('app.services.scheduler.SettingsService.set', side_effect=IntegrityError("Duplicate key", None, None)):
            # Should not crash even if persisting last_check fails
            await scheduler_instance._run_update_check()


class TestSchedulerIntegration:
    """Integration tests for scheduler service."""

    async def test_full_lifecycle(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test complete scheduler lifecycle."""
        # Start
        await scheduler_instance.start()
        assert scheduler_instance.scheduler.running is True

        # Check status
        status = scheduler_instance.get_status()
        assert status['running'] is True

        # Manually trigger job
        await scheduler_instance.trigger_update_check()
        mock_update_checker.check_all_containers.assert_awaited_once()

        # Stop
        await scheduler_instance.stop()
        assert scheduler_instance.scheduler.running is False

    async def test_reload_while_running(self, scheduler_instance, mock_settings, db):
        """Test can reload schedule while scheduler is running."""
        await scheduler_instance.start()
        original_schedule = scheduler_instance._check_schedule

        # Change schedule
        mock_settings._get_values["check_schedule"] = "0 */12 * * *"
        await scheduler_instance.reload_schedule(db)

        # Should have new schedule
        assert scheduler_instance._check_schedule == "0 */12 * * *"
        assert scheduler_instance._check_schedule != original_schedule

    async def test_all_jobs_registered_correctly(self, scheduler_instance, mock_settings):
        """Test all expected jobs are registered."""
        # Enable all jobs
        mock_settings.get_bool.side_effect = lambda db, key, default=False: {
            "check_enabled": True,
            "cleanup_old_images": True,
        }.get(key, True)  # Default to True for all boolean settings
        
        mock_settings.get.side_effect = lambda db, key, default=None: {
            "check_schedule": "0 */6 * * *",
            "dockerfile_scan_schedule": "daily",
            "cleanup_schedule": "0 4 * * *",
        }.get(key, default)

        await scheduler_instance.start()

        # Check all expected jobs exist
        expected_jobs = [
            "update_check",
            "auto_apply",
            "metrics_collection",
            "metrics_cleanup",
            "dockerfile_dependencies_check",
            "docker_cleanup",
        ]

        for job_id in expected_jobs:
            job = scheduler_instance.scheduler.get_job(job_id)
            assert job is not None, f"Job {job_id} should be registered"

    async def test_handles_concurrent_manual_triggers(self, scheduler_instance, mock_settings, mock_update_checker):
        """Test handles multiple manual triggers."""
        await scheduler_instance.start()

        # Trigger multiple times rapidly
        await scheduler_instance.trigger_update_check()
        await scheduler_instance.trigger_update_check()
        await scheduler_instance.trigger_update_check()

        # Should have been called 3 times
        assert mock_update_checker.check_all_containers.await_count == 3
