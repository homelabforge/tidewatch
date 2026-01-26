"""CheckJob model for tracking update check background jobs."""

from datetime import timezone

from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Index
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

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Status: queued, running, done, failed, canceled
    status = Column(String, nullable=False, default="queued", index=True)

    # Progress tracking
    total_count = Column(Integer, nullable=False, default=0)
    checked_count = Column(Integer, nullable=False, default=0)
    updates_found = Column(Integer, nullable=False, default=0)
    errors_count = Column(Integer, nullable=False, default=0)

    # Current container being processed (for live progress display)
    current_container_id = Column(Integer, nullable=True)
    current_container_name = Column(String, nullable=True)

    # Detailed results stored as JSON
    results = Column(JSON, default=list, server_default="[]")
    errors = Column(JSON, default=list, server_default="[]")

    # Execution context
    triggered_by = Column(String, nullable=False, default="user")  # user, scheduler
    cancel_requested = Column(Integer, nullable=False, default=0)

    # Error information for failed jobs
    error_message = Column(Text, nullable=True)

    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CheckJob(id={self.id}, status={self.status}, "
            f"{self.checked_count}/{self.total_count})>"
        )

    @property
    def progress_percent(self) -> float:
        """Calculate progress as a percentage."""
        total: int = self.total_count  # type: ignore[assignment]
        checked: int = self.checked_count  # type: ignore[assignment]
        if total == 0:
            return 0.0
        return round((checked / total) * 100, 1)

    @property
    def is_active(self) -> bool:
        """Check if job is still running or queued."""
        status: str = self.status  # type: ignore[assignment]
        return status in ("queued", "running")

    @property
    def duration_seconds(self) -> float | None:
        """Calculate job duration in seconds, if completed."""
        started = self.started_at
        completed = self.completed_at
        if started is not None and completed is not None:
            # Normalize timezone-naive datetimes to UTC for comparison
            # SQLite returns naive datetimes even when stored with timezone
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            return (completed - started).total_seconds()
        return None
