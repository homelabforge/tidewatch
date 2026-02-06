"""Security key model for database-backed secret management."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class SecretKey(Base):
    """Application security keys stored in database.

    Supports two-tier key architecture:
    - Tier 1: Master key (file-based, encrypts Tier 2)
    - Tier 2: Application keys (database-backed, encrypted with master key)
    """

    __tablename__ = "secret_keys"

    key_name: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    key_value: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Encrypted or plain based on key_type
    key_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'master', 'jwt', 'session', 'encryption'
    encrypted: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if encrypted with master key
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
