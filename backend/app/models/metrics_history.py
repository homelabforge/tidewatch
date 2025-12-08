"""Metrics history model for storing container resource metrics over time."""

from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.db import Base


class MetricsHistory(Base):
    """Historical metrics data for containers."""

    __tablename__ = "metrics_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(Integer, ForeignKey("containers.id", ondelete="CASCADE"), nullable=False, index=True)

    # Timestamp for this metrics snapshot
    collected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    # Resource metrics
    cpu_percent = Column(Float, nullable=False)
    memory_usage = Column(Integer, nullable=False)  # bytes
    memory_limit = Column(Integer, nullable=False)  # bytes
    memory_percent = Column(Float, nullable=False)
    network_rx = Column(Integer, nullable=False)  # bytes
    network_tx = Column(Integer, nullable=False)  # bytes
    block_read = Column(Integer, nullable=False)  # bytes
    block_write = Column(Integer, nullable=False)  # bytes
    pids = Column(Integer, nullable=False)

    # Composite index for efficient queries (container + time range)
    __table_args__ = (
        Index('idx_container_collected', 'container_id', 'collected_at'),
    )
