"""Backup API endpoints for settings backup/restore."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DATABASE_URL, get_db
from app.services import SettingsService
from app.services.auth import require_auth
from app.utils.error_handling import safe_error_response
from app.utils.security import sanitize_log_message, sanitize_path

router = APIRouter()
logger = logging.getLogger(__name__)

# Backup directory configuration
BACKUP_DIR = Path("/data/backups")
DATABASE_PATH = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite+aiosqlite://", "")


def ensure_backup_dir() -> None:
    """Ensure backup directory exists."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def get_database_stats() -> dict[str, Any]:
    """Get database file statistics."""
    try:
        db_path = Path(DATABASE_PATH)
        if db_path.exists():
            stat = db_path.stat()
            return {
                "path": str(db_path),
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "exists": True,
            }
        return {
            "path": str(db_path),
            "size_mb": 0,
            "last_modified": None,
            "exists": False,
        }
    except PermissionError as e:
        logger.error(f"Permission denied reading database stats: {sanitize_log_message(str(e))}")
        return {
            "path": DATABASE_PATH,
            "size_mb": 0,
            "last_modified": None,
            "exists": False,
            "error": "Permission denied",
        }
    except OSError as e:
        logger.error(f"OS error getting database stats: {sanitize_log_message(str(e))}")
        return {
            "path": DATABASE_PATH,
            "size_mb": 0,
            "last_modified": None,
            "exists": False,
            "error": "An error occurred",
        }


def get_backup_files() -> list[dict[str, Any]]:
    """Get list of backup files with metadata."""
    ensure_backup_dir()
    backups = []

    try:
        for backup_file in BACKUP_DIR.glob("*.json"):
            stat = backup_file.stat()
            backups.append(
                {
                    "filename": backup_file.name,
                    "size_mb": round(stat.st_size / 1024 / 1024, 4),
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_safety": "safety" in backup_file.name.lower(),
                }
            )
    except PermissionError as e:
        logger.error(f"Permission denied listing backup files: {sanitize_log_message(str(e))}")
    except OSError as e:
        logger.error(f"OS error listing backup files: {sanitize_log_message(str(e))}")

    # Sort by created date (newest first)
    backups.sort(key=lambda x: x["created"], reverse=True)
    return backups


def validate_filename(filename: str) -> Path:
    """Validate and sanitize filename to prevent path traversal.

    Args:
        filename: The filename to validate

    Returns:
        Path: Safe path to backup file

    Raises:
        HTTPException: If filename is invalid or unsafe
    """
    # Remove any path separators
    safe_name = os.path.basename(filename)

    # Ensure it ends with .json
    if not safe_name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid file type. Must be .json")

    # Use sanitize_path to prevent path traversal attacks
    try:
        backup_path = sanitize_path(safe_name, BACKUP_DIR, allow_symlinks=False)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=400, detail="Invalid file path")

    return backup_path


