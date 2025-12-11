"""Updates API endpoints."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, IntegrityError

logger = logging.getLogger(__name__)

from app.db import get_db
from app.services.auth import require_auth
from app.models.update import Update
from app.models.container import Container
from app.schemas.update import UpdateSchema, UpdateApproval, UpdateApply
from app.services.update_checker import UpdateChecker
from app.services.update_engine import UpdateEngine
from app.services.scheduler import scheduler_service
from app.utils.error_handling import safe_error_response

router = APIRouter()


@router.get("/", response_model=List[UpdateSchema])
async def list_updates(
    admin: Optional[dict] = Depends(require_auth),
    status: str = None,
    container_id: Optional[int] = Query(None, description="Filter by container ID"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
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
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get all pending updates."""
    updates = await UpdateChecker.get_pending_updates(db)
    return updates


@router.get("/auto-approvable", response_model=List[UpdateSchema])
async def get_auto_approvable_updates(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get updates that can be auto-approved."""
    updates = await UpdateChecker.get_auto_approvable_updates(db)
    return updates


@router.get("/security", response_model=List[UpdateSchema])
async def get_security_updates(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> List[UpdateSchema]:
    """Get security-related updates."""
    updates = await UpdateChecker.get_security_updates(db)
    return updates


@router.post("/check")
async def check_updates(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Check all containers for updates.

    Returns:
        Stats about the check
    """
    stats = await UpdateChecker.check_all_containers(db)
    return {
        "success": True,
        "stats": stats,
        "message": f"Checked {stats['checked']} containers, found {stats['updates_found']} updates"
    }


@router.post("/check/{container_id}")
async def check_container_update(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Check a specific container for updates.

    Args:
        container_id: Container ID

    Returns:
        Update info if available
    """
    result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
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
            "update": UpdateSchema.model_validate(update)
        }
    else:
        return {
            "success": True,
            "update_available": False,
            "message": "No updates available"
        }


@router.post("/batch/approve")
async def batch_approve_updates(
    update_ids: List[int] = Body(..., embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
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
                    approved.append({"id": update_id, "container_id": update.container_id})
                    continue

                # Only allow pending -> approved transition
                if update.status != "pending":
                    failed.append({"id": update_id, "reason": f"Invalid status transition: {update.status} -> approved"})
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
            logger.warning(f"Database conflict approving update {update_id}: {e}")
            failed.append({"id": update_id, "reason": "Database conflict - concurrent modification detected"})
        except Exception as e:
            logger.error(f"Error approving update {update_id}: {e}")
            failed.append({"id": update_id, "reason": str(e)})

    return {
        "approved": approved,
        "failed": failed,
        "summary": {
            "total": len(update_ids),
            "approved_count": len(approved),
            "failed_count": len(failed)
        }
    }


@router.post("/batch/reject")
async def batch_reject_updates(
    update_ids: List[int] = Body(..., embed=True),
    reason: Optional[str] = Body(None, embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
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
                    rejected.append({"id": update_id, "container_id": update.container_id})
                    continue

                # Only allow pending/approved -> rejected transition
                if update.status not in ["pending", "approved"]:
                    failed.append({"id": update_id, "reason": f"Invalid status transition: {update.status} -> rejected"})
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
            logger.warning(f"Database conflict rejecting update {update_id}: {e}")
            failed.append({"id": update_id, "reason": "Database conflict - concurrent modification detected"})
        except Exception as e:
            logger.error(f"Error rejecting update {update_id}: {e}")
            failed.append({"id": update_id, "reason": str(e)})

    return {
        "rejected": rejected,
        "failed": failed,
        "summary": {
            "total": len(update_ids),
            "rejected_count": len(rejected),
            "failed_count": len(failed)
        }
    }


@router.get("/{update_id}", response_model=UpdateSchema)
async def get_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> UpdateSchema:
    """Get update details.

    Args:
        update_id: Update ID

    Returns:
        Update details
    """
    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    return update


@router.post("/{update_id}/approve")
async def approve_update(
    update_id: int,
    approval: UpdateApproval,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
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
        result = await db.execute(
            select(Update).where(Update.id == update_id)
        )
        update = result.scalar_one_or_none()

        if not update:
            raise HTTPException(status_code=404, detail="Update not found")

        # Idempotency check - already approved is OK
        if update.status == "approved":
            return {
                "success": True,
                "message": f"Update already approved for container {update.container_id}"
            }

        # Only allow pending -> approved transition
        if update.status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve update with status: {update.status}"
            )

        update.status = "approved"
        update.approved_by = approval.approved_by or "user"
        update.approved_at = datetime.now(timezone.utc)
        update.version += 1  # Increment version for optimistic locking

    await db.commit()

    return {
        "success": True,
        "message": f"Update approved for container {update.container_id}"
    }


@router.post("/{update_id}/apply")
async def apply_update(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    request: UpdateApply = UpdateApply(),
    db: AsyncSession = Depends(get_db)
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
        result = await UpdateEngine.apply_update(db, update_id, triggered_by=request.triggered_by)

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Update failed")
            )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid request")
    except OperationalError as e:
        logger.error(f"Database error applying update: {e}")
        raise HTTPException(status_code=500, detail="Database error during update")
    except (KeyError, AttributeError) as e:
        logger.error(f"Invalid data applying update: {e}")
        raise HTTPException(status_code=500, detail="Invalid update data")


@router.post("/{update_id}/reject")
async def reject_update(
    update_id: int,
    reason: Optional[str] = Body(None, embed=True),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Reject an update.

    Args:
        update_id: Update ID
        reason: Optional rejection reason

    Returns:
        Success message
    """
    from datetime import datetime, timezone

    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.status not in ["pending", "pending_retry"]:
        raise HTTPException(
            status_code=400,
            detail=f"Update is already {update.status}"
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
        "message": f"Update rejected for container {update.container_id}"
    }


@router.post("/{update_id}/cancel-retry")
async def cancel_retry(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> UpdateSchema:
    """Cancel a pending retry and reset update to pending status.

    Args:
        update_id: Update ID

    Returns:
        Updated update object
    """
    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.status != "pending_retry":
        raise HTTPException(
            status_code=400,
            detail=f"Update is not in pending_retry status (current: {update.status})"
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
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Delete an update record.

    Args:
        update_id: Update ID

    Returns:
        Success message
    """
    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
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
    db: AsyncSession = Depends(get_db)
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

    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
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
        "snoozed_until": snooze_until.isoformat()
    }


@router.post("/{update_id}/remove-container")
async def remove_container_from_db(
    update_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
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

    result = await db.execute(
        select(Update).where(Update.id == update_id)
    )
    update = result.scalar_one_or_none()

    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.reason_type != "stale":
        raise HTTPException(
            status_code=400,
            detail="Only stale container notifications can use remove-container action"
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
                UpdateHistory.__table__.delete().where(UpdateHistory.container_id == container.id)
            )

            # 2. Delete restart state and logs
            await db.execute(
                ContainerRestartState.__table__.delete().where(ContainerRestartState.container_id == container.id)
            )
            await db.execute(
                ContainerRestartLog.__table__.delete().where(ContainerRestartLog.container_id == container.id)
            )

            # 3. Delete all updates for this container
            await db.execute(
                Update.__table__.delete().where(Update.container_id == container.id)
            )

            # 4. Delete the container itself
            await db.delete(container)

        await db.commit()

        logger.info(f"Removed stale container from database: {container_name}")

        return {
            "success": True,
            "message": f"Container '{container_name}' removed from database"
        }
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violation removing container: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database constraint error during container removal"
        )
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database error removing container: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error during container removal"
        )
    except (KeyError, AttributeError) as e:
        await db.rollback()
        logger.error(f"Invalid data removing container: {e}")
        raise HTTPException(
            status_code=500,
            detail="Invalid container data"
        )


@router.get("/scheduler/status")
async def get_scheduler_status(
    admin: Optional[dict] = Depends(require_auth)
) -> Dict[str, Any]:
    """Get background scheduler status.

    Returns:
        Scheduler status and next run time
    """
    status = scheduler_service.get_status()
    return {
        "success": True,
        "scheduler": status
    }


@router.post("/scheduler/trigger")
async def trigger_scheduler(
    admin: Optional[dict] = Depends(require_auth)
) -> Dict[str, Any]:
    """Manually trigger an update check outside the schedule.

    Returns:
        Success message
    """
    try:
        await scheduler_service.trigger_update_check()
        return {
            "success": True,
            "message": "Update check triggered successfully"
        }
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Scheduler service error: {e}")
        raise HTTPException(status_code=500, detail="Scheduler service not available")
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data triggering update check: {e}")
        raise HTTPException(status_code=500, detail="Invalid scheduler configuration")


@router.post("/scheduler/reload")
async def reload_scheduler(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
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
            "scheduler": status
        }
    except OperationalError as e:
        logger.error(f"Database error reloading scheduler: {e}")
        raise HTTPException(status_code=500, detail="Database error reloading configuration")
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Scheduler service error: {e}")
        raise HTTPException(status_code=500, detail="Scheduler service not available")
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data reloading scheduler: {e}")
        raise HTTPException(status_code=500, detail="Invalid scheduler configuration")
