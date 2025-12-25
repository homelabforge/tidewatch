"""Secure file operations for dependency updates.

This module provides security-first utilities for updating files in the build directory.
All operations include path validation, backup creation, and atomic writes.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

# Security constants
ALLOWED_BASE_PATH = Path("/projects")
MAX_VERSION_LENGTH = 50
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class FileOperationError(Exception):
    """Base exception for file operation errors."""

    pass


class PathValidationError(FileOperationError):
    """Raised when path validation fails."""

    pass


class VersionValidationError(FileOperationError):
    """Raised when version string validation fails."""

    pass


class BackupError(FileOperationError):
    """Raised when backup creation fails."""

    pass


class AtomicWriteError(FileOperationError):
    """Raised when atomic write fails."""

    pass


def validate_file_path_for_update(file_path: str) -> Path:
    """
    Validate file path for updates with strict security checks.

    Security rules:
    - Must be within /projects (container mount point)
    - No path traversal attempts (.., //, symlinks)
    - File must exist and be a regular file
    - File size must be reasonable (<10MB)
    - Must have read/write permissions

    Args:
        file_path: Absolute or relative path to file

    Returns:
        Path: Validated, resolved absolute path

    Raises:
        PathValidationError: If validation fails
    """
    try:
        # Convert to Path object and resolve
        path = Path(file_path).resolve()

        # Check if path is within allowed base path
        try:
            path.relative_to(ALLOWED_BASE_PATH)
        except ValueError:
            raise PathValidationError(
                f"Path {file_path} is outside allowed directory {ALLOWED_BASE_PATH}"
            )

        # Check for path traversal attempts in original string
        if ".." in str(file_path) or "//" in str(file_path):
            raise PathValidationError(f"Path contains traversal sequences: {file_path}")

        # Check if file exists
        if not path.exists():
            raise PathValidationError(f"File does not exist: {file_path}")

        # Check if it's a regular file (not directory or special file)
        if not path.is_file():
            raise PathValidationError(f"Path is not a regular file: {file_path}")

        # Check if it's a symlink (prevent symlink attacks)
        if path.is_symlink():
            raise PathValidationError(f"Path is a symlink: {file_path}")

        # Check file size
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            raise PathValidationError(
                f"File too large ({file_size} bytes, max {MAX_FILE_SIZE}): {file_path}"
            )

        # Check read permission
        if not os.access(path, os.R_OK):
            raise PathValidationError(f"No read permission: {file_path}")

        # Check write permission
        if not os.access(path, os.W_OK):
            raise PathValidationError(f"No write permission: {file_path}")

        logger.debug(f"Path validation successful: {sanitize_log_message(str(path))}")
        return path

    except PathValidationError:
        raise
    except Exception as e:
        raise PathValidationError(f"Path validation failed: {e}")


def validate_version_string(version: str, ecosystem: Optional[str] = None) -> bool:
    """
    Validate version string to prevent injection attacks.

    Rules:
    - Max 50 characters
    - Only alphanumeric, dots, hyphens, plus, tilde, caret
    - Ecosystem-specific validation when provided

    Args:
        version: Version string to validate
        ecosystem: Optional ecosystem for specific validation (npm, pypi, etc.)

    Returns:
        bool: True if valid

    Raises:
        VersionValidationError: If validation fails
    """
    # Check length
    if len(version) > MAX_VERSION_LENGTH:
        raise VersionValidationError(
            f"Version string too long ({len(version)} chars, max {MAX_VERSION_LENGTH})"
        )

    # Check for empty
    if not version or not version.strip():
        raise VersionValidationError("Version string is empty")

    # Basic pattern: alphanumeric, dots, hyphens, plus, tilde, caret
    # Covers semver, calver, and most package manager formats
    basic_pattern = r"^[a-zA-Z0-9.\-+~^]+$"
    if not re.match(basic_pattern, version):
        raise VersionValidationError(f"Version contains invalid characters: {version}")

    # Ecosystem-specific validation
    if ecosystem:
        if ecosystem == "npm":
            # npm semver: 1.2.3, 1.2.3-alpha.1, ^1.2.3, ~1.2.3, >=1.2.3
            npm_pattern = r"^[\^~>=<]*\d+\.\d+\.\d+(-[a-zA-Z0-9.\-+]+)?$"
            if not re.match(npm_pattern, version.lstrip("^~>=<")):
                raise VersionValidationError(f"Invalid npm version format: {version}")

        elif ecosystem == "pypi":
            # PEP 440: 1.2.3, 1.2.3a1, 1.2.3.post1, 1.2.3+local
            pypi_pattern = (
                r"^\d+(\.\d+)*([a-z]+\d+)?(\.(post|dev)\d+)?(\+[a-zA-Z0-9.]+)?$"
            )
            if not re.match(pypi_pattern, version):
                raise VersionValidationError(
                    f"Invalid Python version format: {version}"
                )

        elif ecosystem == "docker":
            # Docker tags: 1.2.3, 1.2.3-alpine, latest, sha256:abc...
            # Limit length to prevent ReDoS attacks
            if len(version) > 255:
                raise VersionValidationError("Docker tag too long (max 255 characters)")
            docker_pattern = r"^[a-zA-Z0-9.\-_]+(?::[a-zA-Z0-9.\-_]+)?$"  # Fixed: removed extra '?' after ':'
            if not re.match(docker_pattern, version):
                raise VersionValidationError(f"Invalid Docker tag format: {version}")

    logger.debug(
        f"Version validation successful: {sanitize_log_message(str(version))} (ecosystem: {sanitize_log_message(str(ecosystem))})"
    )
    return True


def create_timestamped_backup(file_path: Path) -> Path:
    """
    Create a timestamped backup of a file.

    Backup filename format: {original}.backup.{timestamp}
    Example: Dockerfile.backup.20250112-134525

    Args:
        file_path: Path to file to backup

    Returns:
        Path: Path to created backup file

    Raises:
        BackupError: If backup creation fails
    """
    try:
        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Create backup filename
        backup_path = file_path.parent / f"{file_path.name}.backup.{timestamp}"

        # Copy file to backup location
        shutil.copy2(file_path, backup_path)

        # Verify backup was created and has same content
        if not backup_path.exists():
            raise BackupError(f"Backup file not created: {backup_path}")

        if backup_path.stat().st_size != file_path.stat().st_size:
            raise BackupError(f"Backup file size mismatch: {backup_path}")

        logger.info(f"Created backup: {sanitize_log_message(str(backup_path))}")
        return backup_path

    except Exception as e:
        raise BackupError(f"Failed to create backup of {file_path}: {e}")


def atomic_file_write(file_path: Path, content: str) -> bool:
    """
    Write file atomically to prevent corruption.

    Strategy:
    1. Write to temporary file in same directory
    2. Verify write succeeded
    3. Copy original file's permissions and ownership
    4. Rename temp file to target (atomic operation)

    This ensures the original file is never partially written.

    Args:
        file_path: Path to target file
        content: Content to write

    Returns:
        bool: True if successful

    Raises:
        AtomicWriteError: If write fails
    """
    temp_path = None
    try:
        # Preserve original file's stat info if it exists
        original_stat = None
        if file_path.exists():
            original_stat = file_path.stat()

        # Create temp file in same directory (ensures same filesystem)
        temp_path = file_path.parent / f".{file_path.name}.tmp.{os.getpid()}"

        # Write content to temp file
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Verify temp file was written
        if not temp_path.exists():
            raise AtomicWriteError(f"Temp file not created: {temp_path}")

        # Verify content length matches
        written_size = temp_path.stat().st_size
        expected_size = len(content.encode("utf-8"))
        if written_size != expected_size:
            raise AtomicWriteError(
                f"Temp file size mismatch: written={written_size}, expected={expected_size}"
            )

        # Preserve original file's permissions and ownership
        if original_stat:
            try:
                os.chmod(temp_path, original_stat.st_mode)
                os.chown(temp_path, original_stat.st_uid, original_stat.st_gid)
            except (OSError, PermissionError) as e:
                logger.warning(
                    f"Could not preserve ownership/permissions: {sanitize_log_message(str(e))}"
                )

        # Atomic rename (replaces original file)
        temp_path.replace(file_path)

        logger.info(f"Atomic write successful: {sanitize_log_message(str(file_path))}")
        return True

    except Exception as e:
        # Clean up temp file if it exists
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as cleanup_error:
                logger.error(
                    f"Failed to clean up temp file {sanitize_log_message(str(temp_path))}: {sanitize_log_message(str(cleanup_error))}"
                )

        raise AtomicWriteError(f"Atomic write failed for {file_path}: {e}")


def restore_from_backup(backup_path: Path, target_path: Path) -> bool:
    """
    Restore a file from backup.

    Args:
        backup_path: Path to backup file
        target_path: Path to restore to

    Returns:
        bool: True if successful

    Raises:
        FileOperationError: If restore fails
    """
    try:
        # Validate backup exists
        if not backup_path.exists():
            raise FileOperationError(f"Backup file does not exist: {backup_path}")

        # Copy backup to target
        shutil.copy2(backup_path, target_path)

        # Verify restore
        if not target_path.exists():
            raise FileOperationError("Restore failed: target not created")

        logger.info(
            f"Restored {sanitize_log_message(str(target_path))} from backup {sanitize_log_message(str(backup_path))}"
        )
        return True

    except Exception as e:
        raise FileOperationError(f"Failed to restore from backup: {e}")


def cleanup_old_backups(file_path: Path, keep_count: int = 5) -> int:
    """
    Clean up old backup files, keeping only the most recent N backups.

    Args:
        file_path: Path to original file (backups will be in same directory)
        keep_count: Number of most recent backups to keep

    Returns:
        int: Number of backups deleted
    """
    try:
        # Find all backup files for this file
        pattern = f"{file_path.name}.backup.*"
        backup_files = sorted(
            file_path.parent.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,  # Newest first
        )

        # Delete old backups
        deleted_count = 0
        for backup in backup_files[keep_count:]:
            try:
                backup.unlink()
                deleted_count += 1
                logger.debug(f"Deleted old backup: {sanitize_log_message(str(backup))}")
            except Exception as e:
                logger.warning(
                    f"Failed to delete backup {sanitize_log_message(str(backup))}: {sanitize_log_message(str(e))}"
                )

        if deleted_count > 0:
            logger.info(
                f"Cleaned up {sanitize_log_message(str(deleted_count))} old backups for {sanitize_log_message(str(file_path.name))}"
            )

        return deleted_count

    except Exception as e:
        logger.warning(
            f"Failed to cleanup backups for {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return 0
