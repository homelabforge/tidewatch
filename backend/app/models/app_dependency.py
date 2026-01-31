"""Application dependency model for tracking npm, pypi, and other package dependencies."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AppDependency(Base):
    """Application-level dependencies (npm, pypi, composer, cargo, go)."""

    __tablename__ = "app_dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Relationship to Container
    container = relationship("Container", backref="app_dependencies")

    # Dependency details
    name = Column(String, nullable=False, index=True)  # Package name
    ecosystem = Column(
        String, nullable=False, index=True
    )  # npm, pypi, composer, cargo, go
    current_version = Column(String, nullable=False)  # Currently installed version
    latest_version = Column(String, nullable=True)  # Latest version available
    update_available = Column(Boolean, default=False, index=True)
    dependency_type = Column(
        String, nullable=False, default="production"
    )  # production, development, optional, peer

    # Security and quality
    security_advisories = Column(Integer, default=0)  # Number of security advisories
    socket_score = Column(Float, nullable=True)  # Socket.dev supply chain score (0-100)
    severity = Column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info

    # File location
    manifest_file = Column(
        String, nullable=False
    )  # Path to package.json, requirements.txt, etc.

    # Ignore tracking (version-specific)
    ignored = Column(Boolean, default=False, index=True)
    ignored_version = Column(
        String, nullable=True
    )  # Which version transition was ignored
    ignored_version_prefix = Column(
        String(50), nullable=True
    )  # Major.minor prefix for pattern matching (e.g., "3.15" ignores all 3.15.x)
    ignored_by = Column(String, nullable=True)  # Who ignored the update
    ignored_at = Column(DateTime(timezone=True), nullable=True)  # When it was ignored
    ignored_reason = Column(Text, nullable=True)  # Optional reason for ignoring

    # Metadata
    last_checked = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Optimistic locking
    version = Column(Integer, default=1, nullable=False)

    def __repr__(self):
        return f"<AppDependency(container_id={self.container_id}, name={self.name}, ecosystem={self.ecosystem}, version={self.current_version})>"
