"""Application dependency model for tracking npm, pypi, and other package dependencies."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class AppDependency(Base):
    """Application-level dependencies (npm, pypi, composer, cargo, go)."""

    __tablename__ = "app_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Relationship to Container
    container = relationship("Container", backref="app_dependencies")

    # Dependency details
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)  # Package name
    ecosystem: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # npm, pypi, composer, cargo, go
    current_version: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Currently installed version
    latest_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Latest version available
    update_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dependency_type: Mapped[str] = mapped_column(
        String, nullable=False, default="production"
    )  # production, development, optional, peer

    # Security and quality
    security_advisories: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Number of security advisories
    socket_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # Socket.dev supply chain score (0-100)
    severity: Mapped[str] = mapped_column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info

    # File location
    manifest_file: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Path to package.json, requirements.txt, etc.

    # Ignore tracking (version-specific)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ignored_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Which version transition was ignored
    ignored_version_prefix: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Major.minor prefix for pattern matching (e.g., "3.15" ignores all 3.15.x)
    ignored_by: Mapped[str | None] = mapped_column(String, nullable=True)  # Who ignored the update
    ignored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # When it was ignored
    ignored_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Optional reason for ignoring

    # Metadata
    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Optimistic locking
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def __repr__(self) -> str:
        return f"<AppDependency(container_id={self.container_id}, name={self.name}, ecosystem={self.ecosystem}, version={self.current_version})>"
