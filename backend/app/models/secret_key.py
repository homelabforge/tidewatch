"""Security key model for database-backed secret management."""

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.sql import func

from app.database import Base


class SecretKey(Base):
    """Application security keys stored in database.

    Supports two-tier key architecture:
    - Tier 1: Master key (file-based, encrypts Tier 2)
    - Tier 2: Application keys (database-backed, encrypted with master key)
    """

    __tablename__ = "secret_keys"

    key_name = Column(String, primary_key=True, index=True)
    key_value = Column(String, nullable=False)  # Encrypted or plain based on key_type
    key_type = Column(
        String, nullable=False
    )  # 'master', 'jwt', 'session', 'encryption'
    encrypted = Column(Boolean, default=False)  # True if encrypted with master key
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
