"""API endpoints for dependency ignore/unignore operations."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.app_dependency import AppDependency
from app.models.container import Container
from app.models.dockerfile_dependency import DockerfileDependency
from app.models.history import UpdateHistory
from app.models.http_server import HttpServer
from app.schemas.dependency import (
    BatchDependencyUpdateItem,
    BatchDependencyUpdateRequest,
    BatchDependencyUpdateResponse,
    BatchDependencyUpdateSummary,
    IgnoreRequest,
    PreviewResponse,
    UpdateRequest,
    UpdateResponse,
)
from app.services.dependency_update_service import DependencyUpdateService
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dependencies", tags=["dependencies"])


# ===================================================================
# Dockerfile Dependency Endpoints
# ===================================================================


@router.post("/dockerfile/{dependency_id}/ignore")
async def ignore_dockerfile_dependency(
    dependency_id: int, request: IgnoreRequest, db: AsyncSession = Depends(get_db)
):
    """
    Ignore a Dockerfile dependency update.

    Marks the dependency as ignored for the current version transition.
    If a newer version is released later, the ignore will be automatically cleared.
    """
    try:
        # Get dependency
        result = await db.execute(
            select(DockerfileDependency).where(DockerfileDependency.id == dependency_id)
        )
        dependency = result.scalar_one_or_none()

        if not dependency:
            raise HTTPException(status_code=404, detail="Dependency not found")

        if dependency.ignored:
            raise HTTPException(status_code=400, detail="Dependency is already ignored")

        # Update dependency
        dependency.ignored = True
        dependency.ignored_version = dependency.latest_tag  # Track which version we're ignoring
        dependency.ignored_by = "user"  # TODO: Get from auth context when available
        dependency.ignored_at = datetime.now(UTC)
        dependency.ignored_reason = request.reason

        # Create history entry
        history = UpdateHistory(
            container_id=dependency.container_id,
            container_name="",  # Will be populated by trigger or additional query
            update_id=None,
            from_tag=dependency.current_tag,
            to_tag=dependency.latest_tag or dependency.current_tag,
            update_type="manual",
            status="success",
            event_type="dependency_ignore",
            dependency_type="dockerfile",
            dependency_id=dependency.id,
            dependency_name=dependency.image_name,
            file_path=dependency.dockerfile_path,
            reason=request.reason or "User ignored update",
            triggered_by="user",
        )
        db.add(history)

        await db.commit()

        logger.info(
            f"Ignored Dockerfile dependency {dependency.image_name} "
            f"(id={dependency_id}) for version {dependency.latest_tag}"
        )

        return {"success": True, "message": "Dependency ignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error ignoring Dockerfile dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to ignore dependency: {str(e)}")


@router.post("/dockerfile/{dependency_id}/unignore")
async def unignore_dockerfile_dependency(dependency_id: int, db: AsyncSession = Depends(get_db)):
    """
    Unignore a Dockerfile dependency update.

    Clears the ignore flag so the update will be shown again.
    """
    try:
        # Get dependency
        result = await db.execute(
            select(DockerfileDependency).where(DockerfileDependency.id == dependency_id)
        )
        dependency = result.scalar_one_or_none()

        if not dependency:
            raise HTTPException(status_code=404, detail="Dependency not found")

        if not dependency.ignored:
            raise HTTPException(status_code=400, detail="Dependency is not ignored")

        # Clear ignore fields
        dependency.ignored = False
        dependency.ignored_version = None
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
            dependency_type="dockerfile",
            dependency_id=dependency.id,
            dependency_name=dependency.image_name,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(history_event)

        await db.commit()

        logger.info(
            f"Unignored Dockerfile dependency {sanitize_log_message(str(dependency.image_name))} (id={sanitize_log_message(str(dependency_id))})"
        )

        return {"success": True, "message": "Dependency unignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error unignoring Dockerfile dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to unignore dependency: {str(e)}")


@router.get("/dockerfile/{dependency_id}/preview", response_model=PreviewResponse)
async def preview_dockerfile_update(
    dependency_id: int,
    new_version: str = Query(..., description="New version to preview"),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview a Dockerfile dependency update without applying it.

    Returns the current and new lines that would be changed.
    """
    try:
        result = await DependencyUpdateService.preview_update(
            db=db,
            dependency_type="dockerfile",
            dependency_id=dependency_id,
            new_version=new_version,
        )

        return PreviewResponse(
            current_line=result["current_line"],
            new_line=result["new_line"],
            file_path=result["file_path"],
            line_number=result.get("line_number"),
            current_version=result["current_version"],
            new_version=result["new_version"],
            changelog=result.get("changelog"),
            changelog_url=result.get("changelog_url"),
        )

    except Exception as e:
        logger.error(
            f"Error previewing Dockerfile dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to preview update: {str(e)}")


