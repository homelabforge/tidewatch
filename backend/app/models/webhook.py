"""Webhook model for event notifications."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Webhook(Base):
    """Webhook configuration for external event notifications.

    Webhooks allow TideWatch to send HTTP POST requests to external URLs
    when certain events occur (e.g., update_applied, update_failed).
    """

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Encrypted HMAC secret for signature
    events: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )  # List of event types to trigger on
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Status tracking
    last_triggered: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # "success", "failed", or error message
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Webhook(id={self.id}, name='{self.name}', url='{self.url}', enabled={self.enabled})>"
        )
