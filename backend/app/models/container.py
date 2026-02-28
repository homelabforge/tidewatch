"""Container model for tracking Docker containers."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Container(Base):
    """Docker container tracked by TideWatch."""

    __tablename__ = "containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    image: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "lscr.io/linuxserver/plex"
    current_tag: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "1.40.0.8395"
    current_digest: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g., "sha256:abc123..." for digest tracking
    registry: Mapped[str] = mapped_column(String, nullable=False)  # docker.io, ghcr.io, lscr.io

    # Compose file information
    compose_file: Mapped[str] = mapped_column(String, nullable=False)  # Path to compose file
    service_name: Mapped[str] = mapped_column(String, nullable=False)  # Service name in compose
    compose_project: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Docker Compose project name

    # Update policy (from labels or UI)
    policy: Mapped[str] = mapped_column(
        String, default="monitor", index=True
    )  # auto, monitor, disabled - indexed for filtering
    scope: Mapped[str] = mapped_column(String, default="patch")  # patch, minor, major
    include_prereleases: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )  # None=inherit global, True=include prereleases, False=stable only
    version_track: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # None=auto-detect, "semver"=force SemVer, "calver"=force CalVer

    # VulnForge integration
    vulnforge_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    current_vuln_count: Mapped[int] = mapped_column(Integer, default=0)

    # My Projects feature
    is_my_project: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Status
    update_available: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )  # Indexed for filtering updates
    latest_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_major_tag: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Major version update (if exists outside scope)
    calver_blocked_tag: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Best CalVer candidate blocked for SemVer container (UI badge)
    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )  # Indexed for sorting
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # Docker labels from compose
    health_check_url: Mapped[str | None] = mapped_column(String, nullable=True)
    health_check_method: Mapped[str] = mapped_column(
        String, nullable=False, default="auto", server_default="auto"
    )  # auto, http, docker
    health_check_auth: Mapped[str | None] = mapped_column(String, nullable=True)
    release_source: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g., github:owner/repo or https://changelog

    # Intelligent restart configuration
    auto_restart_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    restart_policy: Mapped[str] = mapped_column(
        String, default="manual"
    )  # manual, on-failure, always, unless-stopped
    restart_max_attempts: Mapped[int] = mapped_column(Integer, default=10)
    restart_backoff_strategy: Mapped[str] = mapped_column(
        String, default="exponential"
    )  # exponential, linear, fixed
    restart_success_window: Mapped[int] = mapped_column(Integer, default=300)  # Seconds (5 minutes)

    # Update window configuration (time-based restrictions)
    update_window: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Format: "HH:MM-HH:MM" or "Days:HH:MM-HH:MM"

    # Dependency tracking for ordered updates
    dependencies: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # JSON array of container names this depends on
    dependents: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # JSON array of container names that depend on this

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Container(name={self.name}, image={self.image}:{self.current_tag})>"
