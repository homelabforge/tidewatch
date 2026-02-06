"""Update model for tracking available updates."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Update(Base):
    """Available container update with reasoning."""

    __tablename__ = "updates"
    __table_args__ = (
        # Prevent duplicate updates for same container/version/status combination
        # This helps prevent race conditions during concurrent update checks
        Index("idx_update_lookup", "container_id", "from_tag", "to_tag", "status"),
        # Note: We use a unique index on all statuses since SQLite doesn't support
        # partial unique constraints. The application handles this by cleaning up
        # old updates when status changes to 'applied' or 'rejected'.
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    container_name: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Version information
    from_tag: Mapped[str] = mapped_column(String, nullable=False)
    to_tag: Mapped[str] = mapped_column(String, nullable=False)
    registry: Mapped[str] = mapped_column(String, nullable=False)

    # Update reasoning
    reason_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # security, feature, bugfix, maintenance
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # Short description
    recommendation: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # "Highly recommended", "Optional", "Review required"
    changelog: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Full changelog if available
    changelog_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Security information (from VulnForge)
    cves_fixed: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )  # List of CVE IDs fixed
    current_vulns: Mapped[int] = mapped_column(Integer, default=0)
    new_vulns: Mapped[int] = mapped_column(Integer, default=0)
    vuln_delta: Mapped[int] = mapped_column(Integer, default=0)  # Negative = improvement

    # Metadata
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image_size_delta: Mapped[int] = mapped_column(Integer, default=0)  # Bytes difference

    # Status
    status: Mapped[str] = mapped_column(
        String, default="pending", index=True
    )  # pending, approved, rejected, applied, pending_retry - indexed for filtering
    scope_violation: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # 1 if major update blocked by scope, 0 otherwise
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Retry logic fields
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    backoff_multiplier: Mapped[int] = mapped_column(Integer, default=3)

    # Snooze/dismiss support
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optimistic locking for concurrent update safety
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Decision traceability (Migration 035)
    decision_trace: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON string with trace data
    update_kind: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )  # "tag" or "digest"
    change_type: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )  # "major", "minor", "patch"

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Update({self.container_name}: {self.from_tag} → {self.to_tag})>"
