"""Pydantic schemas for check jobs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CheckJobCreate(BaseModel):
    """Request to create a new check job."""

    triggered_by: str = "user"


class CheckJobProgress(BaseModel):
    """Real-time progress for a running check job."""

    job_id: int
    status: str
    total_count: int
    checked_count: int
    updates_found: int
    errors_count: int
    progress_percent: float
    current_container: str | None = None


class CheckJobResult(BaseModel):
    """Full check job response with results."""

    id: int
    status: str
    total_count: int
    checked_count: int
    updates_found: int
    errors_count: int
    progress_percent: float
    current_container: str | None = None
    triggered_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    results: list[dict[str, Any]] | None = Field(default=None)
    errors: list[dict[str, Any]] | None = Field(default=None)

    model_config = {"from_attributes": True}


class CheckJobSummary(BaseModel):
    """Summary for job history listing."""

    id: int
    status: str
    total_count: int
    checked_count: int
    updates_found: int
    errors_count: int
    triggered_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    model_config = {"from_attributes": True}


class CheckJobStartResponse(BaseModel):
    """Response when starting a check job."""

    success: bool
    job_id: int
    status: str
    message: str
    already_running: bool = False


class CheckJobCancelResponse(BaseModel):
    """Response when canceling a check job."""

    success: bool
    message: str
