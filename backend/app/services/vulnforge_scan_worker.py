"""APScheduler worker for processing pending VulnForge scan jobs.

Replaces the fire-and-forget asyncio.create_task() pattern with a durable,
scheduler-driven workflow. Runs every 15 seconds, processes up to 3 jobs
per cycle, and handles crash recovery on startup.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.pending_scan_job import PendingScanJob
from app.services.vulnforge_cve_writer import write_cve_delta

logger = logging.getLogger(__name__)

# Maximum jobs processed per scheduler cycle
MAX_JOBS_PER_CYCLE = 3

# Minimum seconds between polls for the same job
POLL_INTERVAL_SECONDS = 15

# Trigger retry settings (pending → triggered transition)
MAX_TRIGGER_ATTEMPTS = 5

# Backoff (seconds) before each retry, indexed by attempt number.
# Attempt 0 = first try (no delay), attempt 1 = immediate retry on next cycle,
# attempt 2+ = increasing waits to give VulnForge time to discover the container.
TRIGGER_BACKOFF_SECONDS = [0, 0, 30, 60, 120]

# Trigger VulnForge container discovery starting at this attempt (0-indexed)
DISCOVERY_TRIGGER_AT_ATTEMPT = 2


async def process_pending_scan_jobs() -> None:
    """Process pending VulnForge scan jobs.

    Called by APScheduler every 15 seconds. Handles the full lifecycle:
    - pending: trigger scan in VulnForge
    - triggered/polling: poll job status
    - completed: fetch CVE delta and write to update records
    - failed: mark job as failed with error message

    Rate-limited to MAX_JOBS_PER_CYCLE per invocation.
    When VulnForge is globally disabled, active jobs are processed normally
    (they'll be marked failed by _handle_pending/_handle_polling since
    _get_vulnforge_client returns None). Skips the DB query only when
    there are no active jobs — the common idle case.
    """
    async with AsyncSessionLocal() as db:
        jobs = await _get_active_jobs(db, limit=MAX_JOBS_PER_CYCLE)
        if not jobs:
            return

        logger.debug(f"Processing {len(jobs)} pending scan job(s)")

        for job in jobs:
            try:
                await _process_single_job(db, job)
            except Exception as e:
                logger.error(
                    f"Unexpected error processing PendingScanJob {job.id}: {e}",
                    exc_info=True,
                )
                await _mark_failed(db, job, f"Unexpected error: {e}")


async def recover_interrupted_jobs() -> None:
    """Recover jobs left in triggered/polling state after a crash.

    Called once at startup. Resets these jobs to polling state so the
    worker picks them up and resumes polling VulnForge.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingScanJob).where(PendingScanJob.status.in_(["triggered", "polling"]))
        )
        interrupted = result.scalars().all()

        if not interrupted:
            return

        for job in interrupted:
            logger.info(
                f"Recovering interrupted PendingScanJob {job.id} "
                f"(container={job.container_name}, status={job.status}, "
                f"job_id={job.vulnforge_job_id})"
            )
            # If we have a job_id, resume polling; otherwise re-trigger
            if job.vulnforge_job_id:
                job.status = "polling"
            else:
                job.status = "pending"

        await db.commit()
        logger.info(f"Recovered {len(interrupted)} interrupted scan job(s)")


