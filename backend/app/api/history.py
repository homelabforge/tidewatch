"""History API endpoints."""

import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.orm import undefer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from app.db import get_db
from app.services.auth import require_auth
from app.models.history import UpdateHistory
from app.models.restart_log import ContainerRestartLog
from app.schemas.history import UpdateHistorySchema, UnifiedHistoryEventSchema
from app.services.update_engine import UpdateEngine
from app.utils.error_handling import safe_error_response

logger = logging.getLogger(__name__)

router = APIRouter()


def transform_update_to_event(update: UpdateHistory) -> UnifiedHistoryEventSchema:
    """Transform UpdateHistory model to unified event schema."""
    return UnifiedHistoryEventSchema(
        id=update.id,
        event_type=update.event_type or "update",  # Use actual event_type from database
        container_id=update.container_id,
        container_name=update.container_name,
        status=update.status,
        started_at=update.started_at,
        completed_at=update.completed_at,
        duration_seconds=update.duration_seconds,
        error_message=update.error_message,
        performed_by=update.triggered_by or "System",
        # Update-specific fields
        from_tag=update.from_tag,
        to_tag=update.to_tag,
        update_type=update.update_type,
        reason=update.reason,
        reason_type=update.reason_type,
        reason_summary=update.reason_summary,
        can_rollback=update.can_rollback,
        rollback_available=update.can_rollback,
        backup_path=update.backup_path,
        cves_fixed=update.cves_fixed or [],
        rolled_back_at=update.rolled_back_at,
        # Dependency-specific fields
        dependency_type=update.dependency_type,
        dependency_id=update.dependency_id,
        dependency_name=update.dependency_name,
    )


def get_restart_status(restart: ContainerRestartLog) -> str:
    """Map restart log data to user-friendly status."""
    if not restart.success:
        return "failed_to_restart"

    # Check final container status
    if restart.final_container_status == "exited":
        return "crashed"
    elif restart.final_container_status == "running":
        return "restarted"
    else:
        # Default to restarted if status unclear
        return "restarted"


def get_restart_performed_by(restart: ContainerRestartLog) -> str:
    """Extract who/what triggered the restart."""
    trigger = restart.trigger_reason or ""

    if trigger.startswith("manual"):
        return "User"
    elif trigger in ["exit_code", "health_check", "oom_killed", "signal_killed_SIGKILL", "signal_killed_SIGTERM"]:
        return "Auto-Restart"
    else:
        return "System"


def transform_restart_to_event(restart: ContainerRestartLog) -> UnifiedHistoryEventSchema:
    """Transform ContainerRestartLog model to unified event schema."""
    # Calculate duration if completed
    duration = None
    if restart.completed_at and restart.executed_at:
        duration = int((restart.completed_at - restart.executed_at).total_seconds())

    return UnifiedHistoryEventSchema(
        id=restart.id,
        event_type="restart",
        container_id=restart.container_id,
        container_name=restart.container_name,
        status=get_restart_status(restart),
        started_at=restart.executed_at,  # Use executed_at as started_at for restarts
        completed_at=restart.completed_at,
        duration_seconds=duration,
        error_message=restart.error_message,
        performed_by=get_restart_performed_by(restart),
        # Restart-specific fields
        attempt_number=restart.attempt_number,
        trigger_reason=restart.trigger_reason,
        exit_code=restart.exit_code,
        health_check_passed=restart.health_check_passed,
        final_container_status=restart.final_container_status,
    )


