"""Sibling drift event model for append-only audit trail."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class SiblingDriftEvent(Base):
    """Append-only record of sibling drift detected during a check run.

    One row per drifted sibling group per check run. Multi-container event:
    sibling_names and per_container_tags are stored as JSON strings.

    job_id is informational only (no FK) — used for correlating drift
    with the check run that detected it.
    """

    __tablename__ = "sibling_drift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    compose_file: Mapped[str] = mapped_column(String, nullable=False)
    registry: Mapped[str] = mapped_column(String, nullable=False)
    image: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sibling_names: Mapped[str] = mapped_column(String, nullable=False)  # JSON array
    dominant_tag: Mapped[str] = mapped_column(String, nullable=False)
    per_container_tags: Mapped[str] = mapped_column(String, nullable=False)  # JSON dict
    settings_divergent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciled_names: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON array
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<SiblingDriftEvent(image={self.image}, job_id={self.job_id})>"
