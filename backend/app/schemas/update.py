"""Pydantic schemas for updates."""

from datetime import datetime
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field, field_validator


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
    scope_violation: int = 0
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

    # Decision traceability
    decision_trace: Optional[Dict[str, Any]] = None
    update_kind: Optional[str] = None
    change_type: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("decision_trace", mode="before")
    @classmethod
    def parse_decision_trace(cls, v: Any) -> Optional[Dict[str, Any]]:
        """Parse JSON string to dict for decision_trace field."""
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v


class UpdateApproval(BaseModel):
    """Update approval request."""

    approved: bool
    approved_by: str = "user"


class UpdateApply(BaseModel):
    """Update apply request."""

    triggered_by: str = (
        "user"  # Who triggered the update: username, "system", "scheduler"
    )


class UpdateReasoning(BaseModel):
    """Update reasoning for display."""

    primary_reason: str  # "Security patch", "New features", "Bug fixes"
    cves_fixed: list[str]
    vulnerability_improvement: str  # "Fixes 3 critical CVEs"
    changelog_summary: Optional[str] = None
    recommendation: str  # "Highly recommended", "Optional", "Review required"