@router.post("/dockerfile/{dependency_id}/update", response_model=UpdateResponse)
async def update_dockerfile_dependency(
    dependency_id: int, request: UpdateRequest, db: AsyncSession = Depends(get_db)
):
    """
    Update a Dockerfile dependency in the source file.

    Creates a backup before updating and records the change in history.
    """
    try:
        result = await DependencyUpdateService.update_dockerfile_base_image(
            db=db,
            dependency_id=dependency_id,
            new_version=request.new_version,
            triggered_by="user",
        )

        return UpdateResponse(
            success=result["success"],
            backup_path=result.get("backup_path"),
            history_id=result.get("history_id"),
            changes_made=result.get("changes_made"),
            error=result.get("error"),
        )

    except Exception as e:
        logger.error(
            f"Error updating Dockerfile dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to update dependency: {str(e)}")


# ===================================================================
# HTTP Server Endpoints
# ===================================================================


@router.post("/http-servers/{server_id}/ignore")
async def ignore_http_server(
    server_id: int, request: IgnoreRequest, db: AsyncSession = Depends(get_db)
):
    """
    Ignore an HTTP server update.

    Marks the server as ignored for the current version transition.
    """
    try:
        # Get server
        result = await db.execute(select(HttpServer).where(HttpServer.id == server_id))
        server = result.scalar_one_or_none()

        if not server:
            raise HTTPException(status_code=404, detail="HTTP server not found")

        if server.ignored:
            raise HTTPException(status_code=400, detail="HTTP server is already ignored")

        # Update server
        server.ignored = True
        server.ignored_version = server.latest_version
        server.ignored_by = "user"
        server.ignored_at = datetime.now(UTC)
        server.ignored_reason = request.reason

        # Create history entry
        history = UpdateHistory(
            container_id=server.container_id,
            container_name="",
            update_id=None,
            from_tag=server.current_version or "unknown",
            to_tag=server.latest_version or "unknown",
            update_type="manual",
            status="success",
            event_type="dependency_ignore",
            dependency_type="http_server",
            dependency_id=server.id,
            dependency_name=server.name,
            file_path=server.dockerfile_path,
            reason=request.reason or "User ignored update",
            triggered_by="user",
        )
        db.add(history)

        await db.commit()

        logger.info(
            f"Ignored HTTP server {server.name} (id={server_id}) "
            f"for version {server.latest_version}"
        )

        return {"success": True, "message": "HTTP server ignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error ignoring HTTP server {sanitize_log_message(str(server_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to ignore HTTP server: {str(e)}")


