"""API endpoints for dependency ignore/unignore operations."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.app_dependency import AppDependency
from app.models.dockerfile_dependency import DockerfileDependency
from app.models.http_server import HttpServer
from app.schemas.dependency import (
    BatchDependencyUpdateItem,
    BatchDependencyUpdateRequest,
    BatchDependencyUpdateResponse,
    BatchDependencyUpdateSummary,
    IgnoreRequest,
    PreviewResponse,
    RollbackHistoryResponse,
    RollbackRequest,
    RollbackResponse,
    UpdateRequest,
    UpdateResponse,
)
from app.services.auth import require_auth
from app.services.dependency_ignore_service import (
    APP_DEPENDENCY_CONFIG,
    DOCKERFILE_CONFIG,
    HTTP_SERVER_CONFIG,
    DependencyIgnoreService,
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
    dependency_id: int,
    request: IgnoreRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Ignore a Dockerfile dependency update.

    Marks the dependency as ignored for the current version transition.
    If a newer version is released later, the ignore will be automatically cleared.
    """
    return await DependencyIgnoreService.ignore(
        db, DockerfileDependency, dependency_id, request.reason, DOCKERFILE_CONFIG
    )


@router.post("/dockerfile/{dependency_id}/unignore")
async def unignore_dockerfile_dependency(
    dependency_id: int,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Unignore a Dockerfile dependency update."""
    return await DependencyIgnoreService.unignore(
        db, DockerfileDependency, dependency_id, DOCKERFILE_CONFIG
    )


@router.get("/dockerfile/{dependency_id}/preview", response_model=PreviewResponse)
async def preview_dockerfile_update(
    dependency_id: int,
    new_version: str = Query(..., description="New version to preview"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Preview a Dockerfile dependency update without applying it."""
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
        raise HTTPException(status_code=500, detail="Failed to preview update")


@router.post("/dockerfile/{dependency_id}/update", response_model=UpdateResponse)
async def update_dockerfile_dependency(
    dependency_id: int,
    request: UpdateRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update a Dockerfile dependency in the source file."""
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
        raise HTTPException(status_code=500, detail="Failed to update dependency")


@router.get("/dockerfile/{dependency_id}/rollback-history", response_model=RollbackHistoryResponse)
async def get_dockerfile_rollback_history(
    dependency_id: int,
    limit: int = Query(10, ge=1, le=50, description="Max history items"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get available rollback versions for a Dockerfile dependency."""
    result = await DependencyUpdateService.get_rollback_history(
        db=db,
        dependency_type="dockerfile",
        dependency_id=dependency_id,
        limit=limit,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return RollbackHistoryResponse(**result)


@router.post("/dockerfile/{dependency_id}/rollback", response_model=RollbackResponse)
async def rollback_dockerfile_dependency(
    dependency_id: int,
    request: RollbackRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Rollback a Dockerfile dependency to a previous version."""
    result = await DependencyUpdateService.rollback_dependency(
        db=db,
        dependency_type="dockerfile",
        dependency_id=dependency_id,
        target_version=request.target_version,
        triggered_by="user",
    )

    return RollbackResponse(
        success=result["success"],
        history_id=result.get("history_id"),
        changes_made=result.get("changes_made"),
        error=result.get("error"),
    )


# ===================================================================
# HTTP Server Endpoints
# ===================================================================


@router.post("/http-servers/{server_id}/ignore")
async def ignore_http_server(
    server_id: int,
    request: IgnoreRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Ignore an HTTP server update."""
    return await DependencyIgnoreService.ignore(
        db, HttpServer, server_id, request.reason, HTTP_SERVER_CONFIG
    )


@router.post("/http-servers/{server_id}/unignore")
async def unignore_http_server(
    server_id: int,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Unignore an HTTP server update."""
    return await DependencyIgnoreService.unignore(db, HttpServer, server_id, HTTP_SERVER_CONFIG)


@router.get("/http-servers/{server_id}/preview", response_model=PreviewResponse)
async def preview_http_server_update(
    server_id: int,
    new_version: str = Query(..., description="New version to preview"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Preview an HTTP server version update without applying it."""
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
        raise HTTPException(status_code=500, detail="Failed to preview update")


@router.post("/http-servers/{server_id}/update", response_model=UpdateResponse)
async def update_http_server(
    server_id: int,
    request: UpdateRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update an HTTP server version in the appropriate source file."""
    try:
        result = await DependencyUpdateService.update_http_server(
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
        raise HTTPException(status_code=500, detail="Failed to update HTTP server")


@router.get("/http-servers/{server_id}/rollback-history", response_model=RollbackHistoryResponse)
async def get_http_server_rollback_history(
    server_id: int,
    limit: int = Query(10, ge=1, le=50, description="Max history items"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get available rollback versions for an HTTP server."""
    result = await DependencyUpdateService.get_rollback_history(
        db=db,
        dependency_type="http_server",
        dependency_id=server_id,
        limit=limit,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return RollbackHistoryResponse(**result)


@router.post("/http-servers/{server_id}/rollback", response_model=RollbackResponse)
async def rollback_http_server(
    server_id: int,
    request: RollbackRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Rollback an HTTP server to a previous version."""
    result = await DependencyUpdateService.rollback_dependency(
        db=db,
        dependency_type="http_server",
        dependency_id=server_id,
        target_version=request.target_version,
        triggered_by="user",
    )

    return RollbackResponse(
        success=result["success"],
        history_id=result.get("history_id"),
        changes_made=result.get("changes_made"),
        error=result.get("error"),
    )


# ===================================================================
# App Dependency Endpoints
# ===================================================================


@router.post("/app-dependencies/batch/update", response_model=BatchDependencyUpdateResponse)
async def batch_update_app_dependencies(
    request: BatchDependencyUpdateRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Batch update multiple application dependencies.

    Updates each dependency to its latest version. Returns granular
    success/failure status for each item.
    """
    updated: list[BatchDependencyUpdateItem] = []
    failed: list[BatchDependencyUpdateItem] = []

    for dep_id in request.dependency_ids:
        try:
            # Get dependency
            result = await db.execute(select(AppDependency).where(AppDependency.id == dep_id))
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

    logger.info(f"Batch update completed: {len(updated)} updated, {len(failed)} failed")

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
    dependency_id: int,
    request: IgnoreRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Ignore an application dependency update."""
    return await DependencyIgnoreService.ignore(
        db, AppDependency, dependency_id, request.reason, APP_DEPENDENCY_CONFIG
    )


@router.post("/app-dependencies/{dependency_id}/unignore")
async def unignore_app_dependency(
    dependency_id: int,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Unignore an application dependency update."""
    return await DependencyIgnoreService.unignore(
        db, AppDependency, dependency_id, APP_DEPENDENCY_CONFIG
    )


@router.get("/app-dependencies/{dependency_id}/preview", response_model=PreviewResponse)
async def preview_app_dependency_update(
    dependency_id: int,
    new_version: str = Query(..., description="New version to preview"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Preview an app dependency update without applying it."""
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
        raise HTTPException(status_code=500, detail="Failed to preview update")


@router.post("/app-dependencies/{dependency_id}/update", response_model=UpdateResponse)
async def update_app_dependency(
    dependency_id: int,
    request: UpdateRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update an app dependency in its manifest file."""
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
        raise HTTPException(status_code=500, detail="Failed to update app dependency")


@router.get(
    "/app-dependencies/{dependency_id}/rollback-history", response_model=RollbackHistoryResponse
)
async def get_app_dependency_rollback_history(
    dependency_id: int,
    limit: int = Query(10, ge=1, le=50, description="Max history items"),
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get available rollback versions for an app dependency."""
    result = await DependencyUpdateService.get_rollback_history(
        db=db,
        dependency_type="app_dependency",
        dependency_id=dependency_id,
        limit=limit,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return RollbackHistoryResponse(**result)


@router.post("/app-dependencies/{dependency_id}/rollback", response_model=RollbackResponse)
async def rollback_app_dependency(
    dependency_id: int,
    request: RollbackRequest,
    _admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Rollback an app dependency to a previous version."""
    result = await DependencyUpdateService.rollback_dependency(
        db=db,
        dependency_type="app_dependency",
        dependency_id=dependency_id,
        target_version=request.target_version,
        triggered_by="user",
    )

    return RollbackResponse(
        success=result["success"],
        history_id=result.get("history_id"),
        changes_made=result.get("changes_made"),
        error=result.get("error"),
    )
