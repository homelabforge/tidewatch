"""Dockerfile dependency model for tracking base images and other Docker dependencies."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class DockerfileDependency(Base):
    """Dockerfile dependencies tracked by TideWatch."""

    __tablename__ = "dockerfile_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Relationship to Container
    container = relationship("Container", backref="dockerfile_dependencies")

    # Dependency details
    dependency_type: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # base_image, build_arg, runtime_image
    image_name: Mapped[str] = mapped_column(
        String, nullable=False
    )  # e.g., "node", "python", "nginx"
    current_tag: Mapped[str] = mapped_column(
        String, nullable=False
    )  # e.g., "22-alpine", "3.14-slim"
    registry: Mapped[str] = mapped_column(
        String, nullable=False, default="docker.io"
    )  # docker.io, ghcr.io, etc.

    # Full image reference
    full_image: Mapped[str] = mapped_column(
        String, nullable=False
    )  # e.g., "node:22-alpine", "python:3.14-slim"

    # Update tracking
    latest_tag: Mapped[str | None] = mapped_column(String, nullable=True)  # Latest available tag
    update_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    severity: Mapped[str] = mapped_column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info
    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Dockerfile context
    dockerfile_path: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Relative path to Dockerfile
    line_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Line number in Dockerfile where dependency is defined
    stage_name: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Multi-stage build stage name (e.g., "frontend-builder")

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
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Optimistic locking
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def __repr__(self) -> str:
        return f"<DockerfileDependency(container_id={self.container_id}, image={self.full_image}, type={self.dependency_type})>"
