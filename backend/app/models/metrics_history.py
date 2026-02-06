"""Metrics history model for storing container resource metrics over time."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class MetricsHistory(Base):
    """Historical metrics data for containers."""

    __tablename__ = "metrics_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("containers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Timestamp for this metrics snapshot
    collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Resource metrics
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    memory_limit: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    memory_percent: Mapped[float] = mapped_column(Float, nullable=False)
    network_rx: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    network_tx: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    block_read: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    block_write: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    pids: Mapped[int] = mapped_column(Integer, nullable=False)

    # Composite index for efficient queries (container + time range)
    __table_args__ = (Index("idx_container_collected", "container_id", "collected_at"),)
