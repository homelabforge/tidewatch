"""Background scheduler service for automatic update checks."""

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, IntegrityError

from app.db import AsyncSessionLocal
from app.services.update_checker import UpdateChecker
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing background scheduled tasks."""

    def __init__(self) -> None:
        """Initialize the scheduler service."""
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._check_schedule: str = "0 */6 * * *"  # Default: every 6 hours
        self._enabled: bool = True
        self._last_check: Optional[datetime] = None  # Track last successful check
        self.restart_scheduler = None  # Will be initialized when scheduler starts

    async def start(self) -> None:
        """Start the background scheduler.

        Loads configuration from settings and starts the APScheduler.
        """
        try:
            # Load settings
            async with AsyncSessionLocal() as db:
                self._check_schedule = await SettingsService.get(
                    db, "check_schedule", default="0 */6 * * *"
                )
                self._enabled = await SettingsService.get_bool(
                    db, "check_enabled", default=True
                )

                # Load last check timestamp if persisted
                last_check_str = await SettingsService.get(db, "scheduler_last_check")
                if last_check_str:
                    try:
                        self._last_check = datetime.fromisoformat(last_check_str)
                    except ValueError:
                        self._last_check = None

                # Load dockerfile scan schedule while we have the session
                dockerfile_schedule = await SettingsService.get(
                    db, "dockerfile_scan_schedule", default="daily"
                )

                # Load cleanup settings
                cleanup_enabled = await SettingsService.get_bool(
                    db, "cleanup_old_images", default=False
                )
                cleanup_schedule = await SettingsService.get(
                    db, "cleanup_schedule", default="0 4 * * *"
                )

            if not self._enabled:
                logger.info("Automatic update checking is disabled in settings")
                return

            # Create scheduler
            self.scheduler = AsyncIOScheduler()

            # Add update check job
            self.scheduler.add_job(
                self._run_update_check,
                CronTrigger.from_crontab(self._check_schedule),
                id="update_check",
                name="Automatic Container Update Check",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
            )

            # Add auto-apply job (runs every 5 minutes)
            self.scheduler.add_job(
                self._run_auto_apply,
                CronTrigger.from_crontab("*/5 * * * *"),
                id="auto_apply",
                name="Automatic Update Application",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
            )

            # Add metrics collection job (runs every 5 minutes)
            self.scheduler.add_job(
                self._run_metrics_collection,
                CronTrigger.from_crontab("*/5 * * * *"),
                id="metrics_collection",
                name="Container Metrics Collection",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
            )

            # Add metrics cleanup job (runs daily at 3 AM)
            self.scheduler.add_job(
                self._run_metrics_cleanup,
                CronTrigger.from_crontab("0 3 * * *"),
                id="metrics_cleanup",
                name="Metrics History Cleanup",
                replace_existing=True,
                max_instances=1,
            )

            # Add Dockerfile dependencies update check job (runs based on setting, default daily at 3 AM)
            if dockerfile_schedule != "disabled":
                cron_schedule = (
                    "0 3 * * 0" if dockerfile_schedule == "weekly" else "0 3 * * *"
                )
                self.scheduler.add_job(
                    self._run_dockerfile_dependencies_check,
                    CronTrigger.from_crontab(cron_schedule),
                    id="dockerfile_dependencies_check",
                    name="Dockerfile Dependencies Update Check",
                    replace_existing=True,
                    max_instances=1,
                )

            # Add Docker cleanup job (runs on configured schedule, default 4 AM daily)
            if cleanup_enabled:
                self.scheduler.add_job(
                    self._run_docker_cleanup,
                    CronTrigger.from_crontab(cleanup_schedule),
                    id="docker_cleanup",
                    name="Docker Resource Cleanup",
                    replace_existing=True,
                    max_instances=1,
                )
                logger.info(f"Docker cleanup scheduled: {cleanup_schedule}")

            # Start the scheduler
            self.scheduler.start()
            logger.info(
                f"Background scheduler started with schedule: {self._check_schedule}"
            )

            # Log next run time
            job = self.scheduler.get_job("update_check")
            if job and job.next_run_time:
                logger.info(f"Next update check scheduled for: {job.next_run_time}")

            # Initialize and start restart monitoring
            async with AsyncSessionLocal() as db:
                from app.services.restart_scheduler import RestartSchedulerService

                self.restart_scheduler = RestartSchedulerService(self.scheduler)
                await self.restart_scheduler.start_monitoring(db)
                logger.info("Restart monitoring initialized")

        except OperationalError as e:
            logger.error(f"Database connection error during scheduler start: {e}")
            raise
        except ValueError as e:
            logger.error(f"Invalid cron schedule or configuration: {e}")
            raise
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to import required service module: {e}")
            raise

    async def stop(self) -> None:
        """Stop the background scheduler.

        Shuts down the APScheduler gracefully.
        """
        if self.scheduler:
            try:
                import asyncio

                self.scheduler.shutdown(wait=False)
                # Give event loop a chance to process shutdown
                await asyncio.sleep(0)
                logger.info("Background scheduler stopped")
            except RuntimeError as e:
                logger.error(f"Scheduler shutdown error: {e}")
            except OSError as e:
                logger.error(f"I/O error during scheduler shutdown: {e}")

    async def reload_schedule(self, db: AsyncSession):
        """Reload the schedule from settings and reschedule jobs.

        Args:
            db: Database session
        """
        try:
            # Load new settings
            new_schedule = await SettingsService.get(
                db, "check_schedule", default="0 */6 * * *"
            )
            new_enabled = await SettingsService.get_bool(
                db, "check_enabled", default=True
            )

            # Check if schedule changed
            if new_schedule != self._check_schedule or new_enabled != self._enabled:
                logger.info(
                    f"Schedule changed: {self._check_schedule} -> {new_schedule}, "
                    f"enabled: {self._enabled} -> {new_enabled}"
                )

                self._check_schedule = new_schedule
                self._enabled = new_enabled

                # Restart scheduler with new settings
                await self.stop()
                await self.start()

        except OperationalError as e:
            logger.error(f"Database error reloading schedule: {e}")
        except ValueError as e:
            logger.error(f"Invalid schedule configuration: {e}")
        except RuntimeError as e:
            logger.error(f"Scheduler restart error: {e}")

    async def _run_update_check(self):
        """Run the update check job.

        This is the actual job that runs on schedule.
        Creates a new database session and calls UpdateChecker.
        """
        logger.info("Starting scheduled update check")
        start_time = datetime.now()

        try:
            # Create a new database session for this job
            async with AsyncSessionLocal() as db:
                # Run the update checker
                stats = await UpdateChecker.check_all_containers(db)

                # Log results
                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Scheduled update check completed in {duration:.2f}s: "
                    f"{stats['checked']}/{stats['total']} containers checked, "
                    f"{stats['updates_found']} updates found, "
                    f"{stats['errors']} errors"
                )

                # Update last check timestamp
                self._last_check = datetime.now(timezone.utc)

                # Persist to settings for recovery after restarts
                await SettingsService.set(
                    db, "scheduler_last_check", self._last_check.isoformat()
                )

        except (OperationalError, IntegrityError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during scheduled update check after {duration:.2f}s: {e}"
            )
        except (KeyError, ValueError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Invalid data during scheduled update check after {duration:.2f}s: {e}"
            )

    async def _run_auto_apply(self):
        """Apply approved updates for containers with auto policies.

        This job runs periodically to apply updates that have been
        auto-approved by the update checker, respecting update windows
        and dependency ordering.
        """
        logger.info("Starting auto-apply job")
        start_time = datetime.now()

        try:
            async with AsyncSessionLocal() as db:
                # Check if auto-update is enabled globally
                auto_update_enabled = await SettingsService.get_bool(
                    db, "auto_update_enabled", default=False
                )

                if not auto_update_enabled:
                    logger.debug("Auto-update is disabled, skipping auto-apply")
                    return

                # Get all approved updates and retries
                from sqlalchemy import select, or_, and_
                from app.models.update import Update
                from app.models.container import Container
                from app.services.update_engine import UpdateEngine
                from app.services.update_window import UpdateWindow
                from app.services.dependency_manager import DependencyManager

                now = datetime.now()

                result = await db.execute(
                    select(Update, Container)
                    .join(Container, Update.container_id == Container.id)
                    .where(
                        or_(
                            # Regular auto-approved updates
                            and_(
                                Update.status == "approved",
                                Update.approved_by == "system",
                                Container.policy.in_(["auto", "security"]),
                            ),
                            # Pending retries that are ready
                            and_(
                                Update.status == "pending_retry",
                                Update.next_retry_at <= now,
                            ),
                        )
                    )
                    .order_by(Update.created_at.asc())  # FIFO order
                )
                updates_with_containers = result.all()

                if not updates_with_containers:
                    logger.debug("No auto-approved updates or retries to apply")
                    return

                # Filter by update windows
                eligible_updates = []
                for update, container in updates_with_containers:
                    # Check update window
                    if container.update_window:
                        if not UpdateWindow.is_in_window(container.update_window, now):
                            logger.debug(
                                f"Skipping {container.name}: outside update window "
                                f"{container.update_window}"
                            )
                            continue

                    eligible_updates.append(update)

                if not eligible_updates:
                    logger.debug("No eligible updates after window filtering")
                    return

                # Get max concurrent updates setting
                max_concurrent = await SettingsService.get_int(
                    db, "auto_update_max_concurrent", default=3
                )

                # Limit updates per run
                if len(eligible_updates) > max_concurrent:
                    logger.info(f"Rate limiting to {max_concurrent} updates per run")
                    eligible_updates = eligible_updates[:max_concurrent]

                # Get container names for dependency ordering
                container_names = [u.container_name for u in eligible_updates]

                # Order by dependencies
                try:
                    ordered_names = await DependencyManager.get_update_order(
                        db, container_names
                    )
                    # Reorder updates based on dependency order
                    update_map = {u.container_name: u for u in eligible_updates}
                    ordered_updates = [update_map[name] for name in ordered_names]
                except (ValueError, KeyError) as e:
                    logger.error(
                        f"Dependency ordering failed (invalid data): {e}, using original order"
                    )
                    ordered_updates = eligible_updates
                except OperationalError as e:
                    logger.error(
                        f"Database error during dependency ordering: {e}, using original order"
                    )
                    ordered_updates = eligible_updates

                logger.info(
                    f"Found {len(ordered_updates)} eligible updates to apply "
                    f"(ordered by dependencies)"
                )

                applied = 0
                failed = 0

                # Apply each update sequentially (safer than parallel)
                for update in ordered_updates:
                    try:
                        retry_info = ""
                        if update.status == "pending_retry":
                            retry_info = f" (retry {update.retry_count + 1}/{update.max_retries})"

                        logger.info(
                            f"Auto-applying update {update.id} for {update.container_name}: "
                            f"{update.from_tag} -> {update.to_tag}{retry_info}"
                        )

                        result = await UpdateEngine.apply_update(
                            db, update.id, triggered_by="scheduler"
                        )

                        if result["success"]:
                            applied += 1
                            logger.info(f"Successfully auto-applied update {update.id}")
                        else:
                            failed += 1
                            logger.error(
                                f"Failed to auto-apply update {update.id}: "
                                f"{result.get('message')}"
                            )

                    except OperationalError as e:
                        failed += 1
                        logger.error(
                            f"Database error auto-applying update {update.id}: {e}"
                        )
                    except (ValueError, KeyError) as e:
                        failed += 1
                        logger.error(
                            f"Invalid data auto-applying update {update.id}: {e}"
                        )

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Auto-apply job completed in {duration:.2f}s: "
                    f"{applied} applied, {failed} failed"
                )

        except OperationalError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during auto-apply job after {duration:.2f}s: {e}"
            )
        except (ImportError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Failed to import required module during auto-apply after {duration:.2f}s: {e}"
            )
        except (ValueError, KeyError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Invalid data during auto-apply job after {duration:.2f}s: {e}"
            )

    async def _run_metrics_collection(self):
        """Run metrics collection job.

        Collects current metrics for all running containers.
        """
        logger.debug("Starting metrics collection")
        start_time = datetime.now()

        try:
            async with AsyncSessionLocal() as db:
                from app.services.metrics_collector import metrics_collector

                stats = await metrics_collector.collect_all_metrics(db)

                duration = (datetime.now() - start_time).total_seconds()
                logger.debug(
                    f"Metrics collection completed in {duration:.2f}s: "
                    f"{stats['collected']} collected, {stats['skipped']} skipped"
                )
        except OperationalError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during metrics collection after {duration:.2f}s: {e}"
            )
        except (ImportError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Failed to import metrics collector after {duration:.2f}s: {e}"
            )
        except (KeyError, ValueError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Invalid metrics data after {duration:.2f}s: {e}")

    async def _run_metrics_cleanup(self):
        """Run metrics cleanup job.

        Removes old metrics data (older than 30 days).
        """
        logger.info("Starting metrics cleanup")
        start_time = datetime.now()

        try:
            async with AsyncSessionLocal() as db:
                from app.services.metrics_collector import metrics_collector

                deleted = await metrics_collector.cleanup_old_metrics(db, days=30)

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Metrics cleanup completed in {duration:.2f}s: "
                    f"{deleted} records deleted"
                )
        except OperationalError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during metrics cleanup after {duration:.2f}s: {e}"
            )
        except (ImportError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Failed to import metrics collector after {duration:.2f}s: {e}"
            )

    async def _run_dockerfile_dependencies_check(self):
        """Run Dockerfile dependencies update check job.

        Checks all Dockerfile dependencies for available updates.
        """
        logger.info("Starting Dockerfile dependencies update check")
        start_time = datetime.now()

        try:
            async with AsyncSessionLocal() as db:
                from app.services.dockerfile_parser import DockerfileParser
                from sqlalchemy import select
                from app.models.dockerfile_dependency import DockerfileDependency

                # Check all dependencies for updates
                parser = DockerfileParser()
                stats = await parser.check_all_for_updates(db)

                total_scanned = stats.get("total_scanned", 0)
                updates_found = stats.get("updates_found", 0)

                # Send notifications for dependencies with updates
                if updates_found > 0:
                    # Get all dependencies with updates
                    stmt = select(DockerfileDependency).where(
                        DockerfileDependency.update_available
                    )
                    result = await db.execute(stmt)
                    deps_with_updates = result.scalars().all()

                    from app.services.notifications.dispatcher import (
                        NotificationDispatcher,
                    )

                    dispatcher = NotificationDispatcher(db)
                    for dep in deps_with_updates:
                        await dispatcher.notify_dockerfile_update(
                            image_name=dep.image_name,
                            from_tag=dep.current_tag,
                            to_tag=dep.latest_tag or "unknown",
                            dependency_type=dep.dependency_type,
                        )

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Dockerfile dependencies check completed in {duration:.2f}s: "
                    f"{total_scanned} dependencies checked, {updates_found} updates found"
                )

        except OperationalError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during Dockerfile dependencies check after {duration:.2f}s: {e}"
            )
        except (ImportError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Failed to import required module after {duration:.2f}s: {e}")
        except (KeyError, ValueError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Invalid data during Dockerfile dependencies check after {duration:.2f}s: {e}"
            )

    async def _run_docker_cleanup(self):
        """Run Docker resource cleanup job.

        Cleans up dangling images, exited containers, and optionally
        old unused images based on settings.
        """
        logger.info("Starting scheduled Docker cleanup")
        start_time = datetime.now()

        try:
            async with AsyncSessionLocal() as db:
                from app.services.cleanup_service import CleanupService

                # Get cleanup settings
                cleanup_mode = await SettingsService.get(
                    db, "cleanup_mode", default="dangling"
                )
                cleanup_days = await SettingsService.get_int(
                    db, "cleanup_after_days", default=7
                )
                cleanup_containers = await SettingsService.get_bool(
                    db, "cleanup_containers", default=True
                )
                exclude_patterns_str = await SettingsService.get(
                    db, "cleanup_exclude_patterns", default="-dev,rollback"
                )

                # Parse exclude patterns
                exclude_patterns = [
                    p.strip() for p in exclude_patterns_str.split(",") if p.strip()
                ]

                # Run cleanup
                result = await CleanupService.run_cleanup(
                    mode=cleanup_mode,
                    days=cleanup_days,
                    exclude_patterns=exclude_patterns,
                    cleanup_containers=cleanup_containers,
                )

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Docker cleanup completed in {duration:.2f}s: "
                    f"{result.get('images_removed', 0)} images removed, "
                    f"{result.get('containers_removed', 0)} containers removed, "
                    f"{result.get('space_reclaimed_formatted', '0 B')} reclaimed"
                )

                # Send notification if enabled and cleanup was performed
                # Note: Docker cleanup notifications use the system notification group
                total_removed = result.get("images_removed", 0) + result.get(
                    "containers_removed", 0
                )
                if total_removed > 0:
                    from app.services.notifications.dispatcher import (
                        NotificationDispatcher,
                    )

                    dispatcher = NotificationDispatcher(db)

                    # Use check_complete event type for system notifications
                    await dispatcher.dispatch(
                        event_type="check_complete",
                        title="Docker Cleanup Complete",
                        message=(
                            f"Removed {result.get('images_removed', 0)} images and "
                            f"{result.get('containers_removed', 0)} containers. "
                            f"Reclaimed {result.get('space_reclaimed_formatted', '0 B')}."
                        ),
                        priority="low",
                        tags=["broom", "docker"],
                    )

        except OperationalError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Database error during Docker cleanup after {duration:.2f}s: {e}"
            )
        except (ImportError, AttributeError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Failed to import cleanup service after {duration:.2f}s: {e}")
        except (KeyError, ValueError) as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(
                f"Invalid data during Docker cleanup after {duration:.2f}s: {e}"
            )

    async def trigger_update_check(self):
        """Manually trigger an update check outside the schedule.

        This allows the API to trigger immediate checks.
        """
        logger.info("Manually triggered update check")
        await self._run_update_check()

    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time.

        Returns:
            Next run time or None if scheduler not running
        """
        if not self.scheduler:
            return None

        try:
            job = self.scheduler.get_job("update_check")
            if job:
                return job.next_run_time
        except (JobLookupError, Exception) as e:
            logger.warning(f"Failed to get job: {e}")
            return None

        return None

    def get_status(self) -> dict:
        """Get scheduler status information.

        Returns:
            Dict with scheduler status details
        """
        if not self.scheduler or not self.scheduler.running:
            return {
                "running": False,
                "enabled": self._enabled,
                "schedule": self._check_schedule,
                "next_run": None,
                "last_check": self._last_check.isoformat()
                if self._last_check
                else None,
            }

        job = self.scheduler.get_job("update_check")
        next_run = job.next_run_time if job else None

        return {
            "running": True,
            "enabled": self._enabled,
            "schedule": self._check_schedule,
            "next_run": next_run.isoformat() if next_run else None,
            "last_check": self._last_check.isoformat() if self._last_check else None,
        }


# Global scheduler instance
scheduler_service = SchedulerService()