async def _get_active_jobs(db: AsyncSession, limit: int) -> list[PendingScanJob]:
    """Fetch active jobs ordered by creation time, oldest first."""
    result = await db.execute(
        select(PendingScanJob)
        .where(PendingScanJob.status.in_(["pending", "triggered", "polling"]))
        .order_by(PendingScanJob.created_at.asc(), PendingScanJob.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _process_single_job(db: AsyncSession, job: PendingScanJob) -> None:
    """Process a single pending scan job through its lifecycle."""
    if job.status == "pending":
        await _handle_pending(db, job)
    elif job.status in ("triggered", "polling"):
        await _handle_polling(db, job)


async def _handle_pending(db: AsyncSession, job: PendingScanJob) -> None:
    """Trigger a VulnForge scan for a pending job.

    Implements bounded retry with exponential backoff.  When VulnForge
    returns 404 for the container (not yet discovered after a
    force-recreate), the job is retried up to MAX_TRIGGER_ATTEMPTS
    times.  On attempt DISCOVERY_TRIGGER_AT_ATTEMPT and later, VulnForge
    container discovery is triggered first to speed up detection.
    """
    # --- check if trigger attempts are exhausted ---
    if job.trigger_attempt_count >= MAX_TRIGGER_ATTEMPTS:
        await _mark_failed(
            db,
            job,
            f"Trigger exhausted after {job.trigger_attempt_count} attempts "
            f"for {job.container_name} (container may not exist in VulnForge)",
        )
        return

    # --- check backoff timer ---
    if job.trigger_attempt_count > 0 and job.last_trigger_attempt_at:
        now = datetime.now(UTC)
        last = job.last_trigger_attempt_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed = (now - last).total_seconds()
        idx = min(job.trigger_attempt_count, len(TRIGGER_BACKOFF_SECONDS) - 1)
        required_backoff = TRIGGER_BACKOFF_SECONDS[idx]
        if elapsed < required_backoff:
            return  # not time yet, skip this cycle

    vulnforge = await _get_vulnforge_client(db)
    if not vulnforge:
        await _mark_failed(db, job, "VulnForge integration disabled or not configured")
        return

    try:
        # --- trigger discovery on later attempts ---
        if job.trigger_attempt_count >= DISCOVERY_TRIGGER_AT_ATTEMPT:
            logger.info(
                f"Trigger attempt {job.trigger_attempt_count + 1}/{MAX_TRIGGER_ATTEMPTS} "
                f"for {job.container_name} — requesting VulnForge container discovery"
            )
            await vulnforge.trigger_container_discovery()

        scan_response = await vulnforge.trigger_scan_by_name(job.container_name)
        if not scan_response:
            # Container not found — retry with backoff instead of hard-fail
            job.trigger_attempt_count += 1
            job.last_trigger_attempt_at = datetime.now(UTC)
            await db.commit()

            remaining = MAX_TRIGGER_ATTEMPTS - job.trigger_attempt_count
            if remaining > 0:
                logger.warning(
                    f"Trigger attempt {job.trigger_attempt_count}/{MAX_TRIGGER_ATTEMPTS} "
                    f"failed for {job.container_name} — {remaining} retries remaining"
                )
            else:
                logger.warning(
                    f"Trigger attempt {job.trigger_attempt_count}/{MAX_TRIGGER_ATTEMPTS} "
                    f"failed for {job.container_name} — no retries remaining"
                )
            return

        job_ids = scan_response.get("job_ids", [])
        if not job_ids:
            await _mark_failed(
                db,
                job,
                f"No job_ids returned (queued={scan_response.get('queued', 0)})",
            )
            return

        job.vulnforge_job_id = job_ids[0]
        job.status = "triggered"
        await db.commit()

        if job.trigger_attempt_count > 0:
            logger.info(
                f"Triggered VulnForge scan for {job.container_name} "
                f"after {job.trigger_attempt_count} retries, "
                f"vulnforge_job_id={job.vulnforge_job_id}"
            )
        else:
            logger.info(
                f"Triggered VulnForge scan for {job.container_name}, "
                f"vulnforge_job_id={job.vulnforge_job_id}"
            )
    finally:
        await vulnforge.close()


async def _handle_polling(db: AsyncSession, job: PendingScanJob) -> None:
    """Poll VulnForge for scan job completion."""
    if not job.vulnforge_job_id:
        # Should not happen, but handle gracefully
        job.status = "pending"
        await db.commit()
        return

    # Respect poll interval — skip if polled too recently
    now = datetime.now(UTC)
    if job.last_polled_at:
        last_polled = job.last_polled_at
        if last_polled.tzinfo is None:
            last_polled = last_polled.replace(tzinfo=UTC)
        elapsed = (now - last_polled).total_seconds()
        if elapsed < POLL_INTERVAL_SECONDS:
            return

    # Check if polls exhausted
    if job.polls_exhausted:
        await _mark_failed(
            db,
            job,
            f"Polling exhausted after {job.max_polls} attempts "
            f"(vulnforge_job_id={job.vulnforge_job_id})",
        )
        return

    vulnforge = await _get_vulnforge_client(db)
    if not vulnforge:
        await _mark_failed(db, job, "VulnForge integration disabled during polling")
        return

    try:
        job_status = await vulnforge.get_scan_job_status(job.vulnforge_job_id)

        job.poll_count += 1
        job.last_polled_at = now
        job.status = "polling"

        if not job_status:
            logger.warning(
                f"PendingScanJob {job.id}: poll {job.poll_count}/{job.max_polls} "
                f"returned None for vulnforge_job_id={job.vulnforge_job_id}"
            )
            await db.commit()
            return

        status = job_status.get("status")

        if status == "completed":
            scan_id = job_status.get("scan_id")
            job.vulnforge_scan_id = scan_id
            logger.info(f"VulnForge job {job.vulnforge_job_id} completed, scan_id={scan_id}")
            # Reuse existing client instead of creating a second one
            await _fetch_and_write_cve_delta(db, job, vulnforge)

        elif status == "failed":
            error_msg = job_status.get("error_message", "unknown")
            await _mark_failed(
                db,
                job,
                f"VulnForge scan failed: {error_msg}",
            )

        else:
            # Still queued/processing — save poll count and continue
            await db.commit()
            logger.debug(
                f"PendingScanJob {job.id}: poll {job.poll_count}/{job.max_polls}, status={status}"
            )
    finally:
        await vulnforge.close()


async def _fetch_and_write_cve_delta(
    db: AsyncSession, job: PendingScanJob, client: Any = None
) -> None:
    """Fetch CVE delta from VulnForge and write to update records.

    Args:
        db: Database session
        job: The pending scan job
        client: Optional pre-existing VulnForge client (avoids duplicate creation)
    """
    owns_client = client is None
    if owns_client:
        client = await _get_vulnforge_client(db)
        if not client:
            await _mark_failed(db, job, "VulnForge disabled during CVE delta fetch")
            return

    try:
        delta = await client.get_cve_delta(
            container_name=job.container_name,
            scan_id=job.vulnforge_scan_id,
        )

        if not delta or not delta.get("scans"):
            logger.info(
                f"No CVE delta data for {job.container_name} scan_id={job.vulnforge_scan_id}"
            )
            await _mark_completed(db, job)
            return

        latest_scan = delta["scans"][0]
        cves_fixed = latest_scan.get("cves_fixed", [])
        cves_introduced = latest_scan.get("cves_introduced", [])
        total_vulns = latest_scan.get("total_vulns", 0)

        await write_cve_delta(
            db=db,
            update_id=job.update_id,
            container_name=job.container_name,
            cves_fixed=cves_fixed,
            cves_introduced=cves_introduced,
            total_vulns=total_vulns,
            scan_id=job.vulnforge_scan_id,
        )
        await _mark_completed(db, job)
    finally:
        if owns_client:
            await client.close()


async def _mark_completed(db: AsyncSession, job: PendingScanJob) -> None:
    """Mark a job as completed."""
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        f"PendingScanJob {job.id} completed for {job.container_name} "
        f"(scan_id={job.vulnforge_scan_id})"
    )


async def _mark_failed(db: AsyncSession, job: PendingScanJob, error_message: str) -> None:
    """Mark a job as failed with an error message."""
    job.status = "failed"
    job.error_message = error_message[:500] if error_message else None
    job.completed_at = datetime.now(UTC)
    await db.commit()
    logger.warning(f"PendingScanJob {job.id} failed: {error_message}")


async def _get_vulnforge_client(db: AsyncSession):
    """Get a VulnForge client from settings."""
    from app.services.vulnforge_client import create_vulnforge_client

    return await create_vulnforge_client(db)
