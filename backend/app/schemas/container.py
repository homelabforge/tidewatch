"""Pydantic schemas for containers."""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.dependency import (
    AppDependencySchema,
    DockerfileDependencySchema,
)
from app.schemas.dependency import (
    HttpServerSchema as HttpServerSchemaFromDependency,
)

# Valid update policy values
VALID_POLICIES = {
    "auto",
    "monitor",
    "disabled",
}


class ContainerSchema(BaseModel):
    """Container response schema."""

    id: int
    name: str
    image: str
    current_tag: str
    current_digest: str | None = None
    registry: str
    compose_file: str
    service_name: str
    policy: str
    scope: str
    include_prereleases: bool | None = None
    vulnforge_enabled: bool
    current_vuln_count: int
    is_my_project: bool = False
    update_available: bool
    latest_tag: str | None = None
    latest_major_tag: str | None = None
    calver_blocked_tag: str | None = None
    version_track: str | None = None
    last_checked: datetime | None = None
    last_updated: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    health_check_url: str | None = None
    health_check_method: str = "auto"
    health_check_has_auth: bool = False
    release_source: str | None = None
    auto_restart_enabled: bool = False
    restart_policy: str = "manual"
    restart_max_attempts: int = 10
    restart_backoff_strategy: str = "exponential"
    restart_success_window: int = 300
    update_window: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("dependencies", mode="before")
    @classmethod
    def parse_dependencies(cls, v):
        """Parse dependencies from JSON string or return as-is if already a list."""
        if isinstance(v, str):
            try:
                return json.loads(v) if v else []
            except json.JSONDecodeError:
                return []
        return v if v is not None else []

    @field_validator("dependents", mode="before")
    @classmethod
    def parse_dependents(cls, v):
        """Parse dependents from JSON string or return as-is if already a list."""
        if isinstance(v, str):
            try:
                return json.loads(v) if v else []
            except json.JSONDecodeError:
                return []
        return v if v is not None else []


class HistoryItemSchema(BaseModel):
    """History item for timeline."""

    id: int
    container_id: int
    from_tag: str
    to_tag: str
    status: str
    event_type: str | None = None  # 'update', 'dependency_ignore', 'dependency_unignore'
    update_type: str | None = None
    reason: str | None = None
    reason_type: str | None = None
    reason_summary: str | None = None
    triggered_by: str
    can_rollback: bool
    backup_path: str | None = None
    error_message: str | None = None
    cves_fixed: list[str] = Field(default_factory=list)
    duration_seconds: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    rolled_back_at: datetime | None = None

    # Dependency-specific fields (present for dependency ignore/unignore events)
    dependency_type: str | None = None  # 'dockerfile', 'http_server', 'app_dependency'
    dependency_id: int | None = None
    dependency_name: str | None = None

    model_config = {"from_attributes": True}


class UpdateInfoSchema(BaseModel):
    """Available update information."""

    id: int
    from_tag: str
    to_tag: str
    status: str
    reason_type: str
    reason_summary: str | None = None
    recommendation: str | None = None
    changelog_url: str | None = None
    cves_fixed: list[str] = Field(default_factory=list)
    current_vulns: int
    new_vulns: int
    vuln_delta: int
    published_date: datetime | None = None
    image_size_delta: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ContainerDetailsSchema(BaseModel):
    """Comprehensive container details with history and updates."""

    container: ContainerSchema
    current_update: UpdateInfoSchema | None = None
    history: list[HistoryItemSchema] = Field(default_factory=list)
    health_status: str | None = None
    last_health_check: datetime | None = None

    model_config = {"from_attributes": True}


class ContainerUpdate(BaseModel):
    """Container update request."""

    policy: str | None = None  # patch-only, minor-and-patch, auto, security, manual, disabled
    scope: str | None = None  # patch, minor, major
    include_prereleases: bool | None = None  # Include nightly, dev, alpha, beta, rc tags
    version_track: Literal["semver", "calver"] | None = None  # None=auto, "semver", "calver"
    vulnforge_enabled: bool | None = None
    health_check_url: str | None = None
    health_check_method: str | None = None
    health_check_auth: str | None = Field(default=None, repr=False)
    release_source: str | None = None
    is_my_project: bool | None = None

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, v: str | None) -> str | None:
        """Validate policy is a known value."""
        if v is not None and v not in VALID_POLICIES:
            raise ValueError(
                f"Invalid policy '{v}'. Must be one of: {', '.join(sorted(VALID_POLICIES))}"
            )
        return v


class PolicyUpdate(BaseModel):
    """Policy update request."""

    policy: str  # patch-only, minor-and-patch, auto, security, manual, disabled

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, v: str) -> str:
        """Validate policy is a known value."""
        if v not in VALID_POLICIES:
            raise ValueError(
                f"Invalid policy '{v}'. Must be one of: {', '.join(sorted(VALID_POLICIES))}"
            )
        return v


class UpdateWindowUpdate(BaseModel):
    """Update window update request."""

    update_window: str | None = None


class ContainerSummary(BaseModel):
    """Container summary for dashboard."""

    total_containers: int
    updates_available: int
    auto_update_count: int
    manual_approval_count: int
    disabled_count: int
    security_policy_count: int


class AppDependenciesResponse(BaseModel):
    """Response containing all application dependencies for a container."""

    dependencies: list[AppDependencySchema] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    with_security_issues: int = 0
    last_scan: datetime | None = None
    scan_status: str = "idle"  # idle, scanning, error


class DockerfileDependenciesResponse(BaseModel):
    """Response containing all Dockerfile dependencies for a container."""

    dependencies: list[DockerfileDependencySchema] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    last_scan: datetime | None = None
    scan_status: str = "idle"  # idle, scanning, error


class HttpServersResponse(BaseModel):
    """Response containing all HTTP servers detected in a container."""

    servers: list[HttpServerSchemaFromDependency] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    last_scan: datetime | None = None
    scan_status: str = "idle"  # idle, scanning, error
