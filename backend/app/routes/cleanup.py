"""Cleanup API endpoints for Docker resource cleanup."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth import require_auth
from app.services.cleanup_service import CleanupService
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_log_message

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_exclude_patterns(patterns_str: str) -> list[str]:
    """Parse comma-separated exclude patterns string."""
    if not patterns_str:
        return []
    return [p.strip() for p in patterns_str.split(",") if p.strip()]


@router.get("/stats")
async def get_disk_usage(
    admin: dict | None = Depends(require_auth),
) -> dict[str, Any]:
    """Get Docker disk usage statistics.

    Returns disk usage for images, containers, volumes, and build cache.
    """
    try:
        stats = await CleanupService.get_disk_usage()
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.error(f"Error getting disk usage stats: {sanitize_log_message(str(e))}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve disk usage statistics"
        )


@router.get("/preview")
async def preview_cleanup(
    admin: dict | None = Depends(require_auth),
    mode: str | None = Query(None, description="Override cleanup mode"),
    days: int | None = Query(None, description="Override days threshold"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Preview what would be cleaned up without removing anything.

    Uses current settings unless overridden by query parameters.
    """
    # Get settings
    cleanup_mode = mode or await SettingsService.get(db, "cleanup_mode", "dangling")
    cleanup_days = days or await SettingsService.get_int(db, "cleanup_after_days", 7)
    exclude_patterns_str = await SettingsService.get(
        db, "cleanup_exclude_patterns", "-dev,rollback"
    )
    exclude_patterns = _parse_exclude_patterns(exclude_patterns_str)

    preview = await CleanupService.get_cleanup_preview(
        mode=cleanup_mode,
        days=cleanup_days,
        exclude_patterns=exclude_patterns,
    )

    return {
        "success": True,
        "preview": preview,
        "settings": {
            "mode": cleanup_mode,
            "days": cleanup_days,
            "exclude_patterns": exclude_patterns,
        },
    }


@router.post("/images")
async def cleanup_images(
    admin: dict | None = Depends(require_auth),
    dangling_only: bool = Query(
        True, description="Only remove dangling (untagged) images"
    ),
    older_than_days: int | None = Query(
        None, description="Remove images older than X days"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clean up Docker images.

    Args:
        dangling_only: If True, only removes untagged images
        older_than_days: If provided, also removes images older than this threshold
    """
    exclude_patterns_str = await SettingsService.get(
        db, "cleanup_exclude_patterns", "-dev,rollback"
    )
    exclude_patterns = _parse_exclude_patterns(exclude_patterns_str)

    result = {"success": True, "images_removed": 0, "space_reclaimed": 0}

    # Always prune dangling images
    dangling_result = await CleanupService.prune_dangling_images()
    result["images_removed"] += dangling_result.get("images_removed", 0)
    result["space_reclaimed"] += dangling_result.get("space_reclaimed", 0)

    # Optionally remove old images
    if not dangling_only and older_than_days:
        old_result = await CleanupService.cleanup_old_images(
            older_than_days, exclude_patterns
        )
        result["images_removed"] += old_result.get("images_removed", 0)
        result["space_reclaimed"] += old_result.get("space_reclaimed", 0)

    result["space_reclaimed_formatted"] = CleanupService._format_bytes(
        result["space_reclaimed"]
    )

    logger.info(
        f"Image cleanup complete: {result['images_removed']} images, {result['space_reclaimed_formatted']}"
    )

    return result


@router.post("/containers")
async def cleanup_containers(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clean up exited/dead containers.

    Removes containers that are in exited, dead, or created state.
    Respects exclude patterns from settings.
    """
    try:
        exclude_patterns_str = await SettingsService.get(
            db, "cleanup_exclude_patterns", "-dev,rollback"
        )
        exclude_patterns = _parse_exclude_patterns(exclude_patterns_str)

        result = await CleanupService.prune_exited_containers(exclude_patterns)

        logger.info(
            f"Container cleanup complete: {result.get('containers_removed', 0)} containers removed"
        )

        return {"success": result.get("success", False), **result}
    except Exception as e:
        logger.error(f"Error cleaning up containers: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=500, detail="Failed to clean up containers")


@router.post("/all")
async def cleanup_all(
    admin: dict | None = Depends(require_auth),
    mode: str | None = Query(None, description="Override cleanup mode"),
    days: int | None = Query(None, description="Override days threshold"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Full cleanup: containers + images based on mode.

    Uses current settings unless overridden by query parameters.

    Modes:
    - dangling: Only remove untagged images
    - moderate: Remove untagged images + exited containers
    - aggressive: Remove untagged images + exited containers + old unused images
    """
    # Get settings
    cleanup_mode = mode or await SettingsService.get(db, "cleanup_mode", "dangling")
    cleanup_days = days or await SettingsService.get_int(db, "cleanup_after_days", 7)
    cleanup_containers = await SettingsService.get_bool(db, "cleanup_containers", True)
    exclude_patterns_str = await SettingsService.get(
        db, "cleanup_exclude_patterns", "-dev,rollback"
    )
    exclude_patterns = _parse_exclude_patterns(exclude_patterns_str)

    result = await CleanupService.run_cleanup(
        mode=cleanup_mode,
        days=cleanup_days,
        exclude_patterns=exclude_patterns,
        cleanup_containers=cleanup_containers,
    )

    return result


@router.post("/run-now")
async def run_cleanup_now(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger immediate cleanup using current settings.

    This runs the same cleanup that would run on schedule.
    Useful for testing settings or manual cleanup.
    """
    # Get all settings
    cleanup_mode = await SettingsService.get(db, "cleanup_mode", "dangling")
    cleanup_days = await SettingsService.get_int(db, "cleanup_after_days", 7)
    cleanup_containers = await SettingsService.get_bool(db, "cleanup_containers", True)
    exclude_patterns_str = await SettingsService.get(
        db, "cleanup_exclude_patterns", "-dev,rollback"
    )
    exclude_patterns = _parse_exclude_patterns(exclude_patterns_str)

    logger.info(f"Manual cleanup triggered (mode={cleanup_mode}, days={cleanup_days})")

    result = await CleanupService.run_cleanup(
        mode=cleanup_mode,
        days=cleanup_days,
        exclude_patterns=exclude_patterns,
        cleanup_containers=cleanup_containers,
    )

    result["message"] = (
        f"Cleanup complete: removed {result.get('images_removed', 0)} images and "
        f"{result.get('containers_removed', 0)} containers, "
        f"reclaimed {result.get('space_reclaimed_formatted', '0 B')}"
    )

    return result


@router.get("/settings")
async def get_cleanup_settings(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get current cleanup settings.

    Returns all cleanup-related settings for display/editing.
    """
    return {
        "success": True,
        "settings": {
            "enabled": await SettingsService.get_bool(db, "cleanup_old_images", False),
            "mode": await SettingsService.get(db, "cleanup_mode", "dangling"),
            "days": await SettingsService.get_int(db, "cleanup_after_days", 7),
            "cleanup_containers": await SettingsService.get_bool(
                db, "cleanup_containers", True
            ),
            "schedule": await SettingsService.get(db, "cleanup_schedule", "0 4 * * *"),
            "exclude_patterns": await SettingsService.get(
                db, "cleanup_exclude_patterns", "-dev,rollback"
            ),
        },
    }
