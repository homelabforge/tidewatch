"""Settings model for database-first configuration."""

from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.db import Base


class Setting(Base):
    """Application settings stored in database."""

    __tablename__ = "settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
    category = Column(
        String, nullable=False, default="general"
    )  # paths, integrations, notifications
    description = Column(String, nullable=True)
    encrypted = Column(Boolean, default=False)  # For sensitive values like API keys
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Setting(key={self.key}, category={self.category})>"
