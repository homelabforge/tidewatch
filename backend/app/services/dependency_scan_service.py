"""Dependency scan service for managing background dependency scans.

Provides concurrent execution of dependency scans for My Projects with:
- Bounded concurrency
- Progress events for real-time UI updates
- Cancellation support
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.container import Container
from app.models.dependency_scan_job import DependencyScanJob
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)


class DependencyScanService:
    """Service for managing background dependency scan jobs."""

    @staticmethod
    async def get_active_job(db: AsyncSession) -> DependencyScanJob | None:
        """Get currently active (queued or running) job if any.

        Args:
            db: Database session

        Returns:
            Active DependencyScanJob or None
        """
        result = await db.execute(
            select(DependencyScanJob)
            .where(DependencyScanJob.status.in_(["queued", "running"]))
            .order_by(DependencyScanJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_job(db: AsyncSession, triggered_by: str = "user") -> DependencyScanJob:
        """Create a new dependency scan job.

        Args:
            db: Database session
            triggered_by: Who triggered the job (user, scheduler)

        Returns:
            Created DependencyScanJob
        """
        # Count My Project containers
        result = await db.execute(
            select(Container).where(Container.is_my_project == True)  # noqa: E712
        )
        projects = result.scalars().all()

        job = DependencyScanJob(
            status="queued",
            total_count=len(projects),
            triggered_by=triggered_by,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        logger.info(
            "Created dependency scan job %d (%s): %d projects to scan",
            job.id,
            triggered_by,
            job.total_count,
        )

        return job

    @staticmethod
    async def get_job(db: AsyncSession, job_id: int) -> DependencyScanJob | None:
        """Get a dependency scan job by ID.

        Args:
            db: Database session
            job_id: Job ID

        Returns:
            DependencyScanJob or None
        """
        result = await db.execute(select(DependencyScanJob).where(DependencyScanJob.id == job_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def request_cancellation(db: AsyncSession, job_id: int) -> None:
        """Request cancellation of a job.

        Args:
            db: Database session
            job_id: Job ID to cancel
        """
        await db.execute(
            update(DependencyScanJob)
            .where(DependencyScanJob.id == job_id)
            .values(cancel_requested=1)
        )
        await db.commit()

        await event_bus.publish(
            {
                "type": "dependency-scan-cancel-requested",
                "job_id": job_id,
            }
        )

        logger.info("Cancellation requested for dependency scan job %d", int(job_id))

    @staticmethod
    def start_job_background(job_id: int) -> None:
        """Start a dependency scan job as a background task.

        Args:
            job_id: ID of the job to run
        """
        asyncio.create_task(DependencyScanService.run_job(job_id))

    @staticmethod
    async def run_job(job_id: int) -> None:
        """Execute the dependency scan job.

        Scans all My Project containers for dependency updates:
        - HTTP servers (filesystem detection)
        - Dockerfile dependencies
        - App dependencies (npm, pypi)

        Args:
            job_id: ID of the job to run
        """
        async with AsyncSessionLocal() as db:
            job: DependencyScanJob | None = None
            try:
                job = await DependencyScanService.get_job(db, job_id)
                if not job:
                    logger.warning("Dependency scan job %d not found", job_id)
                    return

                # Mark as running
                job.status = "running"
                job.started_at = datetime.now(UTC)
                await db.commit()

                await event_bus.publish(_build_progress_event("dependency-scan-started", job))

                # Get all My Project containers
                result = await db.execute(
                    select(Container).where(Container.is_my_project == True)  # noqa: E712
                )
                projects = list(result.scalars().all())

                job.total_count = len(projects)
                await db.commit()

                # Process each project with bounded concurrency
                semaphore = asyncio.Semaphore(3)
                lock = asyncio.Lock()
                all_results: list[dict[str, Any]] = []
                all_errors: list[dict[str, Any]] = []

                async def scan_project(container: Container) -> None:
                    """Scan a single project's dependencies."""
                    async with semaphore:
                        # Check cancellation
                        async with AsyncSessionLocal() as check_db:
                            fresh_job = await DependencyScanService.get_job(check_db, job_id)
                            if fresh_job and fresh_job.cancel_requested:
                                return

                        project_result: dict[str, Any] = {
                            "container_id": container.id,
                            "container_name": container.name,
                            "updates_found": 0,
                        }

                        try:
                            # Update current project
                            async with lock:
                                job.current_project = container.name
                                await db.commit()

                            # Scan HTTP servers (filesystem)
                            http_updates = await _scan_http_servers(container, db)
                            project_result["http_server_updates"] = http_updates

                            # Scan Dockerfile dependencies
                            dockerfile_updates = await _scan_dockerfile_deps(container, db)
                            project_result["dockerfile_updates"] = dockerfile_updates

                            # Scan app dependencies
                            app_updates = await _scan_app_deps(container, db)
                            project_result["app_updates"] = app_updates

                            total_updates = http_updates + dockerfile_updates + app_updates
                            project_result["updates_found"] = total_updates

                            async with lock:
                                all_results.append(project_result)
                                job.scanned_count += 1
                                job.updates_found += total_updates
                                await db.commit()

                                await event_bus.publish(
                                    _build_progress_event("dependency-scan-progress", job)
                                )

                        except Exception as e:
                            logger.error(
                                "Error scanning project %s: %s",
                                container.name,
                                str(e),
                            )
                            error_info = {
                                "container_id": container.id,
                                "container_name": container.name,
                                "error": str(e),
                            }
                            async with lock:
                                all_errors.append(error_info)
                                job.scanned_count += 1
                                job.errors_count += 1
                                await db.commit()

                                await event_bus.publish(
                                    _build_progress_event("dependency-scan-progress", job)
                                )

                # Run all project scans
                tasks = [scan_project(p) for p in projects]
                await asyncio.gather(*tasks, return_exceptions=True)

                # Check if canceled
                await db.refresh(job)
                if job.cancel_requested:
                    job.status = "canceled"
                    job.completed_at = datetime.now(UTC)
                    job.results = all_results
                    job.errors = all_errors
                    await db.commit()

                    await event_bus.publish(_build_progress_event("dependency-scan-canceled", job))
                    logger.info("Dependency scan job %d canceled", job_id)
                    return

                # Mark completed
                job.status = "done"
                job.completed_at = datetime.now(UTC)
                job.current_project = None
                job.results = all_results
                job.errors = all_errors
                await db.commit()

                await event_bus.publish(_build_progress_event("dependency-scan-completed", job))
                logger.info(
                    "Dependency scan job %d completed: %d projects, %d updates found",
                    job_id,
                    job.scanned_count,
                    job.updates_found,
                )

            except Exception as e:
                logger.error("Dependency scan job %d failed: %s", job_id, str(e))
                if job:
                    job.status = "failed"
                    job.error_message = str(e)[:500]
                    job.completed_at = datetime.now(UTC)
                    await db.commit()

                    await event_bus.publish(_build_progress_event("dependency-scan-failed", job))


