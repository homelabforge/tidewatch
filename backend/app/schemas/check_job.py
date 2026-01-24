"""Pydantic schemas for check jobs."""

from datetime import datetime
from typing import Optional, Any

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
    current_container: Optional[str] = None


class CheckJobResult(BaseModel):
    """Full check job response with results."""

    id: int
    status: str
    total_count: int
    checked_count: int
    updates_found: int
    errors_count: int
    progress_percent: float
    current_container: Optional[str] = None
    triggered_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    results: Optional[list[dict[str, Any]]] = Field(default=None)
    errors: Optional[list[dict[str, Any]]] = Field(default=None)

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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

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
