"""Pydantic schemas for update history."""

from datetime import datetime

from pydantic import BaseModel, Field


class UpdateHistorySchema(BaseModel):
    """Update history response schema."""

    id: int
    container_id: int
    container_name: str
    from_tag: str
    to_tag: str
    update_id: int | None = None
    update_type: str | None = None
    status: str
    reason: str | None = None
    reason_type: str | None = None
    reason_summary: str | None = None
    error_message: str | None = None
    triggered_by: str
    backup_path: str | None = None
    can_rollback: bool
    rolled_back_at: datetime | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    cves_fixed: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    created_at: datetime | None = None

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
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    error_message: str | None = None
    performed_by: str  # "System", "Auto-Restart", "User", or username

    # Update-specific fields (nullable for restart events)
    from_tag: str | None = None
    to_tag: str | None = None
    update_type: str | None = None
    reason: str | None = None
    reason_type: str | None = None
    reason_summary: str | None = None
    can_rollback: bool = False
    rollback_available: bool = False  # Alias for can_rollback
    backup_path: str | None = None
    cves_fixed: list[str] = Field(default_factory=list)
    rolled_back_at: datetime | None = None

    # Restart-specific fields (nullable for update events)
    attempt_number: int | None = None
    trigger_reason: str | None = None
    exit_code: int | None = None
    health_check_passed: bool | None = None
    final_container_status: str | None = None

    # Dependency-specific fields (nullable for non-dependency events)
    dependency_type: str | None = None  # 'dockerfile', 'http_server', 'app_dependency'
    dependency_id: int | None = None
    dependency_name: str | None = None

    model_config = {"from_attributes": True}


class HistorySummary(BaseModel):
    """History summary for dashboard."""

    total_updates: int
    successful_updates: int
    failed_updates: int
    rollbacks: int
    last_24h_updates: int
    cves_fixed_total: int