@router.post("/http-servers/{server_id}/unignore")
async def unignore_http_server(server_id: int, db: AsyncSession = Depends(get_db)):
    """
    Unignore an HTTP server update.
    """
    try:
        # Get server
        result = await db.execute(select(HttpServer).where(HttpServer.id == server_id))
        server = result.scalar_one_or_none()

        if not server:
            raise HTTPException(status_code=404, detail="HTTP server not found")

        if not server.ignored:
            raise HTTPException(status_code=400, detail="HTTP server is not ignored")

        # Clear ignore fields
        server.ignored = False
        server.ignored_version = None
        server.ignored_by = None
        server.ignored_at = None
        server.ignored_reason = None

        # Get container name
        container_result = await db.execute(
            select(Container).where(Container.id == server.container_id)
        )
        container = container_result.scalar_one_or_none()
        container_name = container.name if container else "Unknown"

        # Create history event for unignore
        history_event = UpdateHistory(
            container_id=server.container_id,
            container_name=container_name,
            from_tag="",
            to_tag="",
            update_type="manual",
            status="success",
            event_type="dependency_unignore",
            dependency_type="http_server",
            dependency_id=server.id,
            dependency_name=server.name,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(history_event)

        await db.commit()

        logger.info(
            f"Unignored HTTP server {sanitize_log_message(str(server.name))} (id={sanitize_log_message(str(server_id))})"
        )

        return {"success": True, "message": "HTTP server unignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error unignoring HTTP server {sanitize_log_message(str(server_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to unignore HTTP server: {str(e)}")


@router.get("/http-servers/{server_id}/preview", response_model=PreviewResponse)
async def preview_http_server_update(
    server_id: int,
    new_version: str = Query(..., description="New version to preview"),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview an HTTP server version update without applying it.

    Returns the current and new LABEL lines that would be changed.
    """
    try:
        result = await DependencyUpdateService.preview_update(
            db=db,
            dependency_type="http_server",
            dependency_id=server_id,
            new_version=new_version,
        )

        return PreviewResponse(
            current_line=result["current_line"],
            new_line=result["new_line"],
            file_path=result["file_path"],
            line_number=result.get("line_number"),
            current_version=result["current_version"],
            new_version=result["new_version"],
            changelog=result.get("changelog"),
            changelog_url=result.get("changelog_url"),
        )

    except Exception as e:
        logger.error(
            f"Error previewing HTTP server {sanitize_log_message(str(server_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to preview update: {str(e)}")


@router.post("/http-servers/{server_id}/update", response_model=UpdateResponse)
async def update_http_server(
    server_id: int, request: UpdateRequest, db: AsyncSession = Depends(get_db)
):
    """
    Update an HTTP server version label in the Dockerfile.

    Creates a backup before updating and records the change in history.
    """
    try:
        result = await DependencyUpdateService.update_http_server_label(
            db=db,
            server_id=server_id,
            new_version=request.new_version,
            triggered_by="user",
        )

        return UpdateResponse(
            success=result["success"],
            backup_path=result.get("backup_path"),
            history_id=result.get("history_id"),
            changes_made=result.get("changes_made"),
            error=result.get("error"),
        )

    except Exception as e:
        logger.error(
            f"Error updating HTTP server {sanitize_log_message(str(server_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to update HTTP server: {str(e)}")


# ===================================================================
# App Dependency Endpoints
# ===================================================================


@router.post("/app-dependencies/batch/update", response_model=BatchDependencyUpdateResponse)
async def batch_update_app_dependencies(
    request: BatchDependencyUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Batch update multiple application dependencies.

    Updates each dependency to its latest version. Returns granular
    success/failure status for each item.
    """
    updated: list[BatchDependencyUpdateItem] = []
    failed: list[BatchDependencyUpdateItem] = []

    for dep_id in request.dependency_ids:
        try:
            # Get dependency
            result = await db.execute(
                select(AppDependency).where(AppDependency.id == dep_id)
            )
            dependency = result.scalar_one_or_none()

            if not dependency:
                failed.append(
                    BatchDependencyUpdateItem(
                        id=dep_id,
                        name=f"Unknown (id={dep_id})",
                        from_version="unknown",
                        to_version="unknown",
                        success=False,
                        error="Dependency not found",
                    )
                )
                continue

            # Skip ignored dependencies
            if dependency.ignored:
                failed.append(
                    BatchDependencyUpdateItem(
                        id=dep_id,
                        name=dependency.name,
                        from_version=dependency.current_version,
                        to_version=dependency.latest_version or dependency.current_version,
                        success=False,
                        error="Dependency is ignored",
                    )
                )
                continue

            # Skip if no update available
            if not dependency.update_available or not dependency.latest_version:
                failed.append(
                    BatchDependencyUpdateItem(
                        id=dep_id,
                        name=dependency.name,
                        from_version=dependency.current_version,
                        to_version=dependency.latest_version or dependency.current_version,
                        success=False,
                        error="No update available",
                    )
                )
                continue

            # Perform update using the static service method
            try:
                update_result = await DependencyUpdateService.update_app_dependency(
                    db=db,
                    dependency_id=dep_id,
                    new_version=dependency.latest_version,
                    triggered_by="user",
                )

                if update_result.get("success"):
                    updated.append(
                        BatchDependencyUpdateItem(
                            id=dep_id,
                            name=dependency.name,
                            from_version=dependency.current_version,
                            to_version=dependency.latest_version,
                            success=True,
                            backup_path=update_result.get("backup_path"),
                            history_id=update_result.get("history_id"),
                        )
                    )
                else:
                    failed.append(
                        BatchDependencyUpdateItem(
                            id=dep_id,
                            name=dependency.name,
                            from_version=dependency.current_version,
                            to_version=dependency.latest_version,
                            success=False,
                            error=update_result.get("error", "Update failed"),
                        )
                    )
            except Exception as e:
                failed.append(
                    BatchDependencyUpdateItem(
                        id=dep_id,
                        name=dependency.name,
                        from_version=dependency.current_version,
                        to_version=dependency.latest_version,
                        success=False,
                        error=str(e),
                    )
                )

        except Exception as e:
            failed.append(
                BatchDependencyUpdateItem(
                    id=dep_id,
                    name=f"Unknown (id={dep_id})",
                    from_version="unknown",
                    to_version="unknown",
                    success=False,
                    error=str(e),
                )
            )

    # Commit all successful updates
    await db.commit()

    logger.info(
        f"Batch update completed: {len(updated)} updated, {len(failed)} failed"
    )

    return BatchDependencyUpdateResponse(
        updated=updated,
        failed=failed,
        summary=BatchDependencyUpdateSummary(
            total=len(request.dependency_ids),
            updated_count=len(updated),
            failed_count=len(failed),
        ),
    )


@router.post("/app-dependencies/{dependency_id}/ignore")
async def ignore_app_dependency(
    dependency_id: int, request: IgnoreRequest, db: AsyncSession = Depends(get_db)
):
    """
    Ignore an application dependency update.
    """
    try:
        # Get dependency
        result = await db.execute(select(AppDependency).where(AppDependency.id == dependency_id))
        dependency = result.scalar_one_or_none()

        if not dependency:
            raise HTTPException(status_code=404, detail="App dependency not found")

        if dependency.ignored:
            raise HTTPException(status_code=400, detail="App dependency is already ignored")

        # Update dependency
        dependency.ignored = True
        dependency.ignored_version = dependency.latest_version
        dependency.ignored_by = "user"
        dependency.ignored_at = datetime.now(UTC)
        dependency.ignored_reason = request.reason

        # Create history entry
        history = UpdateHistory(
            container_id=dependency.container_id,
            container_name="",
            update_id=None,
            from_tag=dependency.current_version,
            to_tag=dependency.latest_version or dependency.current_version,
            update_type="manual",
            status="success",
            event_type="dependency_ignore",
            dependency_type="app_dependency",
            dependency_id=dependency.id,
            dependency_name=dependency.name,
            file_path=dependency.manifest_file,
            reason=request.reason or "User ignored update",
            triggered_by="user",
        )
        db.add(history)

        await db.commit()

        logger.info(
            f"Ignored app dependency {dependency.name} (id={dependency_id}) "
            f"for version {dependency.latest_version}"
        )

        return {"success": True, "message": "App dependency ignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error ignoring app dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to ignore app dependency: {str(e)}")


@router.post("/app-dependencies/{dependency_id}/unignore")
async def unignore_app_dependency(dependency_id: int, db: AsyncSession = Depends(get_db)):
    """
    Unignore an application dependency update.
    """
    try:
        # Get dependency
        result = await db.execute(select(AppDependency).where(AppDependency.id == dependency_id))
        dependency = result.scalar_one_or_none()

        if not dependency:
            raise HTTPException(status_code=404, detail="App dependency not found")

        if not dependency.ignored:
            raise HTTPException(status_code=400, detail="App dependency is not ignored")

        # Clear ignore fields
        dependency.ignored = False
        dependency.ignored_version = None
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
            dependency_type="app_dependency",
            dependency_id=dependency.id,
            dependency_name=dependency.name,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(history_event)

        await db.commit()

        logger.info(
            f"Unignored app dependency {sanitize_log_message(str(dependency.name))} (id={sanitize_log_message(str(dependency_id))})"
        )

        return {"success": True, "message": "App dependency unignored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error unignoring app dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to unignore app dependency: {str(e)}")


@router.get("/app-dependencies/{dependency_id}/preview", response_model=PreviewResponse)
async def preview_app_dependency_update(
    dependency_id: int,
    new_version: str = Query(..., description="New version to preview"),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview an app dependency update without applying it.

    Returns the current and new lines that would be changed in the manifest file.
    """
    try:
        result = await DependencyUpdateService.preview_update(
            db=db,
            dependency_type="app_dependency",
            dependency_id=dependency_id,
            new_version=new_version,
        )

        return PreviewResponse(
            current_line=result["current_line"],
            new_line=result["new_line"],
            file_path=result["file_path"],
            line_number=result.get("line_number"),
            current_version=result["current_version"],
            new_version=result["new_version"],
            changelog=result.get("changelog"),
            changelog_url=result.get("changelog_url"),
        )

    except Exception as e:
        logger.error(
            f"Error previewing app dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to preview update: {str(e)}")


@router.post("/app-dependencies/{dependency_id}/update", response_model=UpdateResponse)
async def update_app_dependency(
    dependency_id: int, request: UpdateRequest, db: AsyncSession = Depends(get_db)
):
    """
    Update an app dependency in its manifest file.

    Supports multiple manifest formats: package.json, requirements.txt,
    pyproject.toml, composer.json, Cargo.toml, go.mod.

    Creates a backup before updating and records the change in history.
    """
    try:
        result = await DependencyUpdateService.update_app_dependency(
            db=db,
            dependency_id=dependency_id,
            new_version=request.new_version,
            triggered_by="user",
        )

        return UpdateResponse(
            success=result["success"],
            backup_path=result.get("backup_path"),
            history_id=result.get("history_id"),
            changes_made=result.get("changes_made"),
            error=result.get("error"),
        )

    except Exception as e:
        logger.error(
            f"Error updating app dependency {sanitize_log_message(str(dependency_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to update app dependency: {str(e)}")
