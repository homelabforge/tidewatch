"""Pydantic schemas for settings."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from app.services.settings_service import SettingsService

# Sensitive setting keys that must be masked in API responses. Derived from the
# encrypted:True DEFAULTS flags (plus a few extras) so the set can never drift
# out of sync with the actual encrypted settings. Public name preserved for
# existing importers (routes/settings.py).
SENSITIVE_KEYS = SettingsService.sensitive_keys()


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
