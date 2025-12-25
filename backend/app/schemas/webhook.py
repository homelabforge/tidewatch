"""Schemas for webhook configuration and management."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, HttpUrl, Field, field_validator, ConfigDict


# Valid event types that can trigger webhooks
VALID_WEBHOOK_EVENTS = [
    "update_available",
    "update_applied",
    "update_failed",
    "update_rolled_back",
    "container_started",
    "container_stopped",
    "container_restarted",
    "scan_completed",
    "scan_failed",
]


class WebhookCreate(BaseModel):
    """Schema for creating a new webhook."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Unique webhook name"
    )
    url: HttpUrl = Field(..., description="Webhook URL (HTTPS recommended)")
    secret: str = Field(
        ..., min_length=8, max_length=256, description="HMAC secret for signature"
    )
    events: List[str] = Field(
        ..., min_length=1, description="List of event types to trigger on"
    )
    enabled: bool = Field(default=True, description="Whether webhook is enabled")
    retry_count: int = Field(
        default=3, ge=0, le=10, description="Number of retry attempts"
    )

    @field_validator("events")
    @classmethod
    def validate_events(cls, v):
        """Validate that all events are recognized."""
        invalid_events = [e for e in v if e not in VALID_WEBHOOK_EVENTS]
        if invalid_events:
            raise ValueError(
                f"Invalid event types: {invalid_events}. "
                f"Valid events: {VALID_WEBHOOK_EVENTS}"
            )
        return v

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v):
        """Ensure URL uses HTTP or HTTPS."""
        if v.scheme not in ["http", "https"]:
            raise ValueError("URL must use http or https scheme")
        return v


class WebhookUpdate(BaseModel):
    """Schema for updating an existing webhook."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[HttpUrl] = None
    secret: Optional[str] = Field(None, min_length=8, max_length=256)
    events: Optional[List[str]] = Field(None, min_length=1)
    enabled: Optional[bool] = None
    retry_count: Optional[int] = Field(None, ge=0, le=10)

    @field_validator("events")
    @classmethod
    def validate_events(cls, v):
        """Validate that all events are recognized."""
        if v is not None:
            invalid_events = [e for e in v if e not in VALID_WEBHOOK_EVENTS]
            if invalid_events:
                raise ValueError(
                    f"Invalid event types: {invalid_events}. "
                    f"Valid events: {VALID_WEBHOOK_EVENTS}"
                )
        return v

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v):
        """Ensure URL uses HTTP or HTTPS."""
        if v is not None and v.scheme not in ["http", "https"]:
            raise ValueError("URL must use http or https scheme")
        return v


class WebhookSchema(BaseModel):
    """Schema for webhook response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    events: List[str]
    enabled: bool
    retry_count: int
    last_triggered: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WebhookTestResponse(BaseModel):
    """Response from testing a webhook."""

    success: bool
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    message: str
