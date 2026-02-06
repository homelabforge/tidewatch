"""Update history model for audit trail."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class UpdateHistory(Base):
    """Audit trail of all container updates and dependency actions."""

    __tablename__ = "update_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    container_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    update_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )  # Reference to the update that triggered this

    # Update details
    from_tag: Mapped[str] = mapped_column(String, nullable=False)
    to_tag: Mapped[str] = mapped_column(String, nullable=False)
    update_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # auto, manual, security, rollback
    backup_path: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Path to backup compose file

    # Execution details
    status: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # success, failed, rolled_back - indexed for filtering
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Context
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # Legacy reason text
    reason_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="unknown",
        server_default="unknown",
    )  # security, feature, bugfix, maintenance
    reason_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Snapshot of reason text for display
    triggered_by: Mapped[str] = mapped_column(String, default="system")  # system, user, scheduler
    cves_fixed: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")

    # Rollback support
    can_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Dependency update/ignore tracking (deferred to avoid loading issues during migrations)
    event_type: Mapped[str | None] = mapped_column(
        String, nullable=True, deferred=True
    )  # 'update', 'restart', 'dependency_update', 'dependency_ignore'
    dependency_type: Mapped[str | None] = mapped_column(
        String, nullable=True, deferred=True
    )  # 'dockerfile', 'http_server', 'app_dependency'
    dependency_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, deferred=True
    )  # Reference to specific dependency
    dependency_name: Mapped[str | None] = mapped_column(
        String, nullable=True, deferred=True
    )  # For display purposes
    file_path: Mapped[str | None] = mapped_column(
        String, nullable=True, deferred=True
    )  # Path to file that was updated (Dockerfile, package.json, etc.)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )  # Indexed for date filtering
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )  # Indexed for sorting/ordering

    def __repr__(self) -> str:
        return f"<UpdateHistory({self.container_name}: {self.from_tag} → {self.to_tag}, {self.status})>"
