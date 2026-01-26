"""Container restart management API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.services.auth import require_auth
from app.models.container import Container
from app.models.restart_state import ContainerRestartState
from app.models.restart_log import ContainerRestartLog
from app.schemas.restart import (
    RestartStateSchema,
    RestartLogSchema,
    RestartHistoryResponse,
    EnableRestartRequest,
    DisableRestartRequest,
    ResetRestartStateRequest,
    PauseRestartRequest,
    ManualRestartRequest,
    RestartStatsResponse,
    RestartActionResponse,
)
from app.services.restart_service import RestartService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{container_id}/state", response_model=RestartStateSchema)
async def get_restart_state(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartStateSchema:
    """Get current restart state for a container.

    Args:
        container_id: Container ID

    Returns:
        Restart state with backoff info and computed properties
    """
    # Verify container exists
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get or create restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        # Create default state
        state = ContainerRestartState(
            container_id=container.id,
            container_name=container.name,
            enabled=container.auto_restart_enabled,
            max_attempts=container.restart_max_attempts,
            backoff_strategy=container.restart_backoff_strategy,
            success_window_seconds=container.restart_success_window,
        )
        db.add(state)
        await db.commit()
        await db.refresh(state)

    # Build response with computed properties
    response = RestartStateSchema.model_validate(state)
    response.is_paused = state.is_paused
    response.is_ready_for_retry = state.is_ready_for_retry
    response.uptime_seconds = state.uptime_seconds

    return response


@router.get("/{container_id}/history", response_model=RestartHistoryResponse)
async def get_restart_history(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> RestartHistoryResponse:
    """Get restart attempt history for a container.

    Args:
        container_id: Container ID
        limit: Maximum number of entries (1-500)
        offset: Pagination offset

    Returns:
        Paginated list of restart log entries
    """
    # Verify container exists
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get total count
    count_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartLog)
        .where(ContainerRestartLog.container_id == container_id)
    )
    total = count_result.scalar_one()

    # Get logs
    logs_result = await db.execute(
        select(ContainerRestartLog)
        .where(ContainerRestartLog.container_id == container_id)
        .order_by(desc(ContainerRestartLog.scheduled_at))
        .limit(limit)
        .offset(offset)
    )
    logs = logs_result.scalars().all()

    return RestartHistoryResponse(
        total=total, logs=[RestartLogSchema.model_validate(log) for log in logs]
    )


@router.post("/{container_id}/enable", response_model=RestartActionResponse)
async def enable_restart(
    container_id: int,
    request: EnableRestartRequest,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Enable auto-restart for a container.

    Args:
        container_id: Container ID
        request: Configuration parameters

    Returns:
        Success response with updated state
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get or create restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        state = ContainerRestartState(
            container_id=container.id,
            container_name=container.name,
        )
        db.add(state)

    # Update state
    state.enabled = True
    state.max_attempts = request.max_attempts
    state.backoff_strategy = request.backoff_strategy
    state.base_delay_seconds = request.base_delay_seconds
    state.max_delay_seconds = request.max_delay_seconds
    state.success_window_seconds = request.success_window_seconds
    state.health_check_enabled = request.health_check_enabled
    state.health_check_timeout = request.health_check_timeout
    state.rollback_on_health_fail = request.rollback_on_health_fail

    # Update container
    container.auto_restart_enabled = True
    container.restart_max_attempts = request.max_attempts
    container.restart_backoff_strategy = request.backoff_strategy
    container.restart_success_window = request.success_window_seconds

    await db.commit()
    await db.refresh(state)

    return RestartActionResponse(
        success=True,
        message=f"Auto-restart enabled for {container.name}",
        state=RestartStateSchema.model_validate(state),
    )


@router.post("/{container_id}/disable", response_model=RestartActionResponse)
async def disable_restart(
    container_id: int,
    request: DisableRestartRequest,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Disable auto-restart for a container.

    Args:
        container_id: Container ID
        request: Disable request with optional reason

    Returns:
        Success response
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if state:
        state.enabled = False
        if request.reason:
            state.pause_reason = f"Disabled: {request.reason}"

    # Update container
    container.auto_restart_enabled = False

    await db.commit()
    if state:
        await db.refresh(state)

    return RestartActionResponse(
        success=True,
        message=f"Auto-restart disabled for {container.name}",
        state=RestartStateSchema.model_validate(state) if state else None,
    )


@router.post("/{container_id}/reset", response_model=RestartActionResponse)
async def reset_restart_state(
    container_id: int,
    request: ResetRestartStateRequest,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Reset restart state (clear failures and backoff).

    Args:
        container_id: Container ID
        request: Reset request with optional reason

    Returns:
        Success response with reset state
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Restart state not found. Enable auto-restart first.",
        )

    # Reset state
    state.consecutive_failures = 0
    state.current_backoff_seconds = 0.0
    state.next_retry_at = None
    state.max_retries_reached = False
    state.last_failure_reason = None
    state.paused_until = None

    if request.reason:
        state.pause_reason = f"Reset: {request.reason}"

    await db.commit()
    await db.refresh(state)

    return RestartActionResponse(
        success=True,
        message=f"Restart state reset for {container.name}",
        state=RestartStateSchema.model_validate(state),
    )


@router.post("/{container_id}/pause", response_model=RestartActionResponse)
async def pause_restart(
    container_id: int,
    request: PauseRestartRequest,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Temporarily pause auto-restart for a container.

    Args:
        container_id: Container ID
        request: Pause duration and reason

    Returns:
        Success response with paused state
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Restart state not found. Enable auto-restart first.",
        )

    # Set pause
    pause_until = datetime.now(timezone.utc) + timedelta(
        seconds=request.duration_seconds
    )
    state.paused_until = pause_until
    state.pause_reason = request.reason or "Manual pause"

    await db.commit()
    await db.refresh(state)

    return RestartActionResponse(
        success=True,
        message=f"Auto-restart paused for {container.name} until {pause_until.isoformat()}",
        state=RestartStateSchema.model_validate(state),
    )


@router.post("/{container_id}/resume", response_model=RestartActionResponse)
async def resume_restart(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Resume auto-restart after pause.

    Args:
        container_id: Container ID

    Returns:
        Success response
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Restart state not found. Enable auto-restart first.",
        )

    # Clear pause
    state.paused_until = None
    state.pause_reason = None

    await db.commit()
    await db.refresh(state)

    return RestartActionResponse(
        success=True,
        message=f"Auto-restart resumed for {container.name}",
        state=RestartStateSchema.model_validate(state),
    )


@router.post("/{container_id}/manual-restart", response_model=RestartActionResponse)
async def manual_restart(
    container_id: int,
    request: ManualRestartRequest,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RestartActionResponse:
    """Manually trigger a restart (bypasses backoff if requested).

    Args:
        container_id: Container ID
        request: Manual restart request

    Returns:
        Success response with execution result
    """
    # Get container
    container_result = await db.execute(
        select(Container).where(Container.id == container_id)
    )
    container = container_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get or create restart state
    state_result = await db.execute(
        select(ContainerRestartState).where(
            ContainerRestartState.container_id == container_id
        )
    )
    state = state_result.scalar_one_or_none()

    if not state:
        state = ContainerRestartState(
            container_id=container.id,
            container_name=container.name,
        )
        db.add(state)
        await db.commit()
        await db.refresh(state)

    # Execute restart
    attempt_number = state.consecutive_failures + 1 if not request.skip_backoff else 1

    try:
        result = await RestartService.execute_restart(
            db=db,
            container=container,
            state=state,
            attempt_number=attempt_number,
            trigger_reason=f"manual: {request.reason}",
            exit_code=None,
        )

        if result["success"]:
            return RestartActionResponse(
                success=True,
                message=f"Successfully restarted {container.name}",
                state=RestartStateSchema.model_validate(state),
            )
        else:
            return RestartActionResponse(
                success=False,
                message=f"Restart failed: {result.get('error', 'Unknown error')}",
                state=RestartStateSchema.model_validate(state),
            )

    except OperationalError as e:
        return RestartActionResponse(
            success=False,
            message=f"Database error during restart: {str(e)}",
            state=RestartStateSchema.model_validate(state),
        )
    except (ValueError, KeyError, AttributeError) as e:
        return RestartActionResponse(
            success=False,
            message=f"Invalid restart data: {str(e)}",
            state=RestartStateSchema.model_validate(state),
        )


@router.get("/stats", response_model=RestartStatsResponse)
async def get_restart_stats(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> RestartStatsResponse:
    """Get aggregate restart statistics across all containers.

    Returns:
        Statistics summary
    """
    # Total containers with restart state
    total_result = await db.execute(
        select(func.count()).select_from(ContainerRestartState)
    )
    total_monitored = total_result.scalar_one()

    # Containers with failures
    failures_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartState)
        .where(ContainerRestartState.consecutive_failures > 0)
    )
    with_failures = failures_result.scalar_one()

    # Containers paused
    now = datetime.now(timezone.utc)
    paused_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartState)
        .where(
            and_(
                ContainerRestartState.paused_until.isnot(None),
                ContainerRestartState.paused_until > now,
            )
        )
    )
    paused_result.scalar_one()

    # Max retries reached
    max_retries_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartState)
        .where(ContainerRestartState.max_retries_reached)
    )
    max_retries_result.scalar_one()

    # Restarts today
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartLog)
        .where(ContainerRestartLog.scheduled_at >= today_start)
    )
    restarts_today = today_result.scalar_one()

    # Restarts this week
    week_start = today_start - timedelta(days=today_start.weekday())
    week_result = await db.execute(
        select(func.count())
        .select_from(ContainerRestartLog)
        .where(ContainerRestartLog.scheduled_at >= week_start)
    )
    restarts_week = week_result.scalar_one()

    # Average backoff
    backoff_result = await db.execute(
        select(func.avg(ContainerRestartState.current_backoff_seconds))
        .select_from(ContainerRestartState)
        .where(ContainerRestartState.current_backoff_seconds > 0)
    )
    avg_backoff = backoff_result.scalar_one() or 0.0

    # Success rate (last 100 restarts)
    recent_logs_result = await db.execute(
        select(ContainerRestartLog)
        .order_by(desc(ContainerRestartLog.scheduled_at))
        .limit(100)
    )
    recent_logs = recent_logs_result.scalars().all()

    if recent_logs:
        successful = sum(1 for log in recent_logs if log.success)
        (successful / len(recent_logs)) * 100
    else:
        pass

    return RestartStatsResponse(
        total_containers=total_monitored,
        containers_with_restart_enabled=total_monitored,  # For now, same as total_containers
        total_restarts_24h=restarts_today,
        total_restarts_7d=restarts_week,
        containers_with_failures=with_failures,
        average_backoff_seconds=avg_backoff,
    )
