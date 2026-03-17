"""Service for dependency ignore/unignore operations.

Eliminates duplication across DockerfileDependency, HttpServer, and AppDependency
route handlers by providing a single ignore/unignore implementation.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.container import Container
from app.models.history import UpdateHistory
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


def extract_version_prefix(tag: str | None) -> str | None:
    """Extract major.minor version prefix from a tag.

    Examples:
        "3.15.0a5-slim" -> "3.15"
        "22-alpine" -> "22"
        "1.2.3" -> "1.2"
        "latest" -> None

    Args:
        tag: Version tag string

    Returns:
        Major.minor prefix or None if cannot be parsed
    """
    if not tag:
        return None

    match = re.match(r"^(\d+)(?:\.(\d+))?", tag)
    if match:
        major = match.group(1)
        minor = match.group(2)
        if minor:
            return f"{major}.{minor}"
        return major
    return None


@dataclass(frozen=True)
class DependencyTypeConfig:
    """Configuration for a dependency type's model-specific field mappings."""

    dependency_type: str  # "dockerfile", "http_server", "app_dependency"
    entity_label: str  # Human-readable label for messages
    latest_version_attr: str  # Attribute name for the latest version
    current_version_attr: str  # Attribute name for the current version
    name_attr: str  # Attribute name for the dependency name
    file_path_attr: str  # Attribute name for the file path


# Pre-built configs for each dependency type
DOCKERFILE_CONFIG = DependencyTypeConfig(
    dependency_type="dockerfile",
    entity_label="Dockerfile dependency",
    latest_version_attr="latest_tag",
    current_version_attr="current_tag",
    name_attr="image_name",
    file_path_attr="dockerfile_path",
)

HTTP_SERVER_CONFIG = DependencyTypeConfig(
    dependency_type="http_server",
    entity_label="HTTP server",
    latest_version_attr="latest_version",
    current_version_attr="current_version",
    name_attr="name",
    file_path_attr="dockerfile_path",
)

APP_DEPENDENCY_CONFIG = DependencyTypeConfig(
    dependency_type="app_dependency",
    entity_label="app dependency",
    latest_version_attr="latest_version",
    current_version_attr="current_version",
    name_attr="name",
    file_path_attr="manifest_file",
)


class DependencyIgnoreService:
    """Service for ignoring/unignoring dependency updates."""

    @staticmethod
    async def ignore(
        db: AsyncSession,
        model_class: type,
        dependency_id: int,
        reason: str | None,
        config: DependencyTypeConfig,
    ) -> dict[str, Any]:
        """Ignore a dependency update.

        Args:
            db: Database session
            model_class: SQLAlchemy model class
            dependency_id: ID of the dependency to ignore
            reason: Optional reason for ignoring
            config: Type-specific field mapping configuration

        Returns:
            Success dict with message

        Raises:
            HTTPException: 404 if not found, 400 if already ignored
        """
        from fastapi import HTTPException

        try:
            # Get dependency with container relationship loaded
            result = await db.execute(
                select(model_class)
                .where(model_class.id == dependency_id)
                .options(selectinload(model_class.container))
            )
            dependency = result.scalar_one_or_none()

            if not dependency:
                raise HTTPException(
                    status_code=404, detail=f"{config.entity_label.capitalize()} not found"
                )

            if dependency.ignored:
                raise HTTPException(
                    status_code=400,
                    detail=f"{config.entity_label.capitalize()} is already ignored",
                )

            latest_version = getattr(dependency, config.latest_version_attr)
            current_version = getattr(dependency, config.current_version_attr)
            dep_name = getattr(dependency, config.name_attr)
            file_path = getattr(dependency, config.file_path_attr)

            # Set ignore fields
            dependency.ignored = True
            dependency.ignored_version = latest_version
            dependency.ignored_version_prefix = extract_version_prefix(latest_version)
            dependency.ignored_by = "user"
            dependency.ignored_at = datetime.now(UTC)
            dependency.ignored_reason = reason

            # Get container name from relationship
            container_name = dependency.container.name if dependency.container else "Unknown"

            # Create history entry
            history = UpdateHistory(
                container_id=dependency.container_id,
                container_name=container_name,
                update_id=None,
                from_tag=current_version,
                to_tag=latest_version or current_version,
                update_type="manual",
                status="success",
                event_type="dependency_ignore",
                dependency_type=config.dependency_type,
                dependency_id=dependency.id,
                dependency_name=dep_name,
                file_path=file_path,
                reason=reason or "User ignored update",
                triggered_by="user",
            )
            db.add(history)

            await db.commit()

            logger.info(
                f"Ignored {config.entity_label} {dep_name} "
                f"(id={dependency_id}) for version {latest_version}"
            )

            return {
                "success": True,
                "message": f"{config.entity_label.capitalize()} ignored successfully",
            }

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(
                f"Error ignoring {config.entity_label} "
                f"{sanitize_log_message(str(dependency_id))}: "
                f"{sanitize_log_message(str(e))}"
            )
            raise HTTPException(status_code=500, detail=f"Failed to ignore {config.entity_label}")

    @staticmethod
    async def unignore(
        db: AsyncSession,
        model_class: type,
        dependency_id: int,
        config: DependencyTypeConfig,
    ) -> dict[str, Any]:
        """Unignore a dependency update.

        Args:
            db: Database session
            model_class: SQLAlchemy model class
            dependency_id: ID of the dependency to unignore
            config: Type-specific field mapping configuration

        Returns:
            Success dict with message

        Raises:
            HTTPException: 404 if not found, 400 if not ignored
        """
        from fastapi import HTTPException

        try:
            result = await db.execute(select(model_class).where(model_class.id == dependency_id))
            dependency = result.scalar_one_or_none()

            if not dependency:
                raise HTTPException(
                    status_code=404, detail=f"{config.entity_label.capitalize()} not found"
                )

            if not dependency.ignored:
                raise HTTPException(
                    status_code=400,
                    detail=f"{config.entity_label.capitalize()} is not ignored",
                )

            dep_name = getattr(dependency, config.name_attr)

            # Clear ignore fields
            dependency.ignored = False
            dependency.ignored_version = None
            dependency.ignored_version_prefix = None
            dependency.ignored_by = None
            dependency.ignored_at = None
            dependency.ignored_reason = None

            # Get container name
            container_result = await db.execute(
                select(Container).where(Container.id == dependency.container_id)
            )
            container = container_result.scalar_one_or_none()
            container_name = container.name if container else "Unknown"

            # Create history event for unignore
            history_event = UpdateHistory(
                container_id=dependency.container_id,
                container_name=container_name,
                from_tag="",
                to_tag="",
                update_type="manual",
                status="success",
                event_type="dependency_unignore",
                dependency_type=config.dependency_type,
                dependency_id=dependency.id,
                dependency_name=dep_name,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            db.add(history_event)

            await db.commit()

            logger.info(
                f"Unignored {config.entity_label} "
                f"{sanitize_log_message(str(dep_name))} "
                f"(id={sanitize_log_message(str(dependency_id))})"
            )

            return {
                "success": True,
                "message": f"{config.entity_label.capitalize()} unignored successfully",
            }

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(
                f"Error unignoring {config.entity_label} "
                f"{sanitize_log_message(str(dependency_id))}: "
                f"{sanitize_log_message(str(e))}"
            )
            raise HTTPException(status_code=500, detail=f"Failed to unignore {config.entity_label}")
