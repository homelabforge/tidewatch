"""Check job service for managing background update checks.

Provides concurrent execution of container update checks with:
- Bounded concurrency (configurable)
- Per-registry rate limiting
- Container deduplication (shared images checked once)
- Run-scoped caching
- Progress events for real-time UI updates
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.check_job import CheckJob
from app.models.container import Container
from app.services.check_run_context import CheckRunContext, ImageCheckKey
from app.services.event_bus import event_bus
from app.services.registry_client import is_non_semver_tag
from app.services.registry_rate_limiter import RegistryRateLimiter
from app.services.settings_service import SettingsService
from app.services.tag_fetcher import TagFetcher
from app.services.update_checker import UpdateChecker
from app.services.update_decision_maker import UpdateDecisionMaker

logger = logging.getLogger(__name__)


class CheckJobService:
    """Service for managing background update check jobs.

    Provides methods to create, track, and execute update check jobs
    asynchronously with progress reporting via SSE events.

    The run_job method supports two execution modes:
    - Concurrent (default): Multiple containers checked in parallel with
      rate limiting and deduplication
    - Sequential: Legacy mode, one container at a time (when concurrency=1)
    """

    @staticmethod
    async def get_active_job(db: AsyncSession) -> CheckJob | None:
        """Get currently active (queued or running) job if any.

        Args:
            db: Database session

        Returns:
            Active CheckJob or None
        """
        result = await db.execute(
            select(CheckJob)
            .where(CheckJob.status.in_(["queued", "running"]))
            .order_by(CheckJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_job(db: AsyncSession, triggered_by: str = "user") -> CheckJob:
        """Create a new check job.

        Args:
            db: Database session
            triggered_by: Who triggered the job (user, scheduler)

        Returns:
            Created CheckJob
        """
        # Count containers that will be checked
        result = await db.execute(select(Container).where(Container.policy != "disabled"))
        containers = result.scalars().all()

        job = CheckJob(
            status="queued",
            total_count=len(containers),
            triggered_by=triggered_by,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Publish creation event
        await event_bus.publish(
            {
                "type": "check-job-created",
                "job_id": job.id,
                "total_count": job.total_count,
                "triggered_by": triggered_by,
            }
        )

        logger.info(
            f"Created check job {job.id} ({triggered_by}): {job.total_count} containers to check"
        )

        return job

    @staticmethod
    async def get_job(db: AsyncSession, job_id: int) -> CheckJob | None:
        """Get a check job by ID.

        Args:
            db: Database session
            job_id: Job ID

        Returns:
            CheckJob or None
        """
        result = await db.execute(select(CheckJob).where(CheckJob.id == job_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_recent_jobs(db: AsyncSession, limit: int = 20) -> list[CheckJob]:
        """Get recent check jobs.

        Args:
            db: Database session
            limit: Maximum number of jobs to return

        Returns:
            List of recent CheckJob records
        """
        result = await db.execute(
            select(CheckJob).order_by(CheckJob.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def request_cancellation(db: AsyncSession, job_id: int) -> None:
        """Request cancellation of a job.

        Sets the cancel_requested flag. The running job will stop
        after completing the current container.

        Args:
            db: Database session
            job_id: Job ID to cancel
        """
        await db.execute(update(CheckJob).where(CheckJob.id == job_id).values(cancel_requested=1))
        await db.commit()

        await event_bus.publish(
            {
                "type": "check-job-cancel-requested",
                "job_id": job_id,
            }
        )

        # Use explicit int() cast to prevent log injection (job_id is already int-typed)
        logger.info("Cancellation requested for check job %d", int(job_id))

    @staticmethod
    async def run_job(job_id: int) -> None:
        """Execute the check job with bounded concurrent execution.

        This method:
        1. Initializes rate limiter and run context
        2. Groups containers by image signature for deduplication
        3. Executes checks concurrently with bounded parallelism
        4. Reports progress via SSE events

        Args:
            job_id: ID of the job to run
        """
        async with AsyncSessionLocal() as db:
            job: CheckJob | None = None
            try:
                # Get job and mark as running
                job = await CheckJobService.get_job(db, job_id)
                if not job:
                    logger.warning(f"Check job {job_id} not found")
                    return
                if str(job.status) != "queued":  # type: ignore[attr-defined]
                    logger.warning(f"Check job {job_id} not in queued state: {job.status}")
                    return

                job.status = "running"  # type: ignore[attr-defined]
                job.started_at = datetime.now(UTC)  # type: ignore[attr-defined]
                await db.commit()

                await event_bus.publish(
                    {
                        "type": "check-job-started",
                        "job_id": job_id,
                        "total_count": job.total_count,
                    }
                )

                logger.info(f"Started check job {job_id}")

                # Get configuration
                concurrency_limit = await SettingsService.get_int(
                    db, "check_concurrency_limit", default=5
                )
                deduplication_enabled = await SettingsService.get_bool(
                    db, "check_deduplication_enabled", default=True
                )
                global_include_prereleases = await SettingsService.get_bool(
                    db, "include_prereleases", default=False
                )

                # Get containers to check
                result = await db.execute(select(Container).where(Container.policy != "disabled"))
                containers = list(result.scalars().all())

                if not containers:
                    logger.info(f"Check job {job_id}: No containers to check")
                    job.status = "done"  # type: ignore[attr-defined]
                    job.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]
                    job.results = []  # type: ignore[attr-defined]
                    job.errors = []  # type: ignore[attr-defined]
                    await db.commit()
                    await event_bus.publish(
                        {
                            "type": "check-job-completed",
                            "job_id": job_id,
                            "checked_count": 0,
                            "total_count": 0,
                            "updates_found": 0,
                            "errors_count": 0,
                            "duration_seconds": 0,
                        }
                    )
                    return

                # Initialize rate limiter and run context
                rate_limiter = RegistryRateLimiter(global_concurrency=concurrency_limit)
                run_context = CheckRunContext(job_id=job_id)

                # Build include_prereleases lookup for each container (tri-state)
                # None=inherit global, True=force include, False=force stable only
                include_prereleases_lookup: dict[int, bool] = {}
                for container in containers:
                    container_id: int = container.id  # type: ignore[attr-defined]
                    container_prereleases: bool | None = container.include_prereleases  # type: ignore[attr-defined]
                    if container_prereleases is not None:
                        include_prereleases_lookup[container_id] = container_prereleases
                    else:
                        include_prereleases_lookup[container_id] = global_include_prereleases

                # Group containers for deduplication (if enabled)
                if deduplication_enabled:
                    groups = run_context.group_containers(containers, include_prereleases_lookup)
                else:
                    # No grouping - each container is its own group
                    groups = {
                        ImageCheckKey.from_container(
                            c,
                            include_prereleases_lookup.get(c.id, False),  # type: ignore[attr-defined]
                        ): [c]
                        for c in containers
                    }
                    run_context.metrics.total_containers = len(containers)
                    run_context.metrics.unique_images = len(containers)

                # Shared state for progress tracking (with lock)
                progress_lock = asyncio.Lock()
                results: list[dict[str, Any]] = []
                errors: list[dict[str, Any]] = []
                cancel_requested = False

                # Shared counters for progress (protected by progress_lock)
                checked_count = 0
                updates_found = 0
                errors_count = 0

                # Cache total_count as local int for use in workers
                total_count: int = int(job.total_count)  # type: ignore[attr-defined]

                # Worker function for checking a container group
                async def check_group(
                    key: ImageCheckKey,
                    group_containers: list[Container],
                    semaphore: asyncio.Semaphore,
                ) -> None:
                    nonlocal cancel_requested, checked_count, updates_found, errors_count

                    async with semaphore:
                        # Check for cancellation before starting
                        if cancel_requested:
                            return

                        start_time = time.monotonic()

                        # Each worker gets its own database session
                        async with AsyncSessionLocal() as worker_db:
                            try:
                                # Re-fetch containers in this session to avoid detached instance errors
                                container_ids = [c.id for c in group_containers]  # type: ignore[attr-defined]
                                result = await worker_db.execute(
                                    select(Container).where(Container.id.in_(container_ids))
                                )
                                fresh_containers = list(result.scalars().all())

                                # Get the representative container (first one)
                                fresh_representative = (
                                    fresh_containers[0] if fresh_containers else None
                                )
                                if not fresh_representative:
                                    raise ValueError(f"No containers found for group {key.image}")

                                # Fetch tags for this image signature
                                tag_fetcher = TagFetcher(worker_db, rate_limiter, run_context)
                                fetch_response = await tag_fetcher.fetch_tags_for_key(
                                    key,
                                    current_digest=(
                                        fresh_representative.current_digest  # type: ignore[attr-defined]
                                        if is_non_semver_tag(key.current_tag)
                                        else None
                                    ),
                                )

                                # Make update decision
                                decision_maker = UpdateDecisionMaker()
                                decision = decision_maker.make_decision(
                                    fresh_representative,
                                    fetch_response,
                                    key.include_prereleases,
                                )

                                # Apply decision to all containers in group
                                for container in fresh_containers:
                                    if cancel_requested:
                                        break

                                    container_name: str = str(container.name)  # type: ignore[attr-defined]
                                    container_id: int = container.id  # type: ignore[attr-defined]

                                    try:
                                        update_obj = await UpdateChecker.apply_decision(
                                            worker_db,
                                            container,
                                            decision,
                                            fetch_response,
                                        )
                                        await worker_db.commit()

                                        # Update progress counters (thread-safe with lock)
                                        async with progress_lock:
                                            checked_count += 1
                                            if update_obj:
                                                updates_found += 1
                                                run_context.metrics.record_update_found()
                                                results.append(
                                                    {
                                                        "container_id": container_id,
                                                        "container_name": container_name,
                                                        "update_found": True,
                                                        "from_tag": update_obj.from_tag,
                                                        "to_tag": update_obj.to_tag,
                                                    }
                                                )
                                            else:
                                                results.append(
                                                    {
                                                        "container_id": container_id,
                                                        "container_name": container_name,
                                                        "update_found": False,
                                                    }
                                                )

                                        # Publish progress event
                                        await event_bus.publish(
                                            {
                                                "type": "check-job-progress",
                                                "job_id": job_id,
                                                "status": "running",
                                                "checked_count": checked_count,
                                                "total_count": total_count,
                                                "current_container": container_name,
                                                "updates_found": updates_found,
                                                "errors_count": errors_count,
                                                "progress_percent": int(
                                                    (checked_count / total_count) * 100
                                                )
                                                if total_count > 0
                                                else 0,
                                            }
                                        )

                                    except Exception as container_error:
                                        logger.error(
                                            f"Error applying decision to {container_name}: "
                                            f"{container_error}"
                                        )
                                        async with progress_lock:
                                            checked_count += 1
                                            errors_count += 1
                                            run_context.metrics.record_error()
                                            errors.append(
                                                {
                                                    "container_id": container_id,
                                                    "container_name": container_name,
                                                    "error": str(container_error),
                                                }
                                            )
                                        await worker_db.rollback()

                                # Record metrics
                                latency = time.monotonic() - start_time
                                run_context.metrics.record_container_check(
                                    key.registry, latency, fetch_response.cache_hit
                                )

                            except Exception as group_error:
                                logger.error(f"Error checking group {key.image}: {group_error}")
                                # Record error for all containers in group
                                async with progress_lock:
                                    for container in group_containers:
                                        container_id = container.id  # type: ignore[attr-defined]
                                        container_name = str(container.name)  # type: ignore[attr-defined]
                                        checked_count += 1
                                        errors_count += 1
                                        run_context.metrics.record_error()
                                        errors.append(
                                            {
                                                "container_id": container_id,
                                                "container_name": container_name,
                                                "error": str(group_error),
                                            }
                                        )

                # Check for cancellation periodically
                async def cancellation_monitor() -> None:
                    nonlocal cancel_requested
                    while not cancel_requested:
                        await asyncio.sleep(1)
                        await db.refresh(job)
                        if bool(job.cancel_requested):  # type: ignore[attr-defined]
                            cancel_requested = True
                            logger.info(f"Check job {job_id}: Cancellation detected")
                            break

                # Create bounded semaphore
                semaphore = asyncio.Semaphore(concurrency_limit)

                # Start cancellation monitor
                cancel_task = asyncio.create_task(cancellation_monitor())

                # Execute all groups concurrently with bounded parallelism
                try:
                    tasks = [
                        check_group(key, group_containers, semaphore)
                        for key, group_containers in groups.items()
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    cancel_task.cancel()
                    try:
                        await cancel_task
                    except asyncio.CancelledError:
                        logger.debug("Cancellation monitor task stopped")

                # Finalize metrics
                metrics = run_context.finalize()

                # Check final cancellation state
                await db.refresh(job)
                job_cancel_requested: bool = bool(job.cancel_requested)  # type: ignore[attr-defined]
                total_count: int = int(job.total_count)  # type: ignore[attr-defined]

                if job_cancel_requested or cancel_requested:
                    job.status = "canceled"  # type: ignore[attr-defined]
                    job.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]
                    job.current_container_id = None  # type: ignore[attr-defined]
                    job.current_container_name = None  # type: ignore[attr-defined]
                    job.checked_count = checked_count  # type: ignore[attr-defined]
                    job.updates_found = updates_found  # type: ignore[attr-defined]
                    job.errors_count = errors_count  # type: ignore[attr-defined]
                    job.results = results  # type: ignore[attr-defined]
                    job.errors = errors  # type: ignore[attr-defined]
                    await db.commit()

                    await event_bus.publish(
                        {
                            "type": "check-job-canceled",
                            "job_id": job_id,
                            "checked_count": checked_count,
                            "total_count": total_count,
                            "updates_found": updates_found,
                        }
                    )

                    logger.info(f"Check job {job_id} canceled at {checked_count}/{total_count}")
                    return

                # Mark job as complete
                job.status = "done"  # type: ignore[attr-defined]
                job.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]
                job.current_container_id = None  # type: ignore[attr-defined]
                job.current_container_name = None  # type: ignore[attr-defined]
                job.checked_count = checked_count  # type: ignore[attr-defined]
                job.updates_found = updates_found  # type: ignore[attr-defined]
                job.errors_count = errors_count  # type: ignore[attr-defined]
                job.results = results  # type: ignore[attr-defined]
                job.errors = errors  # type: ignore[attr-defined]
                await db.commit()

                # Calculate duration (use metrics duration which handles timezone properly)
                duration_seconds: float = metrics.duration_seconds or 0.0

                await event_bus.publish(
                    {
                        "type": "check-job-completed",
                        "job_id": job_id,
                        "checked_count": checked_count,
                        "total_count": total_count,
                        "updates_found": updates_found,
                        "errors_count": errors_count,
                        "duration_seconds": duration_seconds,
                        "metrics": {
                            "deduplicated_containers": metrics.deduplicated_containers,
                            "unique_images": metrics.unique_images,
                            "cache_hit_rate": metrics.cache_hit_rate,
                            "avg_container_latency": metrics.avg_container_latency,
                        },
                    }
                )

                logger.info(
                    f"Check job {job_id} completed: "
                    f"{checked_count} checked, "
                    f"{updates_found} updates found, "
                    f"{errors_count} errors, "
                    f"deduplicated={metrics.deduplicated_containers}, "
                    f"cache_hit_rate={metrics.cache_hit_rate:.1f}%"
                )

            except Exception as e:
                logger.error(f"Check job {job_id} failed: {e}", exc_info=True)
                try:
                    if job:
                        job.status = "failed"  # type: ignore[attr-defined]
                        job.error_message = str(e)  # type: ignore[attr-defined]
                        job.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]
                        job.current_container_id = None  # type: ignore[attr-defined]
                        job.current_container_name = None  # type: ignore[attr-defined]
                        await db.commit()
                except Exception:
                    pass  # Best effort to record failure

                await event_bus.publish(
                    {
                        "type": "check-job-failed",
                        "job_id": job_id,
                        "error": str(e),
                    }
                )

    @staticmethod
    def start_job_background(job_id: int) -> None:
        """Start a check job as a background task.

        This should be called after creating a job to execute it
        asynchronously without blocking the API response.

        Args:
            job_id: ID of the job to run
        """
        asyncio.create_task(CheckJobService.run_job(job_id))
