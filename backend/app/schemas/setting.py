"""Pydantic schemas for settings."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# Sensitive setting keys that should be masked in API responses
SENSITIVE_KEYS = {
    "dockerhub_token",
    "ghcr_token",
    "vulnforge_api_key",
    "vulnforge_password",
    "ntfy_api_key",
}


class SettingSchema(BaseModel):
    """Setting response schema."""

    key: str
    value: str
    category: str
    description: Optional[str] = None
    encrypted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    """Setting update request."""

    value: str = Field(..., min_length=0)


class SettingCategory(BaseModel):
    """Settings grouped by category."""

    category: str
    settings: list[SettingSchema]