@router.get("/stats")
async def get_stats(admin: dict | None = Depends(require_auth)) -> dict[str, Any]:
    """Get database and backup statistics.

    Returns:
        Statistics about database and backups including sizes, counts, and paths.
    """
    try:
        db_stats = get_database_stats()
        backups = get_backup_files()

        total_backup_size = sum(b["size_bytes"] for b in backups)

        return {
            "database": db_stats,
            "backups": {
                "count": len(backups),
                "total_size_mb": round(total_backup_size / 1024 / 1024, 2),
                "directory": str(BACKUP_DIR),
            },
            "wal_mode_enabled": "wal" in DATABASE_PATH.lower()
            or Path(f"{DATABASE_PATH}-wal").exists(),
        }
    except PermissionError as e:
        logger.error(f"Permission denied getting stats: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied accessing backup files")
    except OSError as e:
        logger.error(f"OS error getting stats: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.get("/list")
async def list_backups(admin: dict | None = Depends(require_auth)) -> dict[str, Any]:
    """List all available backup files with database stats.

    Returns:
        Dictionary with backup files list and database statistics.
    """
    try:
        backups = get_backup_files()
        db_path = Path(DATABASE_PATH)

        # Calculate total backup size
        total_backup_size = sum(b.get("size_bytes", 0) for b in backups)

        # Get database stats
        db_stats = {
            "database_path": str(db_path),
            "database_size": db_path.stat().st_size if db_path.exists() else 0,
            "database_modified": datetime.fromtimestamp(db_path.stat().st_mtime).isoformat()
            if db_path.exists()
            else None,
            "database_exists": db_path.exists(),
            "total_backups": len(backups),
            "total_size": total_backup_size,
            "backup_directory": str(BACKUP_DIR),
        }

        return {"backups": backups, "stats": db_stats}
    except PermissionError as e:
        logger.error(f"Permission denied listing backups: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied accessing backup files")
    except OSError as e:
        logger.error(f"OS error listing backups: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.post("/create")
async def create_backup(
    admin: dict | None = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Create a new backup of all settings.

    Args:
        db: Database session

    Returns:
        Metadata about the created backup file
    """
    try:
        ensure_backup_dir()

        # Get all settings from database
        settings = await SettingsService.get_all(db)

        # Build backup data structure
        backup_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "settings": [
                {
                    "key": s.key,
                    "value": s.value,
                    "category": s.category,
                    "description": s.description,
                    "encrypted": s.encrypted,
                }
                for s in settings
            ],
        }

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"tidewatch-settings-{timestamp}.json"
        backup_path = BACKUP_DIR / filename

        # Write backup file
        with open(backup_path, "w") as f:
            json.dump(backup_data, f, indent=2)

        logger.info(f"Created backup: {sanitize_log_message(str(filename))}")

        # Get file stats
        backup_path.stat()

        return {
            "message": "Backup created successfully",
            "filename": filename,
        }
    except PermissionError as e:
        logger.error(f"Permission denied creating backup: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied writing backup file")
    except OSError as e:
        logger.error(f"OS error creating backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON encoding error creating backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "Failed to encode backup data", status_code=500)


@router.get("/download/{filename}")
async def download_backup(filename: str, admin: dict | None = Depends(require_auth)):
    """Download a specific backup file.

    Args:
        filename: Name of the backup file to download

    Returns:
        Backup file as downloadable JSON
    """
    try:
        backup_path = validate_filename(filename)

        if not backup_path.exists():
            raise HTTPException(status_code=404, detail="Backup file not found")

        return FileResponse(
            path=backup_path,
            media_type="application/json",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"Permission denied downloading backup: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied reading backup file")
    except OSError as e:
        logger.error(f"OS error downloading backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.post("/restore/{filename}")
async def restore_backup(
    filename: str,
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Restore settings from a backup file.

    This creates a safety backup before restoring.

    Args:
        filename: Name of the backup file to restore from
        db: Database session

    Returns:
        Success message with details about restore operation
    """
    try:
        backup_path = validate_filename(filename)

        if not backup_path.exists():
            raise HTTPException(status_code=404, detail="Backup file not found")

        # Create safety backup first
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        safety_filename = f"tidewatch-settings-safety-{timestamp}.json"

        # Get current settings for safety backup
        current_settings = await SettingsService.get_all(db)
        safety_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "note": f"Safety backup created before restoring from {filename}",
            "settings": [
                {
                    "key": s.key,
                    "value": s.value,
                    "category": s.category,
                    "description": s.description,
                    "encrypted": s.encrypted,
                }
                for s in current_settings
            ],
        }

        safety_path = BACKUP_DIR / safety_filename
        with open(safety_path, "w") as f:
            json.dump(safety_data, f, indent=2)

        logger.info(f"Created safety backup: {sanitize_log_message(str(safety_filename))}")

        # Read and validate backup file
        with open(backup_path) as f:
            backup_data = json.load(f)

        # Validate backup structure
        if "settings" not in backup_data:
            raise HTTPException(status_code=400, detail="Invalid backup file structure")

        if not isinstance(backup_data["settings"], list):
            raise HTTPException(status_code=400, detail="Invalid backup file format")

        # Restore settings
        restored_count = 0
        for setting_data in backup_data["settings"]:
            key = setting_data.get("key")
            value = setting_data.get("value")

            if not key:
                logger.warning(
                    f"Skipping setting with no key: {sanitize_log_message(str(setting_data))}"
                )
                continue

            try:
                # Update setting in database
                await SettingsService.set(db, key, value)
                restored_count += 1
            except ValueError as e:
                logger.error(
                    f"Invalid value for setting {sanitize_log_message(str(key))}: {sanitize_log_message(str(e))}"
                )
                # Continue with other settings
            except KeyError as e:
                logger.error(
                    f"Invalid setting key {sanitize_log_message(str(key))}: {sanitize_log_message(str(e))}"
                )
                # Continue with other settings

        logger.info(
            f"Restored {sanitize_log_message(str(restored_count))} settings from {sanitize_log_message(str(filename))}"
        )

        return {
            "success": True,
            "message": f"Settings restored successfully from {filename}",
            "details": {
                "restored_count": restored_count,
                "safety_backup": safety_filename,
                "source_backup": filename,
            },
        }
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        safe_error_response(logger, e, "Invalid JSON in backup file", status_code=400)
    except PermissionError as e:
        logger.error(f"Permission denied restoring backup: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied accessing backup files")
    except FileNotFoundError as e:
        logger.error(f"Backup file not found: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "Backup file not found", status_code=404)
    except OSError as e:
        logger.error(f"OS error restoring backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.post("/upload")
async def upload_backup(
    admin: dict | None = Depends(require_auth),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload and save a backup file.

    Args:
        file: Uploaded backup file
        db: Database session (for validation)

    Returns:
        Metadata about the uploaded backup file
    """
    try:
        ensure_backup_dir()

        # Validate file type
        if not file.filename or not file.filename.endswith(".json"):
            raise HTTPException(status_code=400, detail="Invalid file type. Must be .json")

        # Sanitize filename
        safe_filename = os.path.basename(file.filename)

        # Add timestamp if filename already exists
        backup_path = BACKUP_DIR / safe_filename
        if backup_path.exists():
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            name_part = safe_filename.replace(".json", "")
            safe_filename = f"{name_part}-uploaded-{timestamp}.json"
            backup_path = BACKUP_DIR / safe_filename

        # Read and validate file content
        content = await file.read()

        # Validate it's valid JSON
        try:
            backup_data = json.loads(content)
            if "settings" not in backup_data or not isinstance(backup_data["settings"], list):
                raise HTTPException(status_code=400, detail="Invalid backup file structure")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")

        # Write to backup directory
        with open(backup_path, "wb") as f:
            f.write(content)

        logger.info(f"Uploaded backup: {sanitize_log_message(str(safe_filename))}")

        # Get file stats
        stat = backup_path.stat()

        return {
            "success": True,
            "message": "Backup uploaded successfully",
            "backup": {
                "filename": safe_filename,
                "size_mb": round(stat.st_size / 1024 / 1024, 4),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            },
        }
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"Permission denied uploading backup: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied writing backup file")
    except OSError as e:
        logger.error(f"OS error uploading backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.delete("/{filename}")
async def delete_backup(
    filename: str, admin: dict | None = Depends(require_auth)
) -> dict[str, Any]:
    """Delete a backup file.

    Safety backups cannot be deleted to prevent accidental data loss.

    Args:
        filename: Name of the backup file to delete

    Returns:
        Success message
    """
    try:
        backup_path = validate_filename(filename)

        if not backup_path.exists():
            raise HTTPException(status_code=404, detail="Backup file not found")

        # Prevent deletion of safety backups
        if "safety" in filename.lower():
            raise HTTPException(
                status_code=403,
                detail="Cannot delete safety backups. They are created automatically during restore operations.",
            )

        # Delete the file
        backup_path.unlink()

        logger.info(f"Deleted backup: {sanitize_log_message(str(filename))}")

        return {"success": True, "message": f"Backup {filename} deleted successfully"}
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"Permission denied deleting backup: {sanitize_log_message(str(e))}")
        raise HTTPException(status_code=403, detail="Permission denied deleting backup file")
    except OSError as e:
        logger.error(f"OS error deleting backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "File system error", status_code=500)


@router.get("/download")
async def download_backup_legacy(
    admin: dict | None = Depends(require_auth), db: AsyncSession = Depends(get_db)
):
    """Legacy endpoint: Download current settings as backup file.

    This endpoint creates a backup on-the-fly and returns it directly.
    Kept for backwards compatibility with old frontend code.

    Returns:
        Settings backup as downloadable JSON file
    """
    try:
        # Get all settings from database
        settings = await SettingsService.get_all(db)

        # Build backup data structure
        backup_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "settings": [
                {
                    "key": s.key,
                    "value": s.value,
                    "category": s.category,
                    "description": s.description,
                    "encrypted": s.encrypted,
                }
                for s in settings
            ],
        }

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"tidewatch-settings-{timestamp}.json"

        return JSONResponse(
            content=backup_data,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except (TypeError, ValueError) as e:
        logger.error(f"JSON encoding error creating backup: {sanitize_log_message(str(e))}")
        safe_error_response(logger, e, "Failed to encode backup data", status_code=500)


@router.post("/restore")
async def restore_backup_legacy(
    admin: dict | None = Depends(require_auth),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Legacy endpoint: Restore settings from uploaded file.

    Kept for backwards compatibility with old frontend code.

    Args:
        file: Uploaded backup file
        db: Database session

    Returns:
        Success message with restore details
    """
    try:
        # Read and validate file content
        content = await file.read()

        try:
            backup_data = json.loads(content)
        except json.JSONDecodeError as e:
            safe_error_response(logger, e, "Invalid JSON file", status_code=400)

        # Validate backup structure
        if "settings" not in backup_data:
            raise HTTPException(status_code=400, detail="Invalid backup file structure")

        if not isinstance(backup_data["settings"], list):
            raise HTTPException(status_code=400, detail="Invalid backup file format")

        # Restore settings
        restored_count = 0
        for setting_data in backup_data["settings"]:
            key = setting_data.get("key")
            value = setting_data.get("value")

            if not key:
                logger.warning(
                    f"Skipping setting with no key: {sanitize_log_message(str(setting_data))}"
                )
                continue

            try:
                # Update setting in database
                await SettingsService.set(db, key, value)
                restored_count += 1
            except ValueError as e:
                logger.error(
                    f"Invalid value for setting {sanitize_log_message(str(key))}: {sanitize_log_message(str(e))}"
                )
                # Continue with other settings
            except KeyError as e:
                logger.error(
                    f"Invalid setting key {sanitize_log_message(str(key))}: {sanitize_log_message(str(e))}"
                )
                # Continue with other settings

        logger.info(
            f"Restored {sanitize_log_message(str(restored_count))} settings from uploaded file"
        )

        return {
            "success": True,
            "message": f"Successfully restored {restored_count} settings",
        }
    except HTTPException:
        raise
