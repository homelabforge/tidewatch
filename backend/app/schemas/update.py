"""Pydantic schemas for updates."""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class UpdateSchema(BaseModel):
    """Update response schema."""

    id: int
    container_id: int
    container_name: str
    from_tag: str
    to_tag: str
    registry: str
    reason_type: str
    reason_summary: Optional[str] = None
    recommendation: Optional[str] = None
    changelog: Optional[str] = None
    changelog_url: Optional[str] = None
    cves_fixed: List[str] = Field(default_factory=list)
    current_vulns: int
    new_vulns: int
    vuln_delta: int
    published_date: Optional[datetime] = None
    image_size_delta: int
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None
    backoff_multiplier: int = 3
    snoozed_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateApproval(BaseModel):
    """Update approval request."""

    approved: bool
    approved_by: str = "user"


class UpdateApply(BaseModel):
    """Update apply request."""

    triggered_by: str = "user"  # Who triggered the update: username, "system", "scheduler"


class UpdateReasoning(BaseModel):
    """Update reasoning for display."""

    primary_reason: str  # "Security patch", "New features", "Bug fixes"
    cves_fixed: list[str]
    vulnerability_improvement: str  # "Fixes 3 critical CVEs"
    changelog_summary: Optional[str] = None
    recommendation: str  # "Highly recommended", "Optional", "Review required"
