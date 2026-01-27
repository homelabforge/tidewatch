"""Pydantic schemas for container restart functionality."""

from datetime import datetime

from pydantic import BaseModel, Field


class RestartStateSchema(BaseModel):
    """Container restart state schema."""

    id: int
    container_id: int
    container_name: str
    consecutive_failures: int
    total_restarts: int
    last_exit_code: int | None = None
    last_failure_reason: str | None = None
    current_backoff_seconds: float
    next_retry_at: datetime | None = None
    max_retries_reached: bool
    last_successful_start: datetime | None = None
    last_failure_at: datetime | None = None
    success_window_seconds: int
    enabled: bool
    max_attempts: int
    backoff_strategy: str
    base_delay_seconds: float
    max_delay_seconds: float
    health_check_enabled: bool
    health_check_timeout: int
    rollback_on_health_fail: bool
    paused_until: datetime | None = None
    pause_reason: str | None = None
    restart_history: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    # Computed properties
    is_paused: bool = False
    is_ready_for_retry: bool = False
    uptime_seconds: float | None = None

    model_config = {"from_attributes": True}


class RestartLogSchema(BaseModel):
    """Container restart log schema."""

    id: int
    container_id: int
    container_name: str
    attempt_number: int
    trigger_reason: str
    exit_code: int | None = None
    backoff_delay_seconds: float
    success: bool
    health_check_passed: bool | None = None
    error_message: str | None = None
    scheduled_at: datetime
    executed_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class RestartHistoryResponse(BaseModel):
    """Restart history response."""

    total: int
    logs: list[RestartLogSchema]


class EnableRestartRequest(BaseModel):
    """Request to enable auto-restart."""

    max_attempts: int | None = 10
    backoff_strategy: str | None = "exponential"
    base_delay_seconds: float | None = 2.0
    max_delay_seconds: float | None = 300.0
    success_window_seconds: int | None = 300
    health_check_enabled: bool | None = True
    health_check_timeout: int | None = 60
    rollback_on_health_fail: bool | None = False


class DisableRestartRequest(BaseModel):
    """Request to disable auto-restart."""

    reason: str | None = None


class ResetRestartStateRequest(BaseModel):
    """Request to reset restart state."""

    reason: str | None = None


class PauseRestartRequest(BaseModel):
    """Request to pause restart temporarily."""

    duration_seconds: int = Field(gt=0, le=604800)  # Max 1 week in seconds
    reason: str | None = None


class ManualRestartRequest(BaseModel):
    """Request to manually trigger a restart."""

    reason: str
    skip_backoff: bool = False


class RestartStatsResponse(BaseModel):
    """Aggregate restart statistics."""

    total_containers: int  # Renamed from total_containers_monitored
    containers_with_restart_enabled: int  # New field (same as total_containers for now)
    total_restarts_24h: int  # Renamed from total_restarts_today
    total_restarts_7d: int  # Renamed from total_restarts_week
    containers_with_failures: int
    average_backoff_seconds: float


class RestartActionResponse(BaseModel):
    """Response for restart action."""

    success: bool
    message: str
    state: RestartStateSchema | None = None
