"""Update model for tracking available updates."""

from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Index
from sqlalchemy.sql import func
from app.db import Base


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

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(Integer, nullable=False, index=True)
    container_name = Column(String, nullable=False, index=True)

    # Version information
    from_tag = Column(String, nullable=False)
    to_tag = Column(String, nullable=False)
    registry = Column(String, nullable=False)

    # Update reasoning
    reason_type = Column(
        String, nullable=False
    )  # security, feature, bugfix, maintenance
    reason_summary = Column(Text, nullable=True)  # Short description
    recommendation = Column(
        String, nullable=True
    )  # "Highly recommended", "Optional", "Review required"
    changelog = Column(Text, nullable=True)  # Full changelog if available
    changelog_url = Column(String, nullable=True)

    # Security information (from VulnForge)
    cves_fixed = Column(
        JSON, default=lambda: [], server_default="[]"
    )  # List of CVE IDs fixed
    current_vulns = Column(Integer, default=0)
    new_vulns = Column(Integer, default=0)
    vuln_delta = Column(Integer, default=0)  # Negative = improvement

    # Metadata
    published_date = Column(DateTime(timezone=True), nullable=True)
    image_size_delta = Column(Integer, default=0)  # Bytes difference

    # Status
    status = Column(
        String, default="pending", index=True
    )  # pending, approved, rejected, applied, pending_retry - indexed for filtering
    scope_violation = Column(
        Integer, default=0, nullable=False
    )  # 1 if major update blocked by scope, 0 otherwise
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_by = Column(String, nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Retry logic fields
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    backoff_multiplier = Column(Integer, default=3)

    # Snooze/dismiss support
    snoozed_until = Column(DateTime(timezone=True), nullable=True)

    # Optimistic locking for concurrent update safety
    version = Column(Integer, default=1, nullable=False)

    # Decision traceability (Migration 035)
    decision_trace = Column(Text, nullable=True)  # JSON string with trace data
    update_kind = Column(String, nullable=True, index=True)  # "tag" or "digest"
    change_type = Column(String, nullable=True, index=True)  # "major", "minor", "patch"

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Update({self.container_name}: {self.from_tag} → {self.to_tag})>"
