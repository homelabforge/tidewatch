"""Container model for tracking Docker containers."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.models.mixins import RestartConfigMixin, UpdatePolicyMixin


class Container(UpdatePolicyMixin, RestartConfigMixin, Base):
    """Docker container tracked by TideWatch."""

    __tablename__ = "containers"
    __table_args__ = (
        UniqueConstraint("service_name", "compose_file", name="uq_container_service_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)  # Display label only
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
    docker_name: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Actual Docker container name (e.g., "immich-redis-1")

    # Update policy fields are provided by UpdatePolicyMixin:
    # policy, scope, include_prereleases, version_track, update_window

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

    # Restart configuration fields are provided by RestartConfigMixin:
    # auto_restart_enabled, restart_policy, restart_max_attempts,
    # restart_backoff_strategy, restart_success_window

    # Dependency tracking for ordered updates (JSON arrays)
    dependencies: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )  # Container names this depends on
    dependents: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )  # Container names that depend on this

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def runtime_name(self) -> str:
        """Name for Docker CLI/SDK calls. Prefers docker_name, falls back to name."""
        return self.docker_name or self.name

    def __repr__(self) -> str:
        return f"<Container(name={self.name}, image={self.image}:{self.current_tag})>"
