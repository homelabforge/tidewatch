"""Pre-update data backup service using Docker-native container approach.

Backs up container volumes and bind mounts before updates by spawning
temporary alpine containers to create tarballs. Supports staged restore
for crash-safe rollback.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import docker
from pathlib import Path

from docker.errors import APIError, DockerException, NotFound

from app.services.docker_access import make_docker_client, resolve_docker_url_sync

logger = logging.getLogger(__name__)

# Named Docker volume used for backup storage
BACKUP_VOLUME_NAME = "tidewatch_rollback_data"

# Mount point inside TideWatch container for the backup volume
BACKUP_BASE_DIR = Path("/rollback-data")

# Static host paths to always skip when backing up container mounts
_STATIC_SKIP_PREFIXES = (
    "/var/run",
    "/run",
)

# FHS-standard mount points for user data and removable / network media.
# By convention these are not container state and should not be tar'd into
# rollback snapshots. Override with ``TIDEWATCH_BACKUP_SKIP_PREFIXES``.
_DEFAULT_USER_DATA_PREFIXES = ("/mnt", "/media")

# Default per-mount size cap. Bind/volume mounts whose source exceeds this
# are skipped during backup. Override with ``TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB``.
_DEFAULT_MAX_MOUNT_SIZE_GB = 10.0

# Time budget for the per-mount ``du`` size pre-flight (seconds).
_SIZE_MEASUREMENT_TIMEOUT_SECONDS = 30

# Cached full skip list (populated lazily with TideWatch's own mount sources)
_skip_prefixes_cache: tuple[str, ...] | None = None


def _env_user_data_prefixes() -> tuple[str, ...]:
    """Return user-data skip prefixes from env, or the FHS defaults."""
    raw = os.environ.get("TIDEWATCH_BACKUP_SKIP_PREFIXES", "").strip()
    if not raw:
        return _DEFAULT_USER_DATA_PREFIXES
    return tuple(p.strip() for p in raw.split(":") if p.strip())


def _env_max_mount_size_bytes() -> int:
    """Return the per-mount size cap in bytes, from env or the default."""
    raw = os.environ.get("TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB", "").strip()
    try:
        gb = float(raw) if raw else _DEFAULT_MAX_MOUNT_SIZE_GB
    except ValueError:
        logger.warning(
            "Invalid TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB=%r; using default %.1f GB",
            raw,
            _DEFAULT_MAX_MOUNT_SIZE_GB,
        )
        gb = _DEFAULT_MAX_MOUNT_SIZE_GB
    return int(gb * 1024 * 1024 * 1024)


def _get_skip_source_prefixes() -> tuple[str, ...]:
    """Build skip-list from static prefixes + user-data + TideWatch's own mounts.

    TideWatch's own mounts (compose dir, projects dir, env dir, etc.) are
    infrastructure paths that should never be backed up as container data.
    """
    global _skip_prefixes_cache
    if _skip_prefixes_cache is not None:
        return _skip_prefixes_cache

    try:
        from app.services.mount_resolver import get_all_host_mount_sources

        dynamic = get_all_host_mount_sources()
    except RuntimeError:
        # Mount resolver unavailable (e.g. during tests) — use static only
        dynamic = ()

    _skip_prefixes_cache = _STATIC_SKIP_PREFIXES + _env_user_data_prefixes() + dynamic
    return _skip_prefixes_cache


def _reset_skip_prefixes_cache() -> None:
    """Clear the cached skip-prefix list (intended for tests)."""
    global _skip_prefixes_cache
    _skip_prefixes_cache = None


# Minimum free space (bytes) on backup volume before aborting
MIN_FREE_SPACE_BYTES = 500 * 1024 * 1024  # 500 MB

# Per-container locks to prevent overlapping backup/restore operations
_container_locks: dict[str, asyncio.Lock] = {}


def _get_container_lock(container_name: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a container."""
    if container_name not in _container_locks:
        _container_locks[container_name] = asyncio.Lock()
    return _container_locks[container_name]


@dataclass
class MountBackupInfo:
    """Info about a single backed-up mount."""

    mount_type: str  # bind, volume
    source: str
    destination: str
    tar_filename: str
    size_bytes: int = 0
    error: str | None = None


