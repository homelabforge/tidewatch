"""SQLAlchemy model mixins for shared column groups."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class RestartConfigMixin:
    """Mixin for intelligent restart configuration columns.

    Used by Container model to group restart-related fields.
    """

    auto_restart_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    restart_policy: Mapped[str] = mapped_column(
        String, default="manual"
    )  # manual, on-failure, always, unless-stopped
    restart_max_attempts: Mapped[int] = mapped_column(Integer, default=10)
    restart_backoff_strategy: Mapped[str] = mapped_column(
        String, default="exponential"
    )  # exponential, linear, fixed
    restart_success_window: Mapped[int] = mapped_column(Integer, default=300)  # Seconds (5 minutes)


class UpdatePolicyMixin:
    """Mixin for update policy configuration columns.

    Used by Container model to group update-policy-related fields.
    """

    policy: Mapped[str] = mapped_column(
        String, default="monitor", index=True
    )  # auto, monitor, disabled
    scope: Mapped[str] = mapped_column(String, default="patch")  # patch, minor, major
    include_prereleases: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )  # None=inherit global
    version_track: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # None=auto-detect, "semver", "calver"
    update_window: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Format: "HH:MM-HH:MM" or "Days:HH:MM-HH:MM"


class IgnoreFieldsMixin:
    """Mixin for dependency ignore tracking columns.

    Used by DockerfileDependency, HttpServer, and AppDependency models.
    Eliminates duplication of the 6 identical ignore fields across 3 models.
    """

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
