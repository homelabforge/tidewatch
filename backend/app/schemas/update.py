"""Pydantic schemas for updates."""

from datetime import datetime
from typing import Any

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
    reason_summary: str | None = None
    recommendation: str | None = None
    changelog: str | None = None
    changelog_url: str | None = None
    cves_fixed: list[str] = Field(default_factory=list)
    current_vulns: int
    new_vulns: int
    vuln_delta: int
    published_date: datetime | None = None
    image_size_delta: int
    status: str
    scope_violation: int = 0
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: datetime | None = None
    last_error: str | None = None
    backoff_multiplier: int = 3
    snoozed_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Decision traceability
    decision_trace: dict[str, Any] | None = None
    update_kind: str | None = None
    change_type: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("decision_trace", mode="before")
    @classmethod
    def parse_decision_trace(cls, v: Any) -> dict[str, Any] | None:
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

    triggered_by: str = "user"  # Who triggered the update: username, "system", "scheduler"


class UpdateReasoning(BaseModel):
    """Update reasoning for display."""

    primary_reason: str  # "Security patch", "New features", "Bug fixes"
    cves_fixed: list[str]
    vulnerability_improvement: str  # "Fixes 3 critical CVEs"
    changelog_summary: str | None = None
    recommendation: str  # "Highly recommended", "Optional", "Review required"
