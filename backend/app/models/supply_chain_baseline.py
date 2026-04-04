"""Supply chain baseline model for tracking trusted image states."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class SupplyChainBaseline(Base):
    """Trusted baseline for an image, keyed by (registry, image, version_track)."""

    __tablename__ = "supply_chain_baselines"
    __table_args__ = (
        UniqueConstraint(
            "registry", "image", "version_track", name="uq_baseline_registry_image_track"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registry: Mapped[str] = mapped_column(String, nullable=False)
    image: Mapped[str] = mapped_column(String, nullable=False)
    version_track: Mapped[str | None] = mapped_column(String, nullable=True)
    last_trusted_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    last_trusted_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    last_trusted_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SupplyChainBaseline({self.registry}/{self.image}:{self.version_track})>"
