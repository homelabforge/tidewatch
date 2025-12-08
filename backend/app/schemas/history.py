"""Pydantic schemas for update history."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UpdateHistorySchema(BaseModel):
    """Update history response schema."""

    id: int
    container_id: int
    container_name: str
    from_tag: str
    to_tag: str
    update_id: Optional[int] = None
    update_type: Optional[str] = None
    status: str
    reason: Optional[str] = None
    reason_type: Optional[str] = None
    reason_summary: Optional[str] = None
    error_message: Optional[str] = None
    triggered_by: str
    backup_path: Optional[str] = None
    can_rollback: bool
    rolled_back_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    started_at: datetime
    cves_fixed: List[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# Alias for backward compatibility
HistorySchema = UpdateHistorySchema


class UnifiedHistoryEventSchema(BaseModel):
    """Unified schema for both update and restart events."""

    # Common fields (all events)
    id: int
    event_type: str  # "update" or "restart"
    container_id: int
    container_name: str
    status: str  # success, failed, restarted, failed_to_restart, crashed, rolled_back
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    error_message: Optional[str] = None
    performed_by: str  # "System", "Auto-Restart", "User", or username

    # Update-specific fields (nullable for restart events)
    from_tag: Optional[str] = None
    to_tag: Optional[str] = None
    update_type: Optional[str] = None
    reason: Optional[str] = None
    reason_type: Optional[str] = None
    reason_summary: Optional[str] = None
    can_rollback: bool = False
    rollback_available: bool = False  # Alias for can_rollback
    backup_path: Optional[str] = None
    cves_fixed: List[str] = Field(default_factory=list)
    rolled_back_at: Optional[datetime] = None

    # Restart-specific fields (nullable for update events)
    attempt_number: Optional[int] = None
    trigger_reason: Optional[str] = None
    exit_code: Optional[int] = None
    health_check_passed: Optional[bool] = None
    final_container_status: Optional[str] = None

    model_config = {"from_attributes": True}


class HistorySummary(BaseModel):
    """History summary for dashboard."""

    total_updates: int
    successful_updates: int
    failed_updates: int
    rollbacks: int
    last_24h_updates: int
    cves_fixed_total: int
