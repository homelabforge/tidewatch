"""Release corroboration cache model for persistent GitHub release check results."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ReleaseCorroborationCache(Base):
    """Cached GitHub release check results, keyed by (release_source, tag).

    Only EXISTS results are persisted. MISSING and ERROR are always re-checked.
    """

    __tablename__ = "release_corroboration_cache"
    __table_args__ = (
        UniqueConstraint("release_source", "tag", name="uq_corroboration_source_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_source: Mapped[str] = mapped_column(String, nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReleaseCorroborationCache({self.release_source}:{self.tag}={self.status})>"
