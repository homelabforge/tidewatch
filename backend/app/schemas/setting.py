"""Pydantic schemas for settings."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

# Sensitive setting keys that should be masked in API responses
SENSITIVE_KEYS = {
    "admin_password_hash",
    "dockerhub_token",
    "ghcr_token",
    "vulnforge_api_key",
    "vulnforge_password",
    "ntfy_api_key",
    "gotify_token",
    "pushover_api_token",
    "pushover_user_key",
    "telegram_bot_token",
    "email_smtp_password",
    "smtp_password",
    "oidc_client_secret",
    "encryption_key",
}


class SettingSchema(BaseModel):
    """Setting response schema."""

    key: str
    value: str
    category: str
    description: str | None = None
    encrypted: bool | None = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    """Setting update request."""

    value: str = Field(..., min_length=0)


class SettingCategory(BaseModel):
    """Settings grouped by category."""

    category: str
    settings: Sequence[SettingSchema]
