"""Webhook model for event notifications."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, func
from app.db import Base


class Webhook(Base):
    """Webhook configuration for external event notifications.

    Webhooks allow TideWatch to send HTTP POST requests to external URLs
    when certain events occur (e.g., update_applied, update_failed).
    """

    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    url = Column(String, nullable=False)
    secret = Column(String, nullable=False)  # Encrypted HMAC secret for signature
    events = Column(JSON, nullable=False, default=list)  # List of event types to trigger on
    enabled = Column(Boolean, nullable=False, default=True)
    retry_count = Column(Integer, nullable=False, default=3)

    # Status tracking
    last_triggered = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)  # "success", "failed", or error message
    last_error = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Webhook(id={self.id}, name='{self.name}', url='{self.url}', enabled={self.enabled})>"
