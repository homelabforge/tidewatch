"""User model for admin account management."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """Single admin user for TideWatch authentication.

    TideWatch is a single-user app — this table will have at most one row.
    Previously stored as individual key-value pairs in the settings table.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    full_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    auth_method: Mapped[str] = mapped_column(String, nullable=False, default="local")  # local, oidc
    oidc_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    oidc_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_profile_dict(self) -> dict:
        """Convert to profile dictionary for API responses."""
        return {
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "auth_method": self.auth_method,
            "oidc_provider": self.oidc_provider or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "last_login": self.last_login.isoformat() if self.last_login else "",
        }

    def __repr__(self) -> str:
        return f"<User(username={self.username}, auth_method={self.auth_method})>"
