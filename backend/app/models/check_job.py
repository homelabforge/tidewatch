"""CheckJob model for tracking update check background jobs."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class CheckJob(Base):
    """Background update check job with progress tracking.

    Tracks the state and progress of asynchronous update checks,
    enabling non-blocking UI updates and job history.
    """

    __tablename__ = "check_jobs"
    __table_args__ = (
        Index("idx_check_job_status", "status"),
        Index("idx_check_job_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Status: queued, running, done, failed, canceled
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)

    # Progress tracking
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updates_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-container progress is sent via SSE only (no per-container DB commits).
    # These columns remain for schema compatibility but are not actively written.
    # DB-level progress uses checked_count/total_count above; real-time progress
    # is delivered via SSE events from check_job_service.
    current_container_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_container_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Detailed results stored as JSON
    results: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")

    # Execution context
    triggered_by: Mapped[str] = mapped_column(
        String, nullable=False, default="user"
    )  # user, scheduler
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Error information for failed jobs
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CheckJob(id={self.id}, status={self.status}, "
            f"{self.checked_count}/{self.total_count})>"
        )

    @property
    def progress_percent(self) -> float:
        """Calculate progress as a percentage."""
        if self.total_count == 0:
            return 0.0
        return round((self.checked_count / self.total_count) * 100, 1)

    @property
    def is_active(self) -> bool:
        """Check if job is still running or queued."""
        return self.status in ("queued", "running")

    @property
    def duration_seconds(self) -> float | None:
        """Calculate job duration in seconds, if completed."""
        started = self.started_at
        completed = self.completed_at
        if started is not None and completed is not None:
            # Normalize timezone-naive datetimes to UTC for comparison
            # SQLite returns naive datetimes even when stored with timezone
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=UTC)
            return (completed - started).total_seconds()
        return None
