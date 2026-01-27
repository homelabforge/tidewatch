"""Container restart log model for audit trail of restart attempts."""


from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class ContainerRestartLog(Base):
    """Audit log of all container restart attempts.

    Provides a detailed audit trail of every restart attempt including
    the trigger reason, backoff delay, success/failure, and health check results.
    """

    __tablename__ = "container_restart_log"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Container reference
    container_id = Column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )
    container_name = Column(String, nullable=False, index=True)
    restart_state_id = Column(
        Integer, ForeignKey("container_restart_state.id"), nullable=False
    )

    # Attempt details
    attempt_number = Column(Integer, nullable=False)
    trigger_reason = Column(
        String, nullable=False
    )  # "exit_code", "health_check", "manual", "oom_killed"
    exit_code = Column(Integer, nullable=True)
    failure_reason = Column(
        String, nullable=True
    )  # Detailed reason from container state

    # Backoff strategy used
    backoff_strategy = Column(String, nullable=False)  # exponential, linear, fixed
    backoff_delay_seconds = Column(Float, nullable=False)

    # Execution
    restart_method = Column(
        String, nullable=False
    )  # "docker_compose", "docker_restart"
    docker_command = Column(String, nullable=True)  # Actual command executed

    # Result
    success = Column(Boolean, nullable=False)
    error_message = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Health validation
    health_check_enabled = Column(Boolean, default=False, nullable=False)
    health_check_passed = Column(Boolean, nullable=True)
    health_check_duration = Column(Float, nullable=True)
    health_check_method = Column(String, nullable=True)  # "http", "docker_inspect"
    health_check_error = Column(String, nullable=True)

    # Container state after restart
    final_container_status = Column(
        String, nullable=True
    )  # "running", "exited", "restarting"
    final_exit_code = Column(Integer, nullable=True)

    # Timestamps
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ContainerRestartLog("
            f"id={self.id}, "
            f"container_name='{self.container_name}', "
            f"attempt={self.attempt_number}, "
            f"success={self.success})>"
        )

    @property
    def execution_duration(self) -> float | None:
        """Calculate total execution duration including health checks."""
        if not self.completed_at:
            return None

        return (self.completed_at - self.executed_at).total_seconds()

    @property
    def scheduling_delay(self) -> float | None:
        """Calculate how long the job was delayed from scheduled time."""
        if not self.executed_at or not self.scheduled_at:
            return None

        delay = (self.executed_at - self.scheduled_at).total_seconds()
        return max(0, delay)  # Never negative

    @property
    def is_completed(self) -> bool:
        """Check if restart attempt has completed."""
        return self.completed_at is not None
