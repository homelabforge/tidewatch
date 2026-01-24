"""Updates API endpoints."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, IntegrityError

from app.db import get_db
from app.services.auth import require_auth
from app.models.update import Update
from app.models.container import Container
from app.schemas.update import UpdateSchema, UpdateApproval, UpdateApply
from app.schemas.check_job import (
    CheckJobResult,
    CheckJobSummary,
    CheckJobStartResponse,
    CheckJobCancelResponse,
)
from app.services.update_checker import UpdateChecker
from app.services.update_engine import UpdateEngine
from app.services.scheduler import scheduler_service
from app.services.check_job_service import CheckJobService
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[UpdateSchema])
async def list_updates(
    admin: Optional[dict] = Depends(require_auth),
    status: str = None,
    container_id: Optional[int] = Query(None, description="Filter by container ID"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of records to return"
    ),
    db: AsyncSession = Depends(get_db),
) -> List[UpdateSchema]:
    """List updates by status with pagination.

    Args:
        status: Filter by status (pending, approved, rejected, applied). If None, returns all updates.
        container_id: Filter by container ID. If None, returns updates for all containers.
        skip: Number of records to skip (default: 0)
        limit: Maximum number of records to return (default: 100, max: 1000)

    Returns:
        List of updates (excludes snoozed updates)
    """
    from datetime import datetime, timezone

    query = select(Update).order_by(Update.created_at.desc())
    if status:
        query = query.where(Update.status == status)
    if container_id is not None:
        query = query.where(Update.container_id == container_id)

    # Filter out snoozed updates
    now = datetime.now(timezone.utc)
    query = query.where(
        (Update.snoozed_until.is_(None)) | (Update.snoozed_until <= now)
    )

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    updates = result.scalars().all()
    return updates


@router.get("/pending", response_model=List[UpdateSchema])
async def get_pending_updates(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get all pending updates."""
    updates = await UpdateChecker.get_pending_updates(db)
    return updates


