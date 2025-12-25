"""Container restart state model for tracking intelligent retry logic."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Float,
    JSON,
    ForeignKey,
)
from sqlalchemy.sql import func

from app.db import Base


class ContainerRestartState(Base):
    """Track intelligent restart state and backoff for containers.

    This model maintains the state machine for exponential backoff retry logic,
    tracking consecutive failures, current backoff delay, and success windows.
    """

    __tablename__ = "container_restart_state"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Container reference
    container_id = Column(
        Integer, ForeignKey("containers.id"), nullable=False, unique=True, index=True
    )
    container_name = Column(String, nullable=False, index=True)

    # Restart tracking
    consecutive_failures = Column(Integer, default=0, nullable=False)
    total_restarts = Column(Integer, default=0, nullable=False)
    last_exit_code = Column(Integer, nullable=True)
    last_failure_reason = Column(
        String, nullable=True
    )  # "exit_code_1", "health_check_failed", "oom_killed"

    # Backoff state
    current_backoff_seconds = Column(Float, default=0.0, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    max_retries_reached = Column(Boolean, default=False, nullable=False)

    # Success tracking (for reset logic)
    last_successful_start = Column(DateTime(timezone=True), nullable=True)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    success_window_seconds = Column(
        Integer, default=300, nullable=False
    )  # 5 minutes default

    # Configuration (per-container overrides)
    enabled = Column(Boolean, default=True, nullable=False)
    max_attempts = Column(Integer, default=10, nullable=False)
    backoff_strategy = Column(
        String, default="exponential", nullable=False
    )  # exponential, linear, fixed
    base_delay_seconds = Column(Float, default=2.0, nullable=False)
    max_delay_seconds = Column(Float, default=300.0, nullable=False)

    # Health check configuration
    health_check_enabled = Column(Boolean, default=True, nullable=False)
    health_check_timeout = Column(Integer, default=60, nullable=False)
    rollback_on_health_fail = Column(Boolean, default=False, nullable=False)

    # Circuit breaker
    paused_until = Column(DateTime(timezone=True), nullable=True)  # Manual pause
    pause_reason = Column(String, nullable=True)

    # Metadata
    restart_history = Column(
        JSON, default=list, nullable=False
    )  # Last N restart timestamps
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ContainerRestartState("
            f"id={self.id}, "
            f"container_name='{self.container_name}', "
            f"consecutive_failures={self.consecutive_failures}, "
            f"max_retries_reached={self.max_retries_reached})>"
        )

    @property
    def is_paused(self) -> bool:
        """Check if restart is currently paused."""
        if not self.paused_until:
            return False
        # Ensure both datetimes are timezone-aware for comparison
        paused_until = (
            self.paused_until.replace(tzinfo=timezone.utc)
            if self.paused_until.tzinfo is None
            else self.paused_until
        )
        return datetime.now(timezone.utc) < paused_until

    @property
    def is_ready_for_retry(self) -> bool:
        """Check if container is ready for another retry attempt."""
        if not self.enabled or self.max_retries_reached or self.is_paused:
            return False

        if not self.next_retry_at:
            return True

        # Ensure both datetimes are timezone-aware for comparison
        next_retry = (
            self.next_retry_at.replace(tzinfo=timezone.utc)
            if self.next_retry_at.tzinfo is None
            else self.next_retry_at
        )
        return datetime.now(timezone.utc) >= next_retry

    @property
    def uptime_seconds(self) -> Optional[float]:
        """Calculate how long container has been running since last successful start."""
        if not self.last_successful_start:
            return None

        # Ensure both datetimes are timezone-aware for comparison
        last_start = (
            self.last_successful_start.replace(tzinfo=timezone.utc)
            if self.last_successful_start.tzinfo is None
            else self.last_successful_start
        )
        return (datetime.now(timezone.utc) - last_start).total_seconds()

    @property
    def should_reset_backoff(self) -> bool:
        """Check if backoff should be reset based on success window."""
        uptime = self.uptime_seconds
        if uptime is None:
            return False

        return uptime >= self.success_window_seconds

    def add_restart_to_history(self, timestamp: Optional[datetime] = None) -> None:
        """Add a restart timestamp to history (maintains last 100)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        history = self.restart_history or []
        history.append(timestamp.isoformat())

        # Keep only last 100 entries
        if len(history) > 100:
            history = history[-100:]

        self.restart_history = history
