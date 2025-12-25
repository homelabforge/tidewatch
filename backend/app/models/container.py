"""Container model for tracking Docker containers."""

from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON
from sqlalchemy.sql import func
from app.db import Base


class Container(Base):
    """Docker container tracked by TideWatch."""

    __tablename__ = "containers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)
    image = Column(String, nullable=False)  # e.g., "lscr.io/linuxserver/plex"
    current_tag = Column(String, nullable=False)  # e.g., "1.40.0.8395"
    current_digest = Column(
        String, nullable=True
    )  # e.g., "sha256:abc123..." for digest tracking
    registry = Column(String, nullable=False)  # docker.io, ghcr.io, lscr.io

    # Compose file information
    compose_file = Column(String, nullable=False)  # Path to compose file
    service_name = Column(String, nullable=False)  # Service name in compose

    # Update policy (from labels or UI)
    policy = Column(
        String, default="manual", index=True
    )  # auto, manual, disabled, security - indexed for filtering
    scope = Column(String, default="patch")  # patch, minor, major
    include_prereleases = Column(
        Boolean, default=False
    )  # Include nightly, dev, alpha, beta, rc tags

    # VulnForge integration
    vulnforge_enabled = Column(Boolean, default=True)
    current_vuln_count = Column(Integer, default=0)

    # My Projects feature
    is_my_project = Column(Boolean, default=False, index=True)

    # Status
    update_available = Column(
        Boolean, default=False, index=True
    )  # Indexed for filtering updates
    latest_tag = Column(String, nullable=True)
    latest_major_tag = Column(
        String, nullable=True
    )  # Major version update (if exists outside scope)
    last_checked = Column(
        DateTime(timezone=True), nullable=True, index=True
    )  # Indexed for sorting
    last_updated = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    labels = Column(JSON, default=dict)  # Docker labels from compose
    health_check_url = Column(String, nullable=True)
    health_check_method = Column(
        String, nullable=False, default="auto", server_default="auto"
    )  # auto, http, docker
    health_check_auth = Column(String, nullable=True)
    release_source = Column(
        String, nullable=True
    )  # e.g., github:owner/repo or https://changelog

    # Intelligent restart configuration
    auto_restart_enabled = Column(Boolean, default=False)
    restart_policy = Column(
        String, default="manual"
    )  # manual, on-failure, always, unless-stopped
    restart_max_attempts = Column(Integer, default=10)
    restart_backoff_strategy = Column(
        String, default="exponential"
    )  # exponential, linear, fixed
    restart_success_window = Column(Integer, default=300)  # Seconds (5 minutes)

    # Update window configuration (time-based restrictions)
    update_window = Column(
        String, nullable=True
    )  # Format: "HH:MM-HH:MM" or "Days:HH:MM-HH:MM"

    # Dependency tracking for ordered updates
    dependencies = Column(
        String, nullable=True
    )  # JSON array of container names this depends on
    dependents = Column(
        String, nullable=True
    )  # JSON array of container names that depend on this

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Container(name={self.name}, image={self.image}:{self.current_tag})>"