def _build_progress_event(event_type: str, job: DependencyScanJob) -> dict[str, Any]:
    """Build a progress event payload for SSE.

    Args:
        event_type: Event type string
        job: DependencyScanJob instance

    Returns:
        Event payload dict
    """
    return {
        "type": event_type,
        "job_id": job.id,
        "status": job.status,
        "scanned_count": job.scanned_count,
        "total_count": job.total_count,
        "current_project": job.current_project,
        "updates_found": job.updates_found,
        "errors_count": job.errors_count,
        "progress_percent": job.progress_percent,
    }


async def _scan_http_servers(container: Container, db: AsyncSession) -> int:
    """Scan a container's HTTP servers from filesystem.

    Returns:
        Number of updates found
    """
    try:
        from app.services.http_server_scanner import http_scanner

        servers = await http_scanner.scan_project_http_servers(container_model=container, db=db)
        return sum(1 for s in servers if s.get("update_available"))
    except Exception as e:
        logger.debug("HTTP server scan failed for %s: %s", container.name, str(e))
        return 0


async def _scan_dockerfile_deps(container: Container, db: AsyncSession) -> int:
    """Scan a container's Dockerfile dependencies.

    Returns:
        Number of updates found
    """
    try:
        from app.services.dockerfile_parser import DockerfileParser

        parser = DockerfileParser()
        deps = await parser.scan_container_dockerfile(session=db, container=container)
        return sum(1 for d in deps if d.update_available)
    except Exception as e:
        logger.debug("Dockerfile dep scan failed for %s: %s", container.name, str(e))
        return 0


async def _scan_app_deps(container: Container, db: AsyncSession) -> int:
    """Scan a container's application dependencies.

    Returns:
        Number of updates found
    """
    try:
        from app.services.app_dependencies import DependencyScanner

        scanner = DependencyScanner()
        deps = await scanner.scan_container_dependencies(
            compose_file=container.compose_file or "",
            service_name=container.name,
        )
        return sum(1 for d in deps if d.update_available)
    except Exception as e:
        logger.debug("App dep scan failed for %s: %s", container.name, str(e))
        return 0
