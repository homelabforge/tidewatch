"""HTTP server model for tracking web servers running in containers."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class HttpServer(Base):
    """HTTP servers detected in containers."""

    __tablename__ = "http_servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Server details
    name = Column(
        String, nullable=False, index=True
    )  # nginx, apache, caddy, granian, etc.
    current_version = Column(String, nullable=True)  # Current version detected
    latest_version = Column(String, nullable=True)  # Latest version available
    update_available = Column(Boolean, default=False, index=True)
    severity = Column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info
    detection_method = Column(
        String, nullable=False
    )  # labels, process, version_command, container_config

    # Dockerfile context (if detected from Dockerfile)
    dockerfile_path = Column(
        String, nullable=True
    )  # Path to Dockerfile containing the server
    line_number = Column(Integer, nullable=True)  # Line number in Dockerfile

    # Ignore tracking (version-specific)
    ignored = Column(Boolean, default=False, index=True)
    ignored_version = Column(
        String, nullable=True
    )  # Which version transition was ignored (e.g., "2.6.0")
    ignored_version_prefix = Column(
        String(50), nullable=True
    )  # Major.minor prefix for pattern matching (e.g., "2.6" ignores all 2.6.x)
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
        return f"<HttpServer(container_id={self.container_id}, name={self.name}, version={self.current_version})>"
