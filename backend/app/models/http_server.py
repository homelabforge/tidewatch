"""HTTP server model for tracking web servers running in containers."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class HttpServer(Base):
    """HTTP servers detected in containers."""

    __tablename__ = "http_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("containers.id"), nullable=False, index=True
    )

    # Relationship to Container
    container = relationship("Container", backref="http_servers")

    # Server details
    name: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # nginx, apache, caddy, granian, etc.
    current_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Current version detected
    latest_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Latest version available
    update_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    severity: Mapped[str] = mapped_column(
        String, nullable=False, default="info"
    )  # critical, high, medium, low, info
    detection_method: Mapped[str] = mapped_column(
        String, nullable=False
    )  # labels, process, version_command, container_config

    # Dockerfile context (if detected from Dockerfile)
    dockerfile_path: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Path to Dockerfile containing the server
    line_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Line number in Dockerfile

    # Ignore tracking (version-specific)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ignored_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Which version transition was ignored (e.g., "2.6.0")
    ignored_version_prefix: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Major.minor prefix for pattern matching (e.g., "2.6" ignores all 2.6.x)
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
        return f"<HttpServer(container_id={self.container_id}, name={self.name}, version={self.current_version})>"
