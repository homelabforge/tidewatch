"""Restart scheduler service for monitoring and scheduling container restarts."""

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Container
from app.models.restart_state import ContainerRestartState
from app.services.container_monitor import container_monitor
from app.services.event_bus import event_bus
from app.services.restart_service import restart_service
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class RestartSchedulerService:
    """Manages intelligent container restart scheduling with APScheduler."""

    def __init__(self, scheduler: AsyncIOScheduler) -> None:
        """Initialize restart scheduler.

        Args:
            scheduler: APScheduler instance
        """
        self.scheduler = scheduler

    async def start_monitoring(self, db: AsyncSession):
        """Start the restart monitoring system.

        Args:
            db: Database session for getting settings
        """
        # Check if restart monitoring is enabled
        enabled = await SettingsService.get_bool(
            db, "restart_monitor_enabled", default=True
        )

        if not enabled:
            logger.info("Restart monitoring is disabled")
            return

        # Get monitor interval
        interval = await SettingsService.get_int(
            db, "restart_monitor_interval", default=30
        )

        # Add monitoring loop job
        self.scheduler.add_job(
            self._monitor_loop,
            "interval",
            seconds=interval,
            id="restart_monitor",
            name="Container Restart Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,  # Skip if previous run still executing
        )

        # Add cleanup job (runs hourly)
        self.scheduler.add_job(
            self._cleanup_successful_containers,
            "interval",
            hours=1,
            id="restart_cleanup",
            name="Reset Successful Container States",
            replace_existing=True,
            max_instances=1,
        )

        logger.info(f"Restart monitoring started (interval: {interval}s)")

    async def _monitor_loop(self):
        """Check for failed containers and schedule restarts."""
        async with AsyncSessionLocal() as db:
            try:
                # Get all containers with auto-restart enabled
                result = await db.execute(
                    select(Container).where(Container.auto_restart_enabled)
                )
                containers = result.scalars().all()

                logger.debug(
                    f"Monitoring {len(containers)} containers with auto-restart enabled"
                )

                for container in containers:
                    await self._check_and_schedule_restart(db, container)

            except OperationalError as e:
                logger.error(f"Database error in restart monitor loop: {e}")
            except (ImportError, AttributeError) as e:
                logger.error(f"Service dependency error in restart monitor loop: {e}")
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid data in restart monitor loop: {e}")

    async def _check_and_schedule_restart(self, db: AsyncSession, container: Container):
        """Check if container needs restart and schedule if needed.

        Args:
            db: Database session
            container: Container to check
        """
        try:
            # Get or create restart state
            state = await restart_service.get_or_create_restart_state(db, container)

            # Check if already scheduled
            if state.next_retry_at:
                # Ensure timezone-aware comparison (SQLite returns naive datetimes)
                next_retry = (
                    state.next_retry_at.replace(tzinfo=UTC)
                    if state.next_retry_at.tzinfo is None
                    else state.next_retry_at
                )
                if next_retry > datetime.now(UTC):
                    # Already scheduled, skip
                    return

            # Check if circuit breaker is open
            allowed, reason = await restart_service.check_circuit_breaker(
                db, container.id
            )
            if not allowed:
                logger.debug(f"Circuit breaker open for {container.name}: {reason}")
                return

            # Check container status
            container_state = await container_monitor.get_container_state(
                container.name
            )

            if not container_state:
                logger.warning(f"Could not get state for {container.name}")
                return

            is_running = container_state.get("running", False)

            if is_running:
                # Container is healthy, check if we should reset backoff
                if state.should_reset_backoff:
                    await restart_service.check_and_reset_backoff(db, state, container)
                return

            # Container is down, check if we should retry
            if state.max_retries_reached or not state.enabled:
                return

            # Get exit information
            exit_code = container_state.get("exit_code")
            oom_killed = container_state.get("oom_killed", False)
            container_state.get("error", "")

            # Determine if we should retry
            should_retry, failure_reason = await container_monitor.should_retry_restart(
                exit_code, oom_killed
            )

            if not should_retry:
                logger.info(
                    f"Container {container.name} exited with code {exit_code}, "
                    f"not retrying ({failure_reason})"
                )
                # Update state but don't schedule restart
                state.last_exit_code = exit_code
                state.last_failure_reason = failure_reason
                state.last_failure_at = datetime.now(UTC)
                await db.commit()
                return

            # Calculate backoff delay
            delay = await restart_service.calculate_backoff_delay(state, db)

            # Schedule restart
            run_time = datetime.now(UTC) + timedelta(seconds=delay)
            state.next_retry_at = run_time
            state.current_backoff_seconds = delay
            state.last_exit_code = exit_code
            state.last_failure_reason = failure_reason
            state.last_failure_at = datetime.now(UTC)
            state.consecutive_failures += 1

            # Check if max attempts reached
            if state.consecutive_failures >= state.max_attempts:
                state.max_retries_reached = True
                await db.commit()

                logger.warning(
                    f"Max retries reached for {container.name} "
                    f"({state.consecutive_failures} attempts)"
                )

                # Publish event
                await event_bus.publish(
                    {
                        "type": "restart-max-retries",
                        "container_id": container.id,
                        "container_name": container.name,
                        "attempts": state.consecutive_failures,
                        "exit_code": exit_code,
                    }
                )

                # Send notification
                notify = await SettingsService.get_bool(
                    db, "restart_notify_on_max_retries", default=True
                )
                if notify:
                    from app.services.notifications.dispatcher import (
                        NotificationDispatcher,
                    )

                    dispatcher = NotificationDispatcher(db)
                    await dispatcher.notify_max_retries_reached(
                        container.name, state.consecutive_failures, exit_code
                    )

                return

            await db.commit()

            # Schedule the dynamic restart job
            self.scheduler.add_job(
                self._execute_restart,
                "date",
                run_date=run_time,
                args=[container.id, state.consecutive_failures],
                id=f"restart_{container.id}_{state.consecutive_failures}",
                replace_existing=True,
                misfire_grace_time=60,  # Allow 60s delay if scheduler is busy
            )

            logger.info(
                f"Scheduled restart for {container.name} in {delay:.0f}s "
                f"(attempt {state.consecutive_failures}/{state.max_attempts}, "
                f"reason: {failure_reason})"
            )

            # Publish event
            await event_bus.publish(
                {
                    "type": "restart-scheduled",
                    "container_id": container.id,
                    "container_name": container.name,
                    "attempt": state.consecutive_failures,
                    "delay_seconds": delay,
                    "next_retry_at": run_time.isoformat(),
                    "reason": failure_reason,
                }
            )

        except OperationalError as e:
            logger.error(
                f"Database error checking restart for {container.name}: {e}",
                exc_info=True,
            )
        except (ImportError, AttributeError) as e:
            logger.error(
                f"Service dependency error checking restart for {container.name}: {e}",
                exc_info=True,
            )
        except (ValueError, KeyError) as e:
            logger.error(
                f"Invalid data checking restart for {container.name}: {e}",
                exc_info=True,
            )

    async def _execute_restart(self, container_id: int, attempt_number: int):
        """Execute a scheduled restart job.

        Args:
            container_id: Container ID to restart
            attempt_number: Current attempt number
        """
        async with AsyncSessionLocal() as db:
            try:
                # Get container
                result = await db.execute(
                    select(Container).where(Container.id == container_id)
                )
                container = result.scalar_one_or_none()

                if not container:
                    logger.error(f"Container {container_id} not found for restart")
                    return

                # Get restart state
                result = await db.execute(
                    select(ContainerRestartState).where(
                        ContainerRestartState.container_id == container_id
                    )
                )
                state = result.scalar_one_or_none()

                if not state:
                    logger.error(f"Restart state not found for {container.name}")
                    return

                # Double-check if container is still down
                container_state = await container_monitor.get_container_state(
                    container.name
                )

                if container_state and container_state.get("running"):
                    logger.info(
                        f"Container {container.name} is already running, skipping restart"
                    )
                    # Reset state since it's running
                    state.consecutive_failures = 0
                    state.next_retry_at = None
                    state.current_backoff_seconds = 0.0
                    state.last_successful_start = datetime.now(UTC)
                    await db.commit()
                    return

                # Execute restart
                trigger_reason = state.last_failure_reason or "scheduled"
                result = await restart_service.execute_restart(
                    db,
                    container,
                    state,
                    attempt_number,
                    trigger_reason,
                    state.last_exit_code,
                )

                if not result["success"]:
                    logger.warning(
                        f"Restart attempt {attempt_number} failed for {container.name}: "
                        f"{result.get('error')}"
                    )

                    # Send failure notification if enabled
                    notify = await SettingsService.get_bool(
                        db, "restart_notify_on_failure", default=True
                    )
                    if notify:
                        from app.services.notifications.dispatcher import (
                            NotificationDispatcher,
                        )

                        dispatcher = NotificationDispatcher(db)
                        await dispatcher.notify_restart_failure(
                            container.name,
                            attempt_number,
                            result.get("error", "Unknown error"),
                        )

            except OperationalError as e:
                logger.error(
                    f"Database error executing restart for container {container_id}: {e}",
                    exc_info=True,
                )
            except (ImportError, AttributeError) as e:
                logger.error(
                    f"Service dependency error executing restart for container {container_id}: {e}",
                    exc_info=True,
                )
            except (ValueError, KeyError) as e:
                logger.error(
                    f"Invalid data executing restart for container {container_id}: {e}",
                    exc_info=True,
                )

    async def _cleanup_successful_containers(self):
        """Reset restart states for containers that have been running successfully."""
        async with AsyncSessionLocal() as db:
            try:
                # Get all restart states
                result = await db.execute(select(ContainerRestartState))
                states = result.scalars().all()

                reset_count = 0

                for state in states:
                    # Get container
                    result = await db.execute(
                        select(Container).where(Container.id == state.container_id)
                    )
                    container = result.scalar_one_or_none()

                    if not container:
                        continue

                    # Check if should reset
                    if state.should_reset_backoff:
                        # Verify container is actually running
                        container_state = await container_monitor.get_container_state(
                            container.name
                        )

                        if container_state and container_state.get("running"):
                            await restart_service.check_and_reset_backoff(
                                db, state, container
                            )
                            reset_count += 1

                if reset_count > 0:
                    logger.info(f"Reset restart state for {reset_count} containers")

            except OperationalError as e:
                logger.error(f"Database error in cleanup job: {e}", exc_info=True)
            except (ImportError, AttributeError) as e:
                logger.error(
                    f"Service dependency error in cleanup job: {e}", exc_info=True
                )
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid data in cleanup job: {e}", exc_info=True)


# Note: This is instantiated by SchedulerService when it creates the APScheduler instance
