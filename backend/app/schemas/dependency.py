"""Pydantic schemas for dependencies (HTTP servers, app dependencies, Dockerfile dependencies)."""

from datetime import datetime

from pydantic import BaseModel


class HttpServerSchema(BaseModel):
    """HTTP server response schema."""

    id: int | None = None  # None for scanned-only servers
    container_id: int | None = None  # None for scanned-only servers
    name: str
    current_version: str | None = None
    latest_version: str | None = None
    update_available: bool
    severity: str = "info"
    detection_method: str
    dockerfile_path: str | None = None
    line_number: int | None = None
    manifest_file: str | None = None
    package_name: str | None = None
    ecosystem: str | None = None
    ignored: bool = False
    ignored_version: str | None = None
    ignored_by: str | None = None
    ignored_at: datetime | None = None
    ignored_reason: str | None = None
    last_checked: datetime | None = None
    created_at: datetime | None = None  # None for scanned-only servers
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AppDependencySchema(BaseModel):
    """Application dependency response schema (npm, pypi, etc.)."""

    id: int
    container_id: int
    name: str
    ecosystem: str
    current_version: str
    latest_version: str | None = None
    update_available: bool
    dependency_type: str = "production"
    security_advisories: int = 0
    socket_score: float | None = None
    severity: str = "info"
    manifest_file: str
    ignored: bool = False
    ignored_version: str | None = None
    ignored_by: str | None = None
    ignored_at: datetime | None = None
    ignored_reason: str | None = None
    last_checked: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DockerfileDependencySchema(BaseModel):
    """Dockerfile dependency response schema."""

    id: int
    container_id: int
    dependency_type: str
    image_name: str
    current_tag: str
    registry: str
    full_image: str
    latest_tag: str | None = None
    update_available: bool
    severity: str = "info"
    last_checked: datetime | None = None
    dockerfile_path: str
    line_number: int | None = None
    stage_name: str | None = None
    ignored: bool = False
    ignored_version: str | None = None
    ignored_by: str | None = None
    ignored_at: datetime | None = None
    ignored_reason: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# Request schemas for ignore/unignore actions
class IgnoreRequest(BaseModel):
    """Request to ignore a dependency update."""

    reason: str | None = None


class UnignoreRequest(BaseModel):
    """Request to unignore a dependency update."""

    pass  # No parameters needed


# Request schemas for file update actions
class UpdateRequest(BaseModel):
    """Request to update a dependency in its source file."""

    new_version: str


class PreviewResponse(BaseModel):
    """Response for update preview."""

    current_line: str
    new_line: str
    file_path: str
    line_number: int | None = None
    current_version: str
    new_version: str
    changelog: str | None = None
    changelog_url: str | None = None


class UpdateResponse(BaseModel):
    """Response for dependency update."""

    success: bool
    backup_path: str | None = None
    history_id: int | None = None
    changes_made: str | None = None
    error: str | None = None


# Batch update schemas
class BatchDependencyUpdateRequest(BaseModel):
    """Request for batch dependency update."""

    dependency_ids: list[int]


class BatchDependencyUpdateItem(BaseModel):
    """Single item result in batch dependency update."""

    id: int
    name: str
    from_version: str
    to_version: str
    success: bool
    error: str | None = None
    backup_path: str | None = None
    history_id: int | None = None


class BatchDependencyUpdateSummary(BaseModel):
    """Summary of batch dependency update operation."""

    total: int
    updated_count: int
    failed_count: int


class BatchDependencyUpdateResponse(BaseModel):
    """Response for batch dependency update."""

    updated: list[BatchDependencyUpdateItem]
    failed: list[BatchDependencyUpdateItem]
    summary: BatchDependencyUpdateSummary


# Rollback schemas
class RollbackHistoryItem(BaseModel):
    """A single historical version available for rollback."""

    history_id: int
    from_version: str  # Version BEFORE change (rollback target)
    to_version: str  # Version AFTER change
    updated_at: datetime
    triggered_by: str


class RollbackHistoryResponse(BaseModel):
    """Available rollback versions for a dependency."""

    dependency_id: int
    dependency_type: str  # 'dockerfile', 'http_server', 'app_dependency'
    dependency_name: str
    current_version: str
    rollback_options: list[RollbackHistoryItem]


class RollbackRequest(BaseModel):
    """Request to rollback to a specific version."""

    target_version: str


class RollbackResponse(BaseModel):
    """Rollback operation result."""

    success: bool
    history_id: int | None = None
    changes_made: str | None = None
    error: str | None = None
