"""Update history model for audit trail."""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, JSON
from sqlalchemy.sql import func
from app.db import Base


class UpdateHistory(Base):
    """Audit trail of all container updates."""

    __tablename__ = "update_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(Integer, nullable=False, index=True)
    container_name = Column(String, nullable=False, index=True)
    update_id = Column(Integer, nullable=True, index=True)  # Reference to the update that triggered this

    # Update details
    from_tag = Column(String, nullable=False)
    to_tag = Column(String, nullable=False)
    update_type = Column(String, nullable=True)  # auto, manual, security, rollback
    backup_path = Column(String, nullable=True)  # Path to backup compose file

    # Execution details
    status = Column(String, nullable=False, index=True)  # success, failed, rolled_back - indexed for filtering
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Context
    reason = Column(Text, nullable=True)  # Legacy reason text
    reason_type = Column(
        String,
        nullable=False,
        default="unknown",
        server_default="unknown",
    )  # security, feature, bugfix, maintenance
    reason_summary = Column(Text, nullable=True)  # Snapshot of reason text for display
    triggered_by = Column(String, default="system")  # system, user, scheduler
    cves_fixed = Column(JSON, default=lambda: [], server_default='[]')

    # Rollback support
    can_rollback = Column(Boolean, default=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)

    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Indexed for date filtering
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Indexed for sorting/ordering

    def __repr__(self):
        return f"<UpdateHistory({self.container_name}: {self.from_tag} → {self.to_tag}, {self.status})>"