@router.get("/", response_model=List[UnifiedHistoryEventSchema])
async def list_history(
    admin: Optional[dict] = Depends(require_auth),
    container_id: int = None,
    status: Optional[str] = Query(None, description="Filter by status (success, failed, rolled_back)"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
) -> List[UnifiedHistoryEventSchema]:
    """List unified history (updates + restarts) with pagination.

    Args:
        container_id: Optional filter by container
        status: Optional filter by status
        start_date: Optional filter by start date
        end_date: Optional filter by end date
        skip: Number of records to skip (default: 0)
        limit: Maximum number of records to return (default: 50, max: 500)

    Returns:
        List of unified history events (updates and restarts)
    """
    from datetime import datetime

    # Fetch more from each table to ensure we have enough after merging
    fetch_limit = min(limit * 3, 500)

    # Query updates - undefer event_type to load it eagerly
    update_query = select(UpdateHistory).options(
        undefer(UpdateHistory.event_type),
        undefer(UpdateHistory.dependency_type),
        undefer(UpdateHistory.dependency_id),
        undefer(UpdateHistory.dependency_name),
    ).order_by(UpdateHistory.created_at.desc())
    if container_id:
        update_query = update_query.where(UpdateHistory.container_id == container_id)
    if status:
        update_query = update_query.where(UpdateHistory.status == status)
    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        update_query = update_query.where(UpdateHistory.started_at >= start_dt)
    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        update_query = update_query.where(UpdateHistory.started_at <= end_dt)
    update_query = update_query.limit(fetch_limit)

    # Query restarts (only completed ones)
    restart_query = select(ContainerRestartLog).where(
        ContainerRestartLog.completed_at.isnot(None)
    ).order_by(ContainerRestartLog.created_at.desc())
    if container_id:
        restart_query = restart_query.where(ContainerRestartLog.container_id == container_id)
    restart_query = restart_query.limit(fetch_limit)

    # Execute queries
    update_result = await db.execute(update_query)
    restart_result = await db.execute(restart_query)

    updates = update_result.scalars().all()
    restarts = restart_result.scalars().all()

    # Transform to unified events
    unified_events: List[UnifiedHistoryEventSchema] = []

    for update in updates:
        unified_events.append(transform_update_to_event(update))

    for restart in restarts:
        unified_events.append(transform_restart_to_event(restart))

    # Sort by started_at descending
    unified_events.sort(key=lambda e: e.started_at, reverse=True)

    # Apply pagination
    return unified_events[skip:skip + limit]


@router.get("/stats")
async def get_history_stats(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Get update history statistics.

    Returns:
        Dictionary with statistics including:
        - success_rate: Percentage of successful updates
        - total_updates: Total number of updates
        - avg_update_time: Average update duration in seconds
        - failed_count: Number of failed updates
        - most_updated_containers: List of most frequently updated containers
    """
    from sqlalchemy import func

    # Get total updates count
    total_result = await db.execute(
        select(func.count(UpdateHistory.id))
    )
    total_updates = total_result.scalar() or 0

    # Get successful updates count
    success_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "success")
    )
    successful_updates = success_result.scalar() or 0

    # Get failed updates count
    failed_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "failed")
    )
    failed_count = failed_result.scalar() or 0

    # Calculate success rate
    success_rate = (successful_updates / total_updates * 100) if total_updates > 0 else 0.0

    # Get average update time (only for completed updates)
    avg_time_result = await db.execute(
        select(func.avg(UpdateHistory.duration_seconds)).where(
            UpdateHistory.duration_seconds.isnot(None)
        )
    )
    avg_update_time = avg_time_result.scalar() or 0.0

    # Get most updated containers (top 5)
    most_updated_result = await db.execute(
        select(
            UpdateHistory.container_name,
            func.count(UpdateHistory.id).label("update_count")
        )
        .group_by(UpdateHistory.container_name)
        .order_by(func.count(UpdateHistory.id).desc())
        .limit(5)
    )
    most_updated_rows = most_updated_result.all()
    most_updated_containers = [
        {"container_name": row[0], "update_count": row[1]}
        for row in most_updated_rows
    ]

    return {
        "success_rate": round(success_rate, 2),
        "total_updates": total_updates,
        "avg_update_time": round(float(avg_update_time), 2) if avg_update_time else 0.0,
        "failed_count": failed_count,
        "most_updated_containers": most_updated_containers
    }


@router.get("/{history_id}", response_model=UpdateHistorySchema)
async def get_history(
    history_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> UpdateHistorySchema:
    """Get history record details.

    Args:
        history_id: History ID

    Returns:
        History record
    """
    result = await db.execute(
        select(UpdateHistory)
        .options(
            undefer(UpdateHistory.event_type),
            undefer(UpdateHistory.dependency_type),
            undefer(UpdateHistory.dependency_id),
            undefer(UpdateHistory.dependency_name),
        )
        .where(UpdateHistory.id == history_id)
    )
    history = result.scalar_one_or_none()

    if not history:
        raise HTTPException(status_code=404, detail="History not found")

    return history


@router.post("/{history_id}/rollback")
async def rollback_update(
    history_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Rollback an update.

    This will:
    1. Restore the previous tag in compose file
    2. Execute docker compose up -d
    3. Update container and history status

    Args:
        history_id: History ID to rollback

    Returns:
        Result of the rollback operation
    """
    try:
        result = await UpdateEngine.rollback_update(db, history_id)

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Rollback failed")
            )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid request")
    except OperationalError as e:
        logger.error(f"Database error during rollback: {e}")
        raise HTTPException(status_code=500, detail="Database error during rollback")
    except (KeyError, AttributeError) as e:
        logger.error(f"Invalid data during rollback: {e}")
        raise HTTPException(status_code=500, detail="Invalid rollback data")
