"""Pydantic schemas for containers."""

from datetime import datetime
from typing import Optional, List, Dict
import json

from pydantic import BaseModel, Field, field_validator
from app.schemas.dependency import (
    DockerfileDependencySchema,
    AppDependencySchema,
    HttpServerSchema as HttpServerSchemaFromDependency,
)


class ContainerSchema(BaseModel):
    """Container response schema."""

    id: int
    name: str
    image: str
    current_tag: str
    current_digest: Optional[str] = None
    registry: str
    compose_file: str
    service_name: str
    policy: str
    scope: str
    include_prereleases: bool
    vulnforge_enabled: bool
    current_vuln_count: int
    is_my_project: bool = False
    update_available: bool
    latest_tag: Optional[str] = None
    latest_major_tag: Optional[str] = None
    last_checked: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    health_check_url: Optional[str] = None
    health_check_method: str = "auto"
    health_check_has_auth: bool = False
    release_source: Optional[str] = None
    auto_restart_enabled: bool = False
    restart_policy: str = "manual"
    restart_max_attempts: int = 10
    restart_backoff_strategy: str = "exponential"
    restart_success_window: int = 300
    update_window: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    dependents: List[str] = Field(default_factory=list)
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
    event_type: Optional[str] = (
        None  # 'update', 'dependency_ignore', 'dependency_unignore'
    )
    update_type: Optional[str] = None
    reason: Optional[str] = None
    reason_type: Optional[str] = None
    reason_summary: Optional[str] = None
    triggered_by: str
    can_rollback: bool
    backup_path: Optional[str] = None
    error_message: Optional[str] = None
    cves_fixed: List[str] = Field(default_factory=list)
    duration_seconds: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None

    # Dependency-specific fields (present for dependency ignore/unignore events)
    dependency_type: Optional[str] = (
        None  # 'dockerfile', 'http_server', 'app_dependency'
    )
    dependency_id: Optional[int] = None
    dependency_name: Optional[str] = None

    model_config = {"from_attributes": True}


class UpdateInfoSchema(BaseModel):
    """Available update information."""

    id: int
    from_tag: str
    to_tag: str
    status: str
    reason_type: str
    reason_summary: Optional[str] = None
    recommendation: Optional[str] = None
    changelog_url: Optional[str] = None
    cves_fixed: List[str] = Field(default_factory=list)
    current_vulns: int
    new_vulns: int
    vuln_delta: int
    published_date: Optional[datetime] = None
    image_size_delta: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ContainerDetailsSchema(BaseModel):
    """Comprehensive container details with history and updates."""

    container: ContainerSchema
    current_update: Optional[UpdateInfoSchema] = None
    history: List[HistoryItemSchema] = Field(default_factory=list)
    health_status: Optional[str] = None
    last_health_check: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ContainerUpdate(BaseModel):
    """Container update request."""

    policy: Optional[str] = None  # auto, manual, disabled, security
    scope: Optional[str] = None  # patch, minor, major
    include_prereleases: Optional[bool] = (
        None  # Include nightly, dev, alpha, beta, rc tags
    )
    vulnforge_enabled: Optional[bool] = None
    health_check_url: Optional[str] = None
    health_check_method: Optional[str] = None
    health_check_auth: Optional[str] = Field(default=None, repr=False)
    release_source: Optional[str] = None
    is_my_project: Optional[bool] = None


class PolicyUpdate(BaseModel):
    """Policy update request."""

    policy: str  # auto, manual, disabled, security


class UpdateWindowUpdate(BaseModel):
    """Update window update request."""

    update_window: Optional[str] = None


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

    dependencies: List[AppDependencySchema] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    with_security_issues: int = 0
    last_scan: Optional[datetime] = None
    scan_status: str = "idle"  # idle, scanning, error


class DockerfileDependenciesResponse(BaseModel):
    """Response containing all Dockerfile dependencies for a container."""

    dependencies: List[DockerfileDependencySchema] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    last_scan: Optional[datetime] = None
    scan_status: str = "idle"  # idle, scanning, error


class HttpServersResponse(BaseModel):
    """Response containing all HTTP servers detected in a container."""

    servers: List[HttpServerSchemaFromDependency] = Field(default_factory=list)
    total: int = 0
    with_updates: int = 0
    last_scan: Optional[datetime] = None
    scan_status: str = "idle"  # idle, scanning, error
