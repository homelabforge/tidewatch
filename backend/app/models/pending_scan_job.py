"""PendingScanJob model for durable VulnForge scan tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.update import Update


class PendingScanJob(Base):
    """Tracks VulnForge scan requests across TideWatch restarts.

    Created atomically in the same transaction as the update status change.
    An APScheduler worker processes these rows through their lifecycle:
    pending -> triggered -> polling -> completed/failed.

    Replaces the fire-and-forget asyncio.create_task() pattern.
    """

    __tablename__ = "pending_scan_jobs"
    __table_args__ = (
        Index("idx_pending_scan_job_status", "status"),
        Index("idx_pending_scan_job_update_id", "update_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_name: Mapped[str] = mapped_column(String(255), nullable=False)
    update_id: Mapped[int] = mapped_column(Integer, ForeignKey("updates.id"), nullable=False)

    # VulnForge correlation IDs (populated as workflow progresses)
    vulnforge_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vulnforge_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status: pending, triggered, polling, completed, failed
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # Trigger retry state (pending → triggered transition)
    trigger_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_trigger_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Polling state
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_polls: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    update: Mapped[Update] = relationship("Update")

    def __repr__(self) -> str:
        return (
            f"<PendingScanJob(id={self.id}, container={self.container_name}, "
            f"status={self.status}, job_id={self.vulnforge_job_id})>"
        )

    @property
    def is_active(self) -> bool:
        """Check if job is still in progress."""
        return self.status in ("pending", "triggered", "polling")

    @property
    def polls_exhausted(self) -> bool:
        """Check if maximum poll attempts have been reached."""
        return self.poll_count >= self.max_polls