@dataclass
class BackupResult:
    """Result of a backup operation."""

    backup_id: str
    container_name: str
    status: str  # success, failed, timeout, skipped, partial
    mounts_backed_up: int = 0
    total_size_bytes: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    mounts: list[MountBackupInfo] = field(default_factory=list)


@dataclass
class RestoreResult:
    """Result of a restore operation."""

    backup_id: str
    container_name: str
    status: str  # success, failed, partial
    mounts_restored: int = 0
    duration_seconds: float = 0.0
    error: str | None = None


class DataBackupService:
    """Service for backing up and restoring container data volumes.

    Uses Docker-native approach: spawns temporary alpine containers to
    tar bind mounts and named volumes into a shared backup volume.
    """

    def __init__(self) -> None:
        self.client = make_docker_client(resolve_docker_url_sync())

    async def _measure_mount_size(
        self,
        source: str,
        is_volume: bool,
        timeout: int = _SIZE_MEASUREMENT_TIMEOUT_SECONDS,
    ) -> int | None:
        """Measure total bytes under a mount source via a temp alpine helper.

        Returns the apparent size in bytes, or ``None`` if measurement fails
        (timeout, permission denied, missing path, etc.). Callers should treat
        ``None`` as "do not back up" to fail safe.
        """
        volumes: dict[str, dict[str, str]] = (
            {source: {"bind": "/source", "mode": "ro"}}
            if is_volume
            else {source: {"bind": "/source", "mode": "ro"}}
        )
        helper = None
        try:
            helper = await asyncio.to_thread(
                self.client.containers.run,
                "alpine:latest",
                command="sh -c 'du -sb /source 2>/dev/null | awk \"{print \\$1}\"'",
                volumes=volumes,
                detach=True,
                auto_remove=False,
                name=f"tw-measure-{uuid.uuid4().hex[:8]}",
            )
            result = await asyncio.to_thread(helper.wait, timeout=timeout)
            if result["StatusCode"] != 0:
                return None
            output = await asyncio.to_thread(helper.logs)
            text = output.decode("utf-8", errors="replace").strip()
            return int(text) if text else None
        except Exception as exc:
            logger.debug("Size measurement failed for %s: %s", source, exc)
            return None
        finally:
            if helper is not None:
                try:
                    await asyncio.to_thread(helper.remove, force=True)
                except Exception:
                    pass

    async def _filter_oversized_mounts(
        self,
        mounts: list[dict],
        container_name: str,
    ) -> list[dict]:
        """Drop mounts whose source exceeds the configured size cap.

        Mounts whose size cannot be measured are also dropped (fail-safe), so
        a runaway path like a NAS-mounted media library cannot fill the
        rollback volume even if the prefix skip-list misses it.
        """
        max_bytes = _env_max_mount_size_bytes()
        kept: list[dict] = []
        for mount in mounts:
            source = mount.get("Source", "")
            volume_name = mount.get("Name", "")
            mount_type = mount.get("Type", "bind")
            measure_target = volume_name if mount_type == "volume" and volume_name else source
            size = await self._measure_mount_size(
                measure_target,
                is_volume=mount_type == "volume",
            )
            if size is None:
                logger.warning(
                    "Skipping mount %s for %s: size could not be measured",
                    source or volume_name,
                    container_name,
                )
                continue
            if size > max_bytes:
                logger.warning(
                    "Skipping mount %s for %s: %.2f GB exceeds cap of %.2f GB",
                    source or volume_name,
                    container_name,
                    size / (1024**3),
                    max_bytes / (1024**3),
                )
                continue
            kept.append(mount)
        return kept

    def _get_backup_dir(self, container_name: str, backup_id: str) -> Path:
        """Get the backup directory path for a container backup."""
        return BACKUP_BASE_DIR / container_name / backup_id

    def _should_skip_mount(self, mount: dict) -> tuple[bool, str]:
        """Determine if a mount should be skipped during backup.

        Args:
            mount: Docker mount info dict from container inspect.

        Returns:
            Tuple of (should_skip, reason).
        """
        source = mount.get("Source", "")
        mode = mount.get("Mode", "rw")
        rw = mount.get("RW", True)

        # Skip read-only mounts
        if not rw or "ro" in str(mode):
            return True, "read-only mount"

        # Skip socket mounts
        if source.endswith(".sock"):
            return True, "socket mount"

        # Skip infrastructure/shared paths (TideWatch's own mounts + static list)
        for prefix in _get_skip_source_prefixes():
            if source.startswith(prefix):
                return True, f"infrastructure path ({prefix})"

        # Skip single-file mounts (no trailing slash, contains a dot-extension)
        # Docker reports Type=bind for both file and directory mounts
        if mount.get("Type") == "bind":
            source_path = Path(source)
            if source_path.suffix and not source.endswith("/"):
                # Heuristic: paths ending in .conf, .yml, .json, etc. are likely files
                # More precise: we'd need to stat, but this avoids a Docker call
                common_file_exts = {
                    ".conf",
                    ".yml",
                    ".yaml",
                    ".json",
                    ".toml",
                    ".env",
                    ".ini",
                    ".cfg",
                    ".xml",
                    ".sock",
                    ".log",
                    ".pid",
                    ".lock",
                    ".key",
                    ".pem",
                    ".crt",
                    ".cert",
                }
                if source_path.suffix.lower() in common_file_exts:
                    return True, f"single-file mount ({source_path.suffix})"

        return False, ""

    def _detect_database(self, container_info: dict) -> str | None:
        """Detect if container runs a database requiring special backup.

        Args:
            container_info: Full container inspect data.

        Returns:
            Database type string or None.
        """
        image = container_info.get("Config", {}).get("Image", "").lower()

        if any(db in image for db in ("postgres", "postgresql")):
            return "postgresql"

        return None

    def _get_pg_user(self, container_info: dict) -> str:
        """Extract PostgreSQL user from container environment variables.

        Args:
            container_info: Full container inspect data.

        Returns:
            PostgreSQL username (defaults to 'postgres').
        """
        env_list = container_info.get("Config", {}).get("Env", [])
        for env_var in env_list:
            if env_var.startswith("POSTGRES_USER="):
                return env_var.split("=", 1)[1]
        return "postgres"

    async def create_backup(
        self,
        container_name: str,
        timeout_seconds: int = 300,
        storage_key: str | None = None,
    ) -> BackupResult:
        """Create a backup of all eligible mounts for a container.

        Args:
            container_name: Docker runtime name for container inspection.
            timeout_seconds: Maximum time for the entire backup operation.
            storage_key: Stable key for backup directory naming (defaults to
                container_name for backward compatibility). Use service_name
                to keep backup paths stable across display-name changes.

        Returns:
            BackupResult with backup metadata.
        """
        key = storage_key or container_name
        lock = _get_container_lock(key)
        async with lock:
            return await self._create_backup_impl(container_name, timeout_seconds, key)

    async def _create_backup_impl(
        self,
        container_name: str,
        timeout_seconds: int,
        storage_key: str,
    ) -> BackupResult:
        """Internal backup implementation (runs under lock)."""
        start_time = time.monotonic()
        backup_id = uuid.uuid4().hex[:12]
        backup_dir = self._get_backup_dir(storage_key, backup_id)

        try:
            # Check available space on backup volume
            free_bytes = await self._check_backup_volume_space()
            if free_bytes is not None and free_bytes < MIN_FREE_SPACE_BYTES:
                logger.warning(
                    "Insufficient space on backup volume for %s: %d MB free",
                    container_name,
                    free_bytes // (1024 * 1024),
                )
                return BackupResult(
                    backup_id=backup_id,
                    container_name=container_name,
                    status="failed",
                    duration_seconds=time.monotonic() - start_time,
                    error=f"Insufficient backup volume space: {free_bytes // (1024 * 1024)} MB free",
                )

            # Inspect target container
            container = await asyncio.to_thread(self.client.containers.get, container_name)
            container_info = container.attrs
            mounts = container_info.get("Mounts", [])

            if not mounts:
                logger.info("No mounts found for %s, skipping backup", container_name)
                return BackupResult(
                    backup_id=backup_id,
                    container_name=container_name,
                    status="skipped",
                    duration_seconds=time.monotonic() - start_time,
                )

            # Filter eligible mounts
            eligible_mounts = []
            for mount in mounts:
                should_skip, reason = self._should_skip_mount(mount)
                if should_skip:
                    logger.debug("Skipping mount %s: %s", mount.get("Source", "?"), reason)
                else:
                    eligible_mounts.append(mount)

            # Defense-in-depth: drop anything still oversized after the
            # prefix/file/socket filters. Catches NAS-mounted media libraries
            # and other runaway sources the static skip-list can miss.
            eligible_mounts = await self._filter_oversized_mounts(eligible_mounts, container_name)

            if not eligible_mounts:
                logger.info("No eligible mounts for %s after filtering", container_name)
                return BackupResult(
                    backup_id=backup_id,
                    container_name=container_name,
                    status="skipped",
                    duration_seconds=time.monotonic() - start_time,
                )

            # Create backup directory
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Calculate per-mount timeout
            per_mount_timeout = max(60, timeout_seconds // len(eligible_mounts))

            # Build metadata
            metadata: dict = {
                "backup_id": backup_id,
                "container_name": container_name,
                "container_image": container_info.get("Config", {}).get("Image", ""),
                "created_at": datetime.now(UTC).isoformat(),
                "mounts": [],
            }

            # Check for PostgreSQL
            db_type = self._detect_database(container_info)
            if db_type == "postgresql":
                pg_user = self._get_pg_user(container_info)
                pg_version = await self._get_pg_version(container)
                metadata["pg_version"] = pg_version
                metadata["pg_user"] = pg_user

                await self._backup_postgresql(container, backup_dir, pg_user, per_mount_timeout)

            # Backup each eligible mount
            backed_up_mounts: list[MountBackupInfo] = []
            total_size = 0

            for mount in eligible_mounts:
                # Check total timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    logger.warning(
                        "Backup timeout reached for %s after %d mounts",
                        container_name,
                        len(backed_up_mounts),
                    )
                    self._save_metadata(backup_dir, metadata)
                    return BackupResult(
                        backup_id=backup_id,
                        container_name=container_name,
                        status="timeout",
                        mounts_backed_up=len(backed_up_mounts),
                        total_size_bytes=total_size,
                        duration_seconds=elapsed,
                        mounts=backed_up_mounts,
                    )

                mount_type = mount.get("Type", "bind")
                source = mount.get("Source", "")
                destination = mount.get("Destination", "")
                volume_name = mount.get("Name", "")

                try:
                    if mount_type == "volume" and volume_name:
                        mount_info = await self._backup_named_volume(
                            volume_name,
                            destination,
                            container_name,
                            backup_id,
                            per_mount_timeout,
                        )
                    else:
                        mount_info = await self._backup_bind_mount(
                            source,
                            destination,
                            container_name,
                            backup_id,
                            per_mount_timeout,
                        )

                    backed_up_mounts.append(mount_info)
                    total_size += mount_info.size_bytes
                    metadata["mounts"].append(
                        {
                            "type": mount_type,
                            "source": source,
                            "destination": destination,
                            "volume_name": volume_name,
                            "tar_filename": mount_info.tar_filename,
                            "size_bytes": mount_info.size_bytes,
                        }
                    )

                except Exception as e:
                    logger.error(
                        "Failed to backup mount %s -> %s: %s",
                        source,
                        destination,
                        e,
                    )
                    mount_info = MountBackupInfo(
                        mount_type=mount_type,
                        source=source,
                        destination=destination,
                        tar_filename="",
                        error=str(e),
                    )
                    backed_up_mounts.append(mount_info)
                    metadata["mounts"].append(
                        {
                            "type": mount_type,
                            "source": source,
                            "destination": destination,
                            "error": str(e),
                        }
                    )

            self._save_metadata(backup_dir, metadata)
            duration = time.monotonic() - start_time

            # Determine status based on results
            failed_count = sum(1 for m in backed_up_mounts if m.error)
            success_count = len(backed_up_mounts) - failed_count

            if success_count == 0 and failed_count > 0:
                status = "failed"
            elif failed_count > 0:
                status = "partial"
            else:
                status = "success"

            logger.info(
                "Backup complete for %s: %d/%d mounts, %d bytes, %.1fs",
                container_name,
                success_count,
                len(backed_up_mounts),
                total_size,
                duration,
            )

            return BackupResult(
                backup_id=backup_id,
                container_name=container_name,
                status=status,
                mounts_backed_up=success_count,
                total_size_bytes=total_size,
                duration_seconds=duration,
                mounts=backed_up_mounts,
            )

        except NotFound:
            return BackupResult(
                backup_id=backup_id,
                container_name=container_name,
                status="failed",
                duration_seconds=time.monotonic() - start_time,
                error=f"Container {container_name} not found",
            )
        except (DockerException, APIError) as e:
            return BackupResult(
                backup_id=backup_id,
                container_name=container_name,
                status="failed",
                duration_seconds=time.monotonic() - start_time,
                error=str(e),
            )

    async def _backup_named_volume(
        self,
        volume_name: str,
        destination: str,
        container_name: str,
        backup_id: str,
        timeout: int,
    ) -> MountBackupInfo:
        """Backup a named Docker volume using a temporary alpine container."""
        safe_name = destination.strip("/").replace("/", "_")
        tar_filename = f"vol_{safe_name}.tar.gz"
        # Path inside the temp container's backup mount
        backup_subdir = f"{container_name}/{backup_id}"

        helper = await asyncio.to_thread(
            self.client.containers.run,
            "alpine:latest",
            command=f"sh -c 'mkdir -p /backup/{backup_subdir} && tar czf /backup/{backup_subdir}/{tar_filename} -C /source .'",
            volumes={
                volume_name: {"bind": "/source", "mode": "ro"},
                BACKUP_VOLUME_NAME: {"bind": "/backup", "mode": "rw"},
            },
            detach=True,
            auto_remove=False,
            name=f"tw-backup-{uuid.uuid4().hex[:8]}",
        )

        try:
            result = await asyncio.to_thread(helper.wait, timeout=timeout)
            if result["StatusCode"] != 0:
                logs = await asyncio.to_thread(helper.logs)
                raise RuntimeError(
                    f"Backup container exited with {result['StatusCode']}: "
                    f"{logs.decode('utf-8', errors='replace')}"
                )
        finally:
            try:
                await asyncio.to_thread(helper.remove, force=True)
            except Exception:
                pass  # Best-effort cleanup of temporary helper container

        # Check file size from local mount
        local_tar = BACKUP_BASE_DIR / container_name / backup_id / tar_filename
        size = local_tar.stat().st_size if local_tar.exists() else 0

        return MountBackupInfo(
            mount_type="volume",
            source=volume_name,
            destination=destination,
            tar_filename=tar_filename,
            size_bytes=size,
        )

    async def _backup_bind_mount(
        self,
        source: str,
        destination: str,
        container_name: str,
        backup_id: str,
        timeout: int,
    ) -> MountBackupInfo:
        """Backup a bind mount using a temporary alpine container."""
        safe_name = source.strip("/").replace("/", "_")
        tar_filename = f"bind_{safe_name}.tar.gz"
        backup_subdir = f"{container_name}/{backup_id}"

        helper = await asyncio.to_thread(
            self.client.containers.run,
            "alpine:latest",
            command=f"sh -c 'mkdir -p /backup/{backup_subdir} && tar czf /backup/{backup_subdir}/{tar_filename} -C /source .'",
            volumes={
                source: {"bind": "/source", "mode": "ro"},
                BACKUP_VOLUME_NAME: {"bind": "/backup", "mode": "rw"},
            },
            detach=True,
            auto_remove=False,
            name=f"tw-backup-{uuid.uuid4().hex[:8]}",
        )

        try:
            result = await asyncio.to_thread(helper.wait, timeout=timeout)
            if result["StatusCode"] != 0:
                logs = await asyncio.to_thread(helper.logs)
                raise RuntimeError(
                    f"Backup container exited with {result['StatusCode']}: "
                    f"{logs.decode('utf-8', errors='replace')}"
                )
        finally:
            try:
                await asyncio.to_thread(helper.remove, force=True)
            except Exception:
                pass  # Best-effort cleanup of temporary helper container

        local_tar = BACKUP_BASE_DIR / container_name / backup_id / tar_filename
        size = local_tar.stat().st_size if local_tar.exists() else 0

        return MountBackupInfo(
            mount_type="bind",
            source=source,
            destination=destination,
            tar_filename=tar_filename,
            size_bytes=size,
        )

    async def _backup_postgresql(
        self,
        container: docker.models.containers.Container,  # type: ignore[attr-defined]
        backup_dir: Path,
        pg_user: str,
        _timeout: int,
    ) -> None:
        """Backup PostgreSQL database using pg_dumpall.

        Args:
            container: Running PostgreSQL container.
            backup_dir: Local path to write dump file.
            pg_user: PostgreSQL user for pg_dumpall.
            _timeout: Operation timeout in seconds (reserved).
        """
        try:
            exit_code, output = await asyncio.to_thread(
                container.exec_run,
                f"pg_dumpall -U {pg_user}",
                demux=True,
            )
            if exit_code == 0 and output[0]:
                dump_path = backup_dir / "pg_dumpall.sql"
                dump_path.write_bytes(output[0])
                logger.info(
                    "PostgreSQL dump saved: %s (%d bytes)",
                    dump_path,
                    len(output[0]),
                )
            else:
                error_output = ""
                if output[1]:
                    error_output = output[1].decode("utf-8", errors="replace")
                logger.warning("pg_dumpall failed (exit %d): %s", exit_code, error_output)
        except Exception as e:
            logger.warning("PostgreSQL backup failed: %s", e)

    async def _get_pg_version(
        self,
        container: docker.models.containers.Container,  # type: ignore[attr-defined]
    ) -> str | None:
        """Get PostgreSQL major version from container.

        Args:
            container: Running PostgreSQL container.

        Returns:
            Version string (e.g., '16') or None.
        """
        try:
            exit_code, output = await asyncio.to_thread(
                container.exec_run,
                "postgres --version",
                demux=True,
            )
            if exit_code == 0 and output[0]:
                version_str = output[0].decode("utf-8", errors="replace").strip()
                # Parse "postgres (PostgreSQL) 16.2" -> "16"
                parts = version_str.split()
                for part in parts:
                    if part[0].isdigit():
                        return part.split(".")[0]
        except Exception as e:
            logger.debug("Failed to get PG version: %s", e)
        return None

    async def restore_backup(
        self,
        container_name: str,
        backup_id: str,
        storage_key: str | None = None,
    ) -> RestoreResult:
        """Restore a previous backup for a container.

        The target container should be stopped before calling this for
        bind mount restores. PostgreSQL restore requires the container
        to be running and is handled separately.

        Args:
            container_name: Docker runtime name for container operations.
            backup_id: ID of the backup to restore from.
            storage_key: Stable key for backup directory lookup (defaults to
                container_name for backward compatibility).

        Returns:
            RestoreResult with restore metadata.
        """
        key = storage_key or container_name
        lock = _get_container_lock(key)
        async with lock:
            return await self._restore_backup_impl(container_name, backup_id, key)

    async def _restore_backup_impl(
        self,
        container_name: str,
        backup_id: str,
        storage_key: str,
    ) -> RestoreResult:
        """Internal restore implementation (runs under lock)."""
        start_time = time.monotonic()
        backup_dir = self._get_backup_dir(storage_key, backup_id)
        metadata_path = backup_dir / "metadata.json"

        if not metadata_path.exists():
            return RestoreResult(
                backup_id=backup_id,
                container_name=container_name,
                status="failed",
                duration_seconds=time.monotonic() - start_time,
                error=f"Backup metadata not found at {metadata_path}",
            )

        with open(metadata_path) as f:
            metadata = json.load(f)

        mounts_restored = 0
        errors: list[str] = []

        for mount_info in metadata.get("mounts", []):
            if mount_info.get("error"):
                continue  # Skip mounts that failed during backup

            tar_filename = mount_info.get("tar_filename")
            if not tar_filename:
                continue

            mount_type = mount_info["type"]
            source = mount_info["source"]
            volume_name = mount_info.get("volume_name", "")

            tar_path = backup_dir / tar_filename
            if not tar_path.exists():
                logger.warning("Backup tarball not found: %s", tar_path)
                errors.append(f"{source}: tarball not found")
                continue

            try:
                await self._restore_mount(
                    tar_filename=tar_filename,
                    mount_type=mount_type,
                    source=source,
                    volume_name=volume_name,
                    container_name=container_name,
                    backup_id=backup_id,
                )
                mounts_restored += 1

            except Exception as e:
                logger.error("Failed to restore mount %s: %s", source, e)
                errors.append(f"{source}: {e}")

        duration = time.monotonic() - start_time

        if mounts_restored > 0 and not errors:
            status = "success"
        elif mounts_restored > 0:
            status = "partial"
        else:
            status = "failed"

        return RestoreResult(
            backup_id=backup_id,
            container_name=container_name,
            status=status,
            mounts_restored=mounts_restored,
            duration_seconds=duration,
            error="; ".join(errors) if errors else None,
        )

    async def _restore_mount(
        self,
        tar_filename: str,
        mount_type: str,
        source: str,
        volume_name: str,
        container_name: str,
        backup_id: str,
    ) -> None:
        """Restore a single mount from backup using staged approach.

        Uses staging directory to ensure crash-safe restore:
        1. Clean up leftover staging from previous attempts
        2. Extract to .restore-staging/
        3. Verify extraction succeeded
        4. Remove originals (excluding staging)
        5. Move staged files into place
        6. Clean up staging dir
        """
        backup_subdir = f"{container_name}/{backup_id}"

        # Build the staged restore command.
        # The mv commands use || true because dotfile or wildcard globs may
        # legitimately match nothing.  A final verification ensures at least
        # one item landed in /target (i.e. the staging dir was emptied).
        restore_cmd = (
            "sh -c '"
            "set -e && "
            "rm -rf /target/.restore-staging && "
            "mkdir -p /target/.restore-staging && "
            f"tar xzf /backup/{backup_subdir}/{tar_filename} -C /target/.restore-staging && "
            'test "$(ls -A /target/.restore-staging)" && '
            "find /target -mindepth 1 -maxdepth 1 ! -name .restore-staging -exec rm -rf {} + && "
            "mv /target/.restore-staging/* /target/ 2>/dev/null || true && "
            "mv /target/.restore-staging/.* /target/ 2>/dev/null || true && "
            "rmdir /target/.restore-staging 2>/dev/null || true && "
            # Verify: staging dir should be gone and target should have content
            "test ! -d /target/.restore-staging || "
            '  (echo "ERROR: staging dir still exists after restore" >&2 && exit 1) && '
            'test "$(ls -A /target)" || '
            '  (echo "ERROR: target dir empty after restore" >&2 && exit 1)'
            "'"
        )

        # Build volume spec for the restore container
        volumes = {
            BACKUP_VOLUME_NAME: {"bind": "/backup", "mode": "ro"},
        }

        if mount_type == "volume" and volume_name:
            volumes[volume_name] = {"bind": "/target", "mode": "rw"}
        else:
            volumes[source] = {"bind": "/target", "mode": "rw"}

        helper = await asyncio.to_thread(
            self.client.containers.run,
            "alpine:latest",
            command=restore_cmd,
            volumes=volumes,
            detach=True,
            auto_remove=False,
            name=f"tw-restore-{uuid.uuid4().hex[:8]}",
        )

        try:
            result = await asyncio.to_thread(helper.wait, timeout=300)
            if result["StatusCode"] != 0:
                logs = await asyncio.to_thread(helper.logs)
                raise RuntimeError(
                    f"Restore container exited with {result['StatusCode']}: "
                    f"{logs.decode('utf-8', errors='replace')}"
                )
        finally:
            try:
                await asyncio.to_thread(helper.remove, force=True)
            except Exception:
                pass  # Best-effort cleanup of temporary helper container

    async def restore_postgresql(
        self,
        container_name: str,
        backup_id: str,
    ) -> bool:
        """Restore PostgreSQL dump after container is running.

        Must be called AFTER docker compose up. Checks PG version
        compatibility before restoring.

        Args:
            container_name: Name of the PostgreSQL container.
            backup_id: ID of the backup to restore from.

        Returns:
            True if restore succeeded, False otherwise.
        """
        backup_dir = self._get_backup_dir(container_name, backup_id)
        metadata_path = backup_dir / "metadata.json"
        dump_path = backup_dir / "pg_dumpall.sql"

        if not dump_path.exists():
            logger.debug("No PostgreSQL dump found for %s/%s", container_name, backup_id)
            return False

        if not metadata_path.exists():
            logger.warning("No metadata for PG restore: %s/%s", container_name, backup_id)
            return False

        with open(metadata_path) as f:
            metadata = json.load(f)

        backup_pg_version = metadata.get("pg_version")
        pg_user = metadata.get("pg_user", "postgres")

        # Get current container
        try:
            container = await asyncio.to_thread(self.client.containers.get, container_name)
        except NotFound:
            logger.error("Container %s not found for PG restore", container_name)
            return False

        # Check version compatibility
        current_pg_version = await self._get_pg_version(container)

        if backup_pg_version and current_pg_version:
            if backup_pg_version != current_pg_version:
                logger.error(
                    "PG version mismatch for %s: backup=%s, current=%s. Skipping database restore.",
                    container_name,
                    backup_pg_version,
                    current_pg_version,
                )
                return False

        # Restore via psql: copy dump into container, then execute
        try:
            import tarfile
            from io import BytesIO

            dump_content = dump_path.read_bytes()

            # Create a tar archive containing the dump
            tar_stream = BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                dump_info = tarfile.TarInfo(name="pg_dumpall.sql")
                dump_info.size = len(dump_content)
                tar.addfile(dump_info, BytesIO(dump_content))
            tar_stream.seek(0)

            # Copy tar to container
            await asyncio.to_thread(container.put_archive, "/tmp", tar_stream.getvalue())

            # Execute psql with the dump file
            exit_code, output = await asyncio.to_thread(
                container.exec_run,
                f"sh -c 'psql -U {pg_user} < /tmp/pg_dumpall.sql'",
                demux=True,
            )

            if exit_code == 0:
                logger.info("PostgreSQL restore succeeded for %s", container_name)
                # Clean up
                await asyncio.to_thread(container.exec_run, "rm -f /tmp/pg_dumpall.sql")
                return True
            else:
                error_output = ""
                # demux=True returns (stdout_bytes, stderr_bytes) at runtime,
                # but the docker SDK stubs type `output` as `Iterator[bytes]`.
                if output and output[1]:  # type: ignore[index]
                    error_output = output[1].decode("utf-8", errors="replace")  # type: ignore[index,union-attr]
                logger.error(
                    "PostgreSQL restore failed for %s (exit %d): %s",
                    container_name,
                    exit_code,
                    error_output,
                )
                return False

        except Exception as e:
            logger.error("PostgreSQL restore exception for %s: %s", container_name, e)
            return False

    async def _check_backup_volume_space(self) -> int | None:
        """Check available space on the backup volume.

        Returns:
            Available bytes, or None if check fails.
        """
        try:
            helper = await asyncio.to_thread(
                self.client.containers.run,
                "alpine:latest",
                command="df -B1 /backup | tail -1 | awk '{print $4}'",
                volumes={BACKUP_VOLUME_NAME: {"bind": "/backup", "mode": "ro"}},
                remove=True,
            )
            output = helper.decode("utf-8", errors="replace").strip()
            return int(output)
        except Exception as e:
            logger.debug("Failed to check backup volume space: %s", e)
            return None

    def list_backups(self, container_name: str) -> list[dict]:
        """List all backups for a container.

        Args:
            container_name: Name of the container.

        Returns:
            List of backup metadata dicts, newest first.
        """
        container_dir = BACKUP_BASE_DIR / container_name
        if not container_dir.exists():
            return []

        backups = []
        for backup_dir in sorted(container_dir.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue
            metadata_path = backup_dir / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    backups.append(json.load(f))

        return backups

    def prune_backups(
        self, container_name: str, keep: int = 3, storage_key: str | None = None
    ) -> int:
        """Remove old backups, keeping the most recent N.

        Also removes any backup directories without valid metadata.

        Args:
            container_name: Container identifier (used for logging).
            keep: Number of recent backups to keep.
            storage_key: Stable key for backup directory lookup (defaults to
                container_name for backward compatibility).

        Returns:
            Number of backup sets removed.
        """
        import shutil

        container_dir = BACKUP_BASE_DIR / (storage_key or container_name)
        if not container_dir.exists():
            return 0

        # Separate valid (with metadata) from invalid directories
        valid_dirs: list[Path] = []
        invalid_dirs: list[Path] = []

        for d in container_dir.iterdir():
            if not d.is_dir():
                continue
            if (d / "metadata.json").exists():
                valid_dirs.append(d)
            else:
                invalid_dirs.append(d)

        # Sort valid dirs by modification time, newest first
        valid_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        removed = 0

        # Remove invalid/orphaned backup dirs
        for d in invalid_dirs:
            shutil.rmtree(d)
            removed += 1
            logger.info("Pruned orphaned backup dir: %s", d)

        # Remove oldest valid backups beyond the keep threshold
        for d in valid_dirs[keep:]:
            shutil.rmtree(d)
            removed += 1
            logger.info("Pruned old backup: %s", d)

        return removed

    def _save_metadata(self, backup_dir: Path, metadata: dict) -> None:
        """Save backup metadata to JSON file.

        Args:
            backup_dir: Directory to write metadata into.
            metadata: Metadata dict to serialize.
        """
        metadata_path = backup_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
