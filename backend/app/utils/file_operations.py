"""Secure file operations for dependency updates.

This module provides security-first utilities for updating files in the build directory.
All operations include path validation, backup creation, and atomic writes.
"""

import logging
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path

from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

# Security constants
ALLOWED_BASE_PATH = Path("/projects")
MAX_VERSION_LENGTH = 50
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _open_new_nofollow(path: Path) -> int:
    """Open a NEW file for writing, refusing to follow a symlink (O_NOFOLLOW) and
    refusing to overwrite an existing file (O_EXCL). Mode 0o600. Returns the fd.

    Used where the destination name is predictable (the timestamped backup), so a
    pre-planted symlink at that name must be rejected rather than written through.
    """
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


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


def validate_file_path_for_update(file_path: str, allowed_base: Path | None = None) -> Path:
    """
    Validate file path for updates with strict security checks.

    Security rules:
    - Must be within allowed_base (defaults to /projects container mount point)
    - No path traversal attempts (.., //, symlinks)
    - File must exist and be a regular file
    - File size must be reasonable (<10MB)
    - Must have read/write permissions

    Args:
        file_path: Absolute or relative path to file
        allowed_base: Base path to validate against (defaults to ALLOWED_BASE_PATH)

    Returns:
        Path: Validated, resolved absolute path

    Raises:
        PathValidationError: If validation fails
    """
    try:
        base = allowed_base or ALLOWED_BASE_PATH

        # Reject a symlink at the target BEFORE resolving — resolve() dereferences
        # symlinks, so a post-resolve is_symlink() check (the old code) was dead.
        if Path(file_path).is_symlink():
            raise PathValidationError(f"Path is a symlink: {file_path}")

        # Convert to Path object and resolve
        path = Path(file_path).resolve()

        # Check if path is within allowed base path
        try:
            path.relative_to(base)
        except ValueError:
            raise PathValidationError(f"Path {file_path} is outside allowed directory {base}")

        # Check for path traversal attempts in original string
        if ".." in str(file_path) or "//" in str(file_path):
            raise PathValidationError(f"Path contains traversal sequences: {file_path}")

        # Check if file exists
        if not path.exists():
            raise PathValidationError(f"File does not exist: {file_path}")

        # Check if it's a regular file (not directory or special file)
        if not path.is_file():
            raise PathValidationError(f"Path is not a regular file: {file_path}")

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


def validate_version_string(version: str, ecosystem: str | None = None) -> bool:
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
            pypi_pattern = r"^\d+(\.\d+)*([a-z]+\d+)?(\.(post|dev)\d+)?(\+[a-zA-Z0-9.]+)?$"
            if not re.match(pypi_pattern, version):
                raise VersionValidationError(f"Invalid Python version format: {version}")

        elif ecosystem == "docker":
            # Docker tags: 1.2.3, 1.2.3-alpine, latest, sha256:abc...
            # Limit length to prevent ReDoS attacks
            if len(version) > 255:
                raise VersionValidationError("Docker tag too long (max 255 characters)")
            docker_pattern = (
                r"^[a-zA-Z0-9.\-_]+(?::[a-zA-Z0-9.\-_]+)?$"  # Fixed: removed extra '?' after ':'
            )
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

        # Read the source without following a symlink, and write the (predictable)
        # backup name with O_NOFOLLOW|O_EXCL so a pre-planted symlink at that name
        # is refused rather than written through. fd→fd stream copy.
        src_fd = os.open(file_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            src_stat = os.fstat(src_fd)
            dst_fd = _open_new_nofollow(backup_path)
            try:
                while True:
                    chunk = os.read(src_fd, 1024 * 1024)
                    if not chunk:
                        break
                    os.write(dst_fd, chunk)
                os.fchmod(dst_fd, stat.S_IMODE(src_stat.st_mode))
                os.utime(dst_fd, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
            finally:
                os.close(dst_fd)
        finally:
            os.close(src_fd)

        # Verify backup was created and has same content size
        if not backup_path.exists():
            raise BackupError(f"Backup file not created: {backup_path}")

        if backup_path.stat().st_size != src_stat.st_size:
            raise BackupError(f"Backup file size mismatch: {backup_path}")

        logger.info(f"Created backup: {sanitize_log_message(str(backup_path))}")
        return backup_path

    except BackupError:
        raise
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
    temp_fd = None
    try:
        # Preserve original file's stat info if it exists
        original_stat = None
        if file_path.exists():
            original_stat = file_path.stat()

        encoded = content.encode("utf-8")

        # Create the temp file with an UNPREDICTABLE name (mkstemp, O_EXCL, 0o600)
        # in the same directory. The unpredictable name is the defense: an attacker
        # cannot pre-plant a symlink at a guessable temp path. os.replace at the end
        # swaps the temp INTO place atomically (replacing a symlink entry, if any,
        # without writing through it).
        temp_fd, temp_name = tempfile.mkstemp(
            dir=file_path.parent, prefix=f".{file_path.name}.tmp."
        )
        temp_path = Path(temp_name)
        with os.fdopen(temp_fd, "wb") as f:
            temp_fd = None  # fdopen now owns the fd
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())

        # Verify content length matches
        written_size = temp_path.stat().st_size
        if written_size != len(encoded):
            raise AtomicWriteError(
                f"Temp file size mismatch: written={written_size}, expected={len(encoded)}"
            )

        # Preserve original permissions/ownership via fd (no path-based chmod/chown
        # that could follow a symlink). Reopen O_NOFOLLOW defensively.
        if original_stat:
            try:
                pfd = os.open(temp_path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    os.fchmod(pfd, stat.S_IMODE(original_stat.st_mode))
                    os.fchown(pfd, original_stat.st_uid, original_stat.st_gid)
                finally:
                    os.close(pfd)
            except (OSError, PermissionError) as e:
                logger.warning(
                    f"Could not preserve ownership/permissions: {sanitize_log_message(str(e))}"
                )

        # Atomic replace (swaps the entry; never writes through a symlink target)
        os.replace(temp_path, file_path)
        temp_path = None

        logger.info(f"Atomic write successful: {sanitize_log_message(str(file_path))}")
        return True

    except Exception as e:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
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
    temp_path = None
    try:
        # Validate backup exists
        if not backup_path.exists():
            raise FileOperationError(f"Backup file does not exist: {backup_path}")

        # Read the backup without following a symlink, stage into an unpredictable
        # temp file in the target's directory, then os.replace into place. Because
        # the rollback callers pass UNRESOLVED target paths, target_path may itself
        # be a symlink — os.replace swaps the entry, so we never write through it.
        src_fd = os.open(backup_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            src_stat = os.fstat(src_fd)
            temp_fd, temp_name = tempfile.mkstemp(
                dir=target_path.parent, prefix=f".{target_path.name}.restore."
            )
            temp_path = Path(temp_name)
            try:
                while True:
                    chunk = os.read(src_fd, 1024 * 1024)
                    if not chunk:
                        break
                    os.write(temp_fd, chunk)
                os.fchmod(temp_fd, stat.S_IMODE(src_stat.st_mode))
            finally:
                os.close(temp_fd)
        finally:
            os.close(src_fd)

        os.replace(temp_path, target_path)
        temp_path = None

        # Verify restore
        if not target_path.exists():
            raise FileOperationError("Restore failed: target not created")

        logger.info(
            f"Restored {sanitize_log_message(str(target_path))} from backup {sanitize_log_message(str(backup_path))}"
        )
        return True

    except FileOperationError:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    except Exception as e:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
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