@router.get("/auto-approvable", response_model=List[UpdateSchema])
async def get_auto_approvable_updates(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get updates that can be auto-approved."""
    updates = await UpdateChecker.get_auto_approvable_updates(db)
    return updates


@router.get("/security", response_model=List[UpdateSchema])
async def get_security_updates(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get security-related updates."""
    updates = await UpdateChecker.get_security_updates(db)
    return updates


@router.post("/check", response_model=CheckJobStartResponse)
async def check_updates(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> CheckJobStartResponse:
    """Start a background check for all containers.

    Returns immediately with a job ID. Use GET /updates/check/{job_id}
    to poll for progress, or subscribe to SSE for real-time updates.

    Returns:
        Job information including ID for tracking
    """
    # Check for existing running/queued job
    existing = await CheckJobService.get_active_job(db)
    if existing:
        return CheckJobStartResponse(
            success=True,
            job_id=existing.id,
            status=existing.status,
            message=f"Check already in progress (job {existing.id})",
            already_running=True,
        )

    # Create new check job
    job = await CheckJobService.create_job(db, triggered_by="user")

    # Start background task
    CheckJobService.start_job_background(job.id)

    return CheckJobStartResponse(
        success=True,
        job_id=job.id,
        status="queued",
        message="Update check started",
        already_running=False,
    )


@router.get("/check/history", response_model=List[CheckJobSummary])
async def get_check_history(
    admin: Optional[dict] = Depends(require_auth),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of jobs to return"
    ),
    db: AsyncSession = Depends(get_db),
) -> List[CheckJobSummary]:
    """Get history of update check jobs.

    Args:
        limit: Maximum number of jobs to return (default: 20)

    Returns:
        List of recent check jobs with summary info
    """
    jobs = await CheckJobService.get_recent_jobs(db, limit=limit)
    return [
        CheckJobSummary(
            id=job.id,
            status=job.status,
            total_count=job.total_count,
            checked_count=job.checked_count,
            updates_found=job.updates_found,
            errors_count=job.errors_count,
            triggered_by=job.triggered_by,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=job.duration_seconds,
        )
        for job in jobs
    ]


@router.get("/check/{job_id}", response_model=CheckJobResult)
async def get_check_job(
    job_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> CheckJobResult:
    """Get status and progress of an update check job.

    Args:
        job_id: Check job ID

    Returns:
        Job status, progress, and results
    """
    job = await CheckJobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Only include detailed results when job is complete
    include_results = job.status in ("done", "failed", "canceled")

    return CheckJobResult(
        id=job.id,
        status=job.status,
        total_count=job.total_count,
        checked_count=job.checked_count,
        updates_found=job.updates_found,
        errors_count=job.errors_count,
        progress_percent=job.progress_percent,
        current_container=job.current_container_name,
        triggered_by=job.triggered_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_seconds=job.duration_seconds,
        error_message=job.error_message,
        results=job.results if include_results else None,
        errors=job.errors if include_results else None,
    )


@router.post("/check/{job_id}/cancel", response_model=CheckJobCancelResponse)
async def cancel_check_job(
    job_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> CheckJobCancelResponse:
    """Request cancellation of a running check job.

    The job will stop after completing the current container check.

    Args:
        job_id: Check job ID

    Returns:
        Confirmation message
    """
    job = await CheckJobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job.status}",
        )

    await CheckJobService.request_cancellation(db, job_id)

    return CheckJobCancelResponse(
        success=True,
        message="Cancellation requested. Job will stop after current container.",
    )


@router.post("/check/{container_id}")
async def check_container_update(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Check a specific container for updates.

    Args:
        container_id: Container ID

    Returns:
        Update info if available
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    update = await UpdateChecker.check_container(db, container)
    await db.commit()

    if update:
        # Refresh to ensure all attributes are loaded after commit
        await db.refresh(update)
        return {
            "success": True,
            "update_available": True,
            "update": UpdateSchema.model_validate(update),
        }
    else:
        return {
            "success": True,
            "update_available": False,
            "message": "No updates available",
        }


@router.post("/batch/approve")
async def batch_approve_updates(
    update_ids: List[int] = Body(..., embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Batch approve multiple updates.

    Args:
        update_ids: List of update IDs to approve

    Returns:
        Summary of approved updates with success/failure counts
    """
    approved = []
    failed = []

    for update_id in update_ids:
        try:
            # Use nested transaction for atomicity and concurrent safety
            async with db.begin_nested():
                # Get the update
                result = await db.execute(select(Update).where(Update.id == update_id))
                update = result.scalar_one_or_none()

                if not update:
                    failed.append({"id": update_id, "reason": "Update not found"})
                    continue

                # Idempotency check - already approved is OK
                if update.status == "approved":
                    approved.append(
                        {"id": update_id, "container_id": update.container_id}
                    )
                    continue

                # Only allow pending -> approved transition
                if update.status != "pending":
                    failed.append(
                        {
                            "id": update_id,
                            "reason": f"Invalid status transition: {update.status} -> approved",
                        }
                    )
                    continue

                # Approve the update with version increment
                update.status = "approved"
                update.approved_at = datetime.now(timezone.utc)
                update.version += 1  # Increment version for optimistic locking

            # Commit the nested transaction
            await db.commit()
            await db.refresh(update)

            approved.append({"id": update_id, "container_id": update.container_id})

        except OperationalError as e:
            # Database lock/conflict - likely concurrent modification
            logger.warning(
                f"Database conflict approving update {sanitize_log_message(str(update_id))}: {sanitize_log_message(str(e))}"
            )
            failed.append(
                {
                    "id": update_id,
                    "reason": "Database conflict - concurrent modification detected",
                }
            )
        except Exception as e:
            logger.error(
                f"Error approving update {sanitize_log_message(str(update_id))}: {sanitize_log_message(str(e))}"
            )
            failed.append(
                {"id": update_id, "reason": "An error occurred processing the update"}
            )

    return {
        "approved": approved,
        "failed": failed,
        "summary": {
            "total": len(update_ids),
            "approved_count": len(approved),
            "failed_count": len(failed),
        },
    }


@router.post("/batch/reject")
async def batch_reject_updates(
    update_ids: List[int] = Body(..., embed=True),
    reason: Optional[str] = Body(None, embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Batch reject multiple updates.

    Args:
        update_ids: List of update IDs to reject
        reason: Optional rejection reason

    Returns:
        Summary of rejected updates with success/failure counts
    """
    rejected = []
    failed = []

    for update_id in update_ids:
        try:
            # Use nested transaction for atomicity and concurrent safety
            async with db.begin_nested():
                # Get the update
                result = await db.execute(select(Update).where(Update.id == update_id))
                update = result.scalar_one_or_none()

                if not update:
                    failed.append({"id": update_id, "reason": "Update not found"})
                    continue

                # Idempotency check - already rejected is OK
                if update.status == "rejected":
                    rejected.append(
                        {"id": update_id, "container_id": update.container_id}
                    )
                    continue

                # Only allow pending/approved -> rejected transition
                if update.status not in ["pending", "approved"]:
                    failed.append(
                        {
                            "id": update_id,
                            "reason": f"Invalid status transition: {update.status} -> rejected",
                        }
                    )
                    continue

                # Reject the update with version increment
                update.status = "rejected"
                update.rejected_at = datetime.now(timezone.utc)
                if reason and hasattr(update, "rejection_reason"):
                    update.rejection_reason = reason
                update.version += 1  # Increment version for optimistic locking

            # Commit the nested transaction
            await db.commit()
            await db.refresh(update)

            rejected.append({"id": update_id, "container_id": update.container_id})

        except OperationalError as e:
            # Database lock/conflict - likely concurrent modification
            logger.warning(
                f"Database conflict rejecting update {sanitize_log_message(str(update_id))}: {sanitize_log_message(str(e))}"
            )
            failed.append(
                {
                    "id": update_id,
                    "reason": "Database conflict - concurrent modification detected",
                }
            )
        except Exception as e:
            logger.error(
                f"Error rejecting update {sanitize_log_message(str(update_id))}: {sanitize_log_message(str(e))}"
            )
            failed.append(
                {"id": update_id, "reason": "An error occurred processing the update"}
            )

    return {
        "rejected": rejected,
        "failed": failed,
        "summary": {
            "total": len(update_ids),
            "rejected_count": len(rejected),
            "failed_count": len(failed),
        },
    }


@router.get("/{update_id}", response_model=UpdateSchema)
async def get_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> UpdateSchema:
    """Get update details.

    Args:
        update_id: Update ID

    Returns:
        Update details
    """
    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    return update


@router.post("/{update_id}/approve")
async def approve_update(
    update_id: int,
    approval: UpdateApproval,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Approve an update.

    Args:
        update_id: Update ID
        approval: Approval details

    Returns:
        Success message
    """
    # Use nested transaction for atomicity and concurrent safety
    async with db.begin_nested():
        result = await db.execute(select(Update).where(Update.id == update_id))
        update = result.scalar_one_or_none()

        if not update:
            raise HTTPException(status_code=404, detail="Update not found")

        # Idempotency check - already approved is OK
        if update.status == "approved":
            return {
                "success": True,
                "message": f"Update already approved for container {update.container_id}",
            }

        # Only allow pending -> approved transition
        if update.status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve update with status: {update.status}",
            )

        update.status = "approved"
        update.approved_by = approval.approved_by or "user"
        update.approved_at = datetime.now(timezone.utc)
        update.version += 1  # Increment version for optimistic locking

    await db.commit()

    return {
        "success": True,
        "message": f"Update approved for container {update.container_id}",
    }


@router.post("/{update_id}/apply")
async def apply_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    request: UpdateApply = UpdateApply(),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Apply an approved update.

    This will:
    1. Update the compose file
    2. Execute docker compose up -d
    3. Create history record
    4. Update container status
    5. Validate health check (if configured)

    Args:
        update_id: Update ID
        request: Update apply request (includes triggered_by)

    Returns:
        Result of the update operation
    """
    try:
        result = await UpdateEngine.apply_update(
            db, update_id, triggered_by=request.triggered_by
        )

        if not result["success"]:
            raise HTTPException(
                status_code=500, detail=result.get("message", "Update failed")
            )

        return result

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request")
    except OperationalError as e:
        logger.error(f"Database error applying update: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Database error during update")
    except (KeyError, AttributeError) as e:
        logger.error(f"Invalid data applying update: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Invalid update data")


@router.post("/{update_id}/reject")
async def reject_update(
    update_id: int,
    reason: Optional[str] = Body(None, embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Reject an update.

    Args:
        update_id: Update ID
        reason: Optional rejection reason

    Returns:
        Success message
    """
    from datetime import datetime, timezone

    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.status not in ["pending", "pending_retry"]:
        raise HTTPException(
            status_code=400, detail=f"Update is already {update.status}"
        )

    # Wrap status updates in transaction for atomicity
    async with db.begin_nested():
        update.status = "rejected"
        update.rejected_at = datetime.now(timezone.utc)
        update.rejected_by = admin.get("email") if admin else "system"
        update.rejection_reason = reason
        update.version += 1  # Increment version for optimistic locking

        # Clear update_available flag on container
        result = await db.execute(
            select(Container).where(Container.id == update.container_id)
        )
        container = result.scalar_one_or_none()
        if container:
            container.update_available = False
            container.latest_tag = None

    await db.commit()

    return {
        "success": True,
        "message": f"Update rejected for container {update.container_id}",
    }


@router.post("/{update_id}/cancel-retry")
async def cancel_retry(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> UpdateSchema:
    """Cancel a pending retry and reset update to pending status.

    Args:
        update_id: Update ID

    Returns:
        Updated update object
    """
    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.status != "pending_retry":
        raise HTTPException(
            status_code=400,
            detail=f"Update is not in pending_retry status (current: {update.status})",
        )

    # Reset retry state
    update.status = "pending"
    update.retry_count = 0
    update.next_retry_at = None
    update.last_error = None

    await db.commit()
    await db.refresh(update)

    return update


@router.delete("/{update_id}")
async def delete_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Delete an update record.

    Args:
        update_id: Update ID

    Returns:
        Success message
    """
    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    await db.delete(update)
    await db.commit()

    return {"success": True, "message": "Update deleted"}


@router.post("/{update_id}/snooze")
async def snooze_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Snooze/dismiss a stale container notification.

    Sets snoozed_until to current time + threshold days, preventing the
    notification from showing up again until the snooze expires.

    Args:
        update_id: Update ID

    Returns:
        Success message with snooze details
    """
    from datetime import datetime, timedelta, timezone
    from app.services.settings_service import SettingsService

    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    # Get threshold from settings
    threshold_days = await SettingsService.get_int(
        db, "stale_detection_threshold_days", default=30
    )

    # Set snooze expiration
    now = datetime.now(timezone.utc)
    snooze_until = now + timedelta(days=threshold_days)
    update.snoozed_until = snooze_until

    await db.commit()

    return {
        "success": True,
        "message": f"Update snoozed for {threshold_days} days",
        "snoozed_until": snooze_until.isoformat(),
    }


@router.post("/{update_id}/remove-container")
async def remove_container_from_db(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Remove a stale container from the database entirely.

    This deletes both the update notification and the container record.
    Use this for containers that are truly obsolete and will never return.

    Args:
        update_id: Update ID (must be a stale-type update)

    Returns:
        Success message
    """
    from app.models.history import UpdateHistory
    from app.models.restart_state import ContainerRestartState
    from app.models.restart_log import ContainerRestartLog

    result = await db.execute(select(Update).where(Update.id == update_id))
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.reason_type != "stale":
        raise HTTPException(
            status_code=400,
            detail="Only stale container notifications can use remove-container action",
        )

    # Get container
    result = await db.execute(
        select(Container).where(Container.id == update.container_id)
    )
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    container_name = container.name

    # Use transaction to ensure all-or-nothing deletion
    try:
        async with db.begin_nested():
            # Delete related records
            # 1. Delete update history
            await db.execute(
                select(UpdateHistory).where(UpdateHistory.container_id == container.id)
            )
            await db.execute(
                UpdateHistory.__table__.delete().where(
                    UpdateHistory.container_id == container.id
                )
            )

            # 2. Delete restart state and logs
            await db.execute(
                ContainerRestartState.__table__.delete().where(
                    ContainerRestartState.container_id == container.id
                )
            )
            await db.execute(
                ContainerRestartLog.__table__.delete().where(
                    ContainerRestartLog.container_id == container.id
                )
            )

            # 3. Delete all updates for this container
            await db.execute(
                Update.__table__.delete().where(Update.container_id == container.id)
            )

            # 4. Delete the container itself
            await db.delete(container)

        await db.commit()

        logger.info(
            f"Removed stale container from database: {sanitize_log_message(str(container_name))}"
        )

        return {
            "success": True,
            "message": f"Container '{container_name}' removed from database",
        }
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            f"Database constraint violation removing container: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Database constraint error during container removal"
        )
    except OperationalError as e:
        await db.rollback()
        logger.error(
            f"Database error removing container: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Database error during container removal"
        )
    except (KeyError, AttributeError) as e:
        await db.rollback()
        logger.error(f"Invalid data removing container: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Invalid container data")


@router.get("/scheduler/status")
async def get_scheduler_status(
    admin: Optional[dict] = Depends(require_auth),
) -> Dict[str, Any]:
    """Get background scheduler status.

    Returns:
        Scheduler status and next run time
    """
    status = scheduler_service.get_status()
    return {"success": True, "scheduler": status}


@router.post("/scheduler/trigger")
async def trigger_scheduler(
    admin: Optional[dict] = Depends(require_auth),
) -> Dict[str, Any]:
    """Manually trigger an update check outside the schedule.

    Returns:
        Success message
    """
    try:
        await scheduler_service.trigger_update_check()
        return {"success": True, "message": "Update check triggered successfully"}
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Scheduler service error: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Scheduler service not available")
    except (ValueError, KeyError) as e:
        logger.error(
            f"Invalid data triggering update check: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Invalid scheduler configuration")


@router.post("/scheduler/reload")
async def reload_scheduler(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Reload scheduler configuration from settings.

    This allows updating the schedule without restarting the container.

    Returns:
        Success message with new schedule
    """
    try:
        await scheduler_service.reload_schedule(db)
        status = scheduler_service.get_status()
        return {
            "success": True,
            "message": "Scheduler reloaded successfully",
            "scheduler": status,
        }
    except OperationalError as e:
        logger.error(
            f"Database error reloading scheduler: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Database error reloading configuration"
        )
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Scheduler service error: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Scheduler service not available")
    except (ValueError, KeyError) as e:
        logger.error(
            f"Invalid data reloading scheduler: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Invalid scheduler configuration")
