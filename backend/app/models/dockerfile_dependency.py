"""Dockerfile dependency model for tracking base images and other Docker dependencies."""

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base


class DockerfileDependency(Base):
    """Dockerfile dependencies tracked by TideWatch."""

    __tablename__ = "dockerfile_dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Dependency details
    dependency_type = Column(
        String, nullable=False, index=True
    )  # base_image, build_arg, runtime_image
    image_name = Column(String, nullable=False)  # e.g., "node", "python", "nginx"
    current_tag = Column(String, nullable=False)  # e.g., "22-alpine", "3.14-slim"
    registry = Column(
        String, nullable=False, default="docker.io"
    )  # docker.io, ghcr.io, etc.

    # Full image reference
    full_image = Column(
        String, nullable=False
    )  # e.g., "node:22-alpine", "python:3.14-slim"

    # Update tracking
    latest_tag = Column(String, nullable=True)  # Latest available tag
    update_available = Column(Boolean, default=False, index=True)
    severity = Column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info
    last_checked = Column(DateTime(timezone=True), nullable=True, index=True)

    # Dockerfile context
    dockerfile_path = Column(String, nullable=False)  # Relative path to Dockerfile
    line_number = Column(
        Integer, nullable=True
    )  # Line number in Dockerfile where dependency is defined
    stage_name = Column(
        String, nullable=True
    )  # Multi-stage build stage name (e.g., "frontend-builder")

    # Ignore tracking (version-specific)
    ignored = Column(Boolean, default=False, index=True)
    ignored_version = Column(
        String, nullable=True
    )  # Which version transition was ignored
    ignored_by = Column(String, nullable=True)  # Who ignored the update
    ignored_at = Column(DateTime(timezone=True), nullable=True)  # When it was ignored
    ignored_reason = Column(Text, nullable=True)  # Optional reason for ignoring

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Optimistic locking
    version = Column(Integer, default=1, nullable=False)

    def __repr__(self):
        return f"<DockerfileDependency(container_id={self.container_id}, image={self.full_image}, type={self.dependency_type})>"
