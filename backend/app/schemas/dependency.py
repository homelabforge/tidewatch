"""Pydantic schemas for dependencies (HTTP servers, app dependencies, Dockerfile dependencies)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HttpServerSchema(BaseModel):
    """HTTP server response schema."""

    id: Optional[int] = None  # None for scanned-only servers
    container_id: Optional[int] = None  # None for scanned-only servers
    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    update_available: bool
    severity: str = "info"
    detection_method: str
    dockerfile_path: Optional[str] = None
    line_number: Optional[int] = None
    ignored: bool = False
    ignored_version: Optional[str] = None
    ignored_by: Optional[str] = None
    ignored_at: Optional[datetime] = None
    ignored_reason: Optional[str] = None
    last_checked: Optional[datetime] = None
    created_at: Optional[datetime] = None  # None for scanned-only servers
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AppDependencySchema(BaseModel):
    """Application dependency response schema (npm, pypi, etc.)."""

    id: int
    container_id: int
    name: str
    ecosystem: str
    current_version: str
    latest_version: Optional[str] = None
    update_available: bool
    dependency_type: str = "production"
    security_advisories: int = 0
    socket_score: Optional[float] = None
    severity: str = "info"
    manifest_file: str
    ignored: bool = False
    ignored_version: Optional[str] = None
    ignored_by: Optional[str] = None
    ignored_at: Optional[datetime] = None
    ignored_reason: Optional[str] = None
    last_checked: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

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
    latest_tag: Optional[str] = None
    update_available: bool
    severity: str = "info"
    last_checked: Optional[datetime] = None
    dockerfile_path: str
    line_number: Optional[int] = None
    stage_name: Optional[str] = None
    ignored: bool = False
    ignored_version: Optional[str] = None
    ignored_by: Optional[str] = None
    ignored_at: Optional[datetime] = None
    ignored_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Request schemas for ignore/unignore actions
class IgnoreRequest(BaseModel):
    """Request to ignore a dependency update."""

    reason: Optional[str] = None


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
    line_number: Optional[int] = None
    current_version: str
    new_version: str
    changelog: Optional[str] = None
    changelog_url: Optional[str] = None


class UpdateResponse(BaseModel):
    """Response for dependency update."""

    success: bool
    backup_path: Optional[str] = None
    history_id: Optional[int] = None
    changes_made: Optional[str] = None
    error: Optional[str] = None
