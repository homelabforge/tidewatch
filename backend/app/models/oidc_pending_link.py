"""OIDC pending link model for username-based account linking with password verification."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OIDCPendingLink(Base):
    """OIDC pending link model for username-based account linking.

    Stores temporary tokens for linking OIDC accounts to existing local accounts
    when usernames match but no OIDC subject link exists. Requires password
    verification before linking.

    Security features:
    - Short expiration (5 minutes default)
    - Limited password attempts (3 default)
    - One-time use (token deleted after successful link)
    - Cryptographically random tokens
    """

    __tablename__ = "oidc_pending_links"

    token: Mapped[str] = mapped_column(String(128), primary_key=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    oidc_claims: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string of ID token claims
    userinfo_claims: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON string of userinfo endpoint claims
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)  # Provider display name
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Failed password attempts
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Indexes for efficient queries and cleanup
    __table_args__ = (
        Index("idx_oidc_pending_links_username", "username"),
        Index("idx_oidc_pending_links_expires_at", "expires_at"),
    )

    def __repr__(self):
        return f"<OIDCPendingLink(token={self.token[:16]}..., username={self.username}, expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the pending link token has expired."""
        now = datetime.now(UTC)
        expires = self.expires_at
        # Handle timezone-naive datetimes from SQLite
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return bool(now > expires)

    @classmethod
    def get_expiry_time(cls, minutes: int = 5) -> datetime:
        """Get expiry timestamp for a new pending link token (default 5 minutes)."""
        return datetime.now(UTC) + timedelta(minutes=minutes)
