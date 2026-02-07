"""Update engine for applying container updates."""

import asyncio
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.history import UpdateHistory
from app.models.update import Update
from app.services.compose_parser import ComposeParser
from app.services.event_bus import event_bus
from app.services.registry_client import RegistryClientFactory
from app.services.settings_service import SettingsService
from app.utils.validators import (
    ValidationError,
    validate_compose_file_path,
    validate_docker_compose_command,
    validate_service_name,
)

logger = logging.getLogger(__name__)


class UpdateEngine:
    """Service for applying container updates."""

    @staticmethod
    def _translate_container_path_to_host(container_path: str) -> str:
        """Translate container-visible paths to host paths for docker compose.

        Docker compose runs on the host (via socket), so it needs host paths,
        not container paths.

        Args:
            container_path: Path as seen inside the Tidewatch container

        Returns:
            Equivalent path on the host system

        Raises:
            ValidationError: If path contains traversal attempts or is invalid
        """
        # Validate the path before translation
        try:
            validated_path = validate_compose_file_path(container_path, allowed_base="/compose")
        except ValidationError as e:
            logger.error(f"Path validation failed: {str(e)}")
            raise

        # Get the relative path from /compose/
        try:
            rel_path = validated_path.relative_to("/compose")
        except ValueError:
            raise ValidationError(f"Path {container_path} is not within /compose directory")

        # Construct safe host path
        host_base = Path("/srv/raid0/docker/compose")
        host_path = host_base / rel_path

        # Final safety check: ensure resolved path is still within host base
        try:
            host_path.resolve(strict=True).relative_to(host_base.resolve())
        except (ValueError, OSError) as e:
            raise ValidationError(f"Path traversal detected: {str(e)}")

        return str(host_path)

    @staticmethod
    async def _ensure_compose_project(db: AsyncSession, container: "Container") -> None:
        """Populate compose_project from Docker if not already set.

        Docker Compose containers have a 'com.docker.compose.project' label
        that indicates which project they belong to (e.g., 'homelab', 'proxies').
        This method queries Docker for that label and stores it in the database.

        Args:
            db: Database session
            container: Container to check/update
        """
        if container.compose_project:
            return

        try:
            import docker

            client = docker.from_env()
            docker_container = client.containers.get(container.name)
            project = docker_container.labels.get("com.docker.compose.project")

            if project:
                container.compose_project = project
                await db.commit()
                logger.info(f"Auto-populated compose_project={project} for {container.name}")
        except Exception as e:
            logger.debug(f"Could not get compose_project for {container.name}: {e}")

    @staticmethod
    async def apply_update(db: AsyncSession, update_id: int, triggered_by: str = "user") -> dict:
        """Apply an approved update.

        Args:
            db: Database session
            update_id: Update ID to apply
            triggered_by: Who triggered the update (username, "system", "scheduler")

        Returns:
            Result dict with success status
        """
        # Get the update
        result = await db.execute(select(Update).where(Update.id == update_id))
        update = result.scalar_one_or_none()

        if not update:
            raise ValueError(f"Update {update_id} not found")

        if update.status == "applied":
            raise ValueError("This update has already been applied")
        if update.status != "approved":
            raise ValueError(f"Update must be approved first (status: {update.status})")

        # Get the container
        result = await db.execute(select(Container).where(Container.id == update.container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise ValueError(f"Container {update.container_id} not found")

        # Concurrency guard: prevent overlapping operations on same container
        in_progress = await db.execute(
            select(UpdateHistory)
            .where(
                UpdateHistory.container_id == container.id,
                UpdateHistory.status == "in_progress",
            )
            .limit(1)
        )
        if in_progress.scalar_one_or_none():
            return {
                "success": False,
                "message": f"Another operation is already in progress for {container.name}",
            }

        # Ensure compose_project is populated from Docker labels
        await UpdateEngine._ensure_compose_project(db, container)

        logger.info(f"Applying update for {container.name}: {update.from_tag} -> {update.to_tag}")

        # Determine update type based on who triggered it
        if triggered_by == "scheduler":
            update_type = "auto"
        elif triggered_by == "system":
            update_type = "auto"
        else:
            update_type = "manual"

        # Ensure CVE data is loaded from database before accessing
        await db.refresh(update, ["cves_fixed"])  # Force load JSON column
        cves_data = update.cves_fixed if update.cves_fixed is not None else []

        # Sanity check for the specific failure mode where security updates have empty CVE data
        if cves_data == [] and update.reason_type == "security":
            # Check if the source Update record actually has CVE data
            await db.refresh(update)  # Full refresh of all columns
            if update.cves_fixed:
                cves_data = update.cves_fixed
                logger.warning(
                    f"Had to force-reload CVE data for update {update.id}. "
                    f"This indicates a JSON column deserialization issue."
                )
            else:
                logger.warning(
                    f"Security update {update.id} has no CVE data even after full refresh. "
                    f"This may indicate VulnForge enrichment failed during update detection."
                )

        logger.info(
            f"Creating UpdateHistory for {container.name}: {len(cves_data)} CVEs will be recorded"
        )

        # Create history record
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag=update.from_tag,
            to_tag=update.to_tag,
            update_id=update.id,
            update_type=update_type,  # Auto or manual update
            event_type="update",  # Set event_type for proper display in history
            status="in_progress",
            triggered_by=triggered_by,  # Track who triggered the update
            reason=update.reason_summary,
            reason_type=update.reason_type,
            reason_summary=update.reason_summary,
            cves_fixed=cves_data,
        )
        db.add(history)
        await db.commit()

        await event_bus.publish(
            {
                "type": "update-progress",
                "container_id": container.id,
                "container_name": container.name,
                "history_id": history.id,
                "phase": "starting",
                "progress": 0.05,
                "status": "in_progress",
                "from_tag": update.from_tag,
                "to_tag": update.to_tag,
            }
        )

        try:
            # Step 1: Backup current compose file
            backup_path = await UpdateEngine._backup_compose_file(container.compose_file)
            history.backup_path = backup_path
            await db.commit()

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "backup",
                    "progress": 0.1,
                    "status": "in_progress",
                    "message": "Compose file backup created",
                }
            )

            # Step 1.5: Pre-update data backup (best-effort, non-blocking)
            try:
                from app.services.data_backup_service import DataBackupService

                backup_service = DataBackupService()
                data_backup_result = await backup_service.create_backup(
                    container.name, timeout_seconds=300
                )
                history.data_backup_id = data_backup_result.backup_id
                history.data_backup_status = data_backup_result.status
                await db.commit()

                await event_bus.publish(
                    {
                        "type": "update-progress",
                        "container_id": container.id,
                        "container_name": container.name,
                        "history_id": history.id,
                        "phase": "data-backup",
                        "progress": 0.2,
                        "status": "in_progress",
                        "step_id": "data_backup",
                        "duration_ms": int(data_backup_result.duration_seconds * 1000),
                        "error_code": (
                            "BACKUP_FAILED" if data_backup_result.status == "failed" else None
                        ),
                        "message": (
                            f"Data backup: {data_backup_result.status} "
                            f"({data_backup_result.mounts_backed_up} mounts)"
                        ),
                    }
                )

                if data_backup_result.status == "failed":
                    logger.warning(
                        "Data backup failed for %s: %s. Continuing with update.",
                        container.name,
                        data_backup_result.error,
                    )
            except Exception as backup_err:
                logger.warning(
                    "Data backup exception for %s: %s. Continuing with update.",
                    container.name,
                    backup_err,
                )
                history.data_backup_status = "failed"
                await db.commit()

            # Step 2: Update compose file
            success = await ComposeParser.update_compose_file(
                container.compose_file, container.service_name, update.to_tag, db
            )

            if not success:
                raise Exception("Failed to update compose file")

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "compose-updated",
                    "progress": 0.3,
                    "status": "in_progress",
                    "message": f"Updated compose to {update.to_tag}",
                }
            )

            # Step 3: Pull the new image (separate step with longer timeout)
            docker_socket = await SettingsService.get(db, "docker_socket") or "/var/run/docker.sock"
            docker_compose_cmd = (
                await SettingsService.get(db, "docker_compose_command", "docker compose")
                or "docker compose"
            )

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "pulling",
                    "progress": 0.35,
                    "status": "in_progress",
                    "message": "Pulling new image...",
                }
            )

            pull_result = await UpdateEngine._pull_docker_image(
                container.compose_file,
                container.service_name,
                docker_socket,
                docker_compose_cmd,
                container.compose_project,
            )

            if not pull_result["success"]:
                raise Exception(f"Image pull failed: {pull_result['error']}")

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "pulled",
                    "progress": 0.5,
                    "status": "in_progress",
                    "message": "Image pulled successfully",
                }
            )

            # Step 4: Execute docker compose up (now quick since image is pulled)
            result = await UpdateEngine._execute_docker_compose(
                container.compose_file,
                container.service_name,
                docker_socket,
                docker_compose_cmd,
                container.compose_project,
            )

            if not result["success"]:
                raise Exception(f"Docker compose failed: {result['error']}")

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "deploying",
                    "progress": 0.7,
                    "status": "in_progress",
                    "message": "Container deployed",
                }
            )

            # Step 4: Validate container health
            health_check_result = await UpdateEngine._validate_health_check(
                container, timeout=60, db=db
            )

            if not health_check_result["success"]:
                raise Exception(
                    f"Health check failed: {health_check_result.get('error', 'Unknown error')}"
                )

            logger.info(
                f"Health check passed for {container.name} "
                f"(method: {health_check_result.get('method')})"
            )

            await event_bus.publish(
                {
                    "type": "update-progress",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "phase": "health-check",
                    "progress": 0.8,
                    "status": "in_progress",
                    "message": "Health check passed",
                }
            )

            # Trigger VulnForge rescan (fire-and-forget)
            # This runs in the background and doesn't block the update
            # Pass update_id so we can store CVE delta results when scan completes
            asyncio.create_task(UpdateEngine._trigger_vulnforge_rescan(container.name, update.id))

            # Success! Wrap status updates in transaction for atomicity
            async with db.begin_nested():
                update.status = "applied"
                update.version += 1  # Increment version for optimistic locking
                container.current_tag = update.to_tag

                if container.current_tag == "latest":
                    new_digest_value: str | None = None
                    if update.changelog:
                        try:
                            changelog_data = json.loads(update.changelog)
                            if isinstance(changelog_data, dict):
                                new_digest_value = changelog_data.get("to_digest")
                        except json.JSONDecodeError:
                            new_digest_value = None

                    if not new_digest_value:
                        new_digest_value = await UpdateEngine._fetch_latest_digest(container, db)

                    if new_digest_value:
                        container.current_digest = new_digest_value

                container.update_available = False
                container.latest_tag = None
                container.last_updated = datetime.now(UTC)

                history.status = "success"
                history.completed_at = datetime.now(UTC)
                history.can_rollback = True

            await db.commit()

            # Send notifications via dispatcher (handles all enabled services)
            from app.services.notifications.dispatcher import NotificationDispatcher

            dispatcher = NotificationDispatcher(db)
            await dispatcher.notify_update_applied(
                container.name,
                update.to_tag,
                success=True,
                reason_type=update.reason_type,
                reason_summary=update.reason_summary,
            )

            logger.info(f"Successfully updated {container.name} to {update.to_tag}")

            # Prune old backups (keep 3 most recent, fire-and-forget)
            try:
                from app.services.data_backup_service import DataBackupService

                backup_service = DataBackupService()
                pruned = await asyncio.to_thread(
                    backup_service.prune_backups, container.name, 3
                )
                if pruned:
                    logger.info("Pruned %d old backup(s) for %s", pruned, container.name)
            except Exception as prune_err:
                logger.debug("Backup pruning failed for %s: %s", container.name, prune_err)

            await event_bus.publish(
                {
                    "type": "update-complete",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "status": "success",
                    "from_tag": update.from_tag,
                    "to_tag": update.to_tag,
                }
            )

            return {
                "success": True,
                "message": f"Updated {container.name} to {update.to_tag}",
                "history_id": history.id,
            }

        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"{error_type} during update of {container.name}: {e}")
            return await UpdateEngine._handle_update_failure(db, update, container, history, e)

    @staticmethod
    async def _handle_update_failure(
        db: AsyncSession,
        update: Update,
        container: Container,
        history: UpdateHistory,
        error: Exception,
    ) -> dict:
        """Handle update failure: restore compose, manage retries, and notify.

        Centralizes all error handling for apply_update() to eliminate
        duplication across exception types.

        Args:
            db: Database session
            update: The update record
            container: The container being updated
            history: The update history record
            error: The exception that caused the failure

        Returns:
            Failure result dict
        """
        # Restore compose file from backup (single attempt, no double-restore)
        if history.backup_path:
            try:
                await UpdateEngine._restore_compose_file(
                    container.compose_file, history.backup_path
                )
            except (OSError, PermissionError) as restore_error:
                logger.error(f"Failed to restore compose backup: {restore_error}")

        # Update retry logic - wrap in transaction for atomicity
        async with db.begin_nested():
            update.last_error = str(error)
            update.retry_count = (update.retry_count or 0) + 1
            update.version += 1  # Increment version for optimistic locking

            # Calculate next retry time using exponential backoff
            if update.retry_count < (update.max_retries or 3):
                # Backoff schedule: 5min, 15min, 1hr, 4hrs
                backoff_multiplier = update.backoff_multiplier or 3
                if update.retry_count == 1:
                    delay_minutes = 5
                elif update.retry_count == 2:
                    delay_minutes = 15
                elif update.retry_count == 3:
                    delay_minutes = 60
                else:
                    delay_minutes = 60 * int(backoff_multiplier) ** (int(update.retry_count) - 3)

                from datetime import timedelta

                update.next_retry_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
                update.status = "pending_retry"

                logger.info(
                    f"Update will be retried in {delay_minutes} minutes "
                    f"(attempt {update.retry_count + 1}/{update.max_retries or 3})"
                )
            else:
                # Max retries reached - attempt automatic rollback
                update.next_retry_at = None
                logger.warning(
                    f"Max retries ({update.max_retries or 3}) reached for "
                    f"update {update.id}, initiating automatic rollback"
                )

                if history.backup_path:
                    try:
                        # Mark history as failed BEFORE rollback attempt so the
                        # concurrency guard (checks for in_progress) and status
                        # check (requires success|failed) in rollback_update() pass.
                        history.status = "failed"
                        history.error_message = str(error)
                        history.completed_at = datetime.now(UTC)
                        history.can_rollback = True
                        await db.flush()

                        logger.info(f"Attempting automatic rollback for update {update.id}")
                        rollback_result = await UpdateEngine.rollback_update(db, history.id)
                        if rollback_result["success"]:
                            update.status = "rolled_back"
                            update.last_error = (
                                f"Auto-rolled back after {update.retry_count} failed retry attempts"
                            )
                            logger.info(f"Successfully auto-rolled back update {update.id}")
                        else:
                            update.status = "failed"
                            update.last_error = (
                                f"Max retries reached. Auto-rollback failed: "
                                f"{rollback_result.get('message', 'Unknown error')}"
                            )
                            logger.error(
                                f"Auto-rollback failed for update {update.id}: "
                                f"{rollback_result.get('message')}"
                            )
                    except Exception as rollback_error:
                        update.status = "failed"
                        update.last_error = (
                            f"Max retries reached. Auto-rollback failed: {rollback_error}"
                        )
                        logger.error(
                            f"Auto-rollback exception for update {update.id}: {rollback_error}"
                        )
                else:
                    update.status = "failed"
                    update.last_error = (
                        f"Max retries ({update.retry_count}) reached. "
                        f"No backup available for auto-rollback."
                    )
                    logger.warning(f"No backup available for auto-rollback of update {update.id}")

            # Update history record (skip if already set by successful auto-rollback)
            if history.status != "rolled_back":
                history.status = "failed"
                history.error_message = str(error)
                history.completed_at = datetime.now(UTC)
                history.can_rollback = bool(history.backup_path)

        await db.commit()

        await event_bus.publish(
            {
                "type": "update-complete",
                "container_id": container.id,
                "container_name": container.name,
                "history_id": history.id,
                "status": "failed",
                "message": str(error),
                "from_tag": update.from_tag,
                "to_tag": update.to_tag,
            }
        )

        # Send failure notification
        from app.services.notifications.dispatcher import NotificationDispatcher

        dispatcher = NotificationDispatcher(db)
        await dispatcher.notify_update_applied(
            container.name,
            update.to_tag,
            success=False,
            reason_type=update.reason_type,
            reason_summary=update.reason_summary,
        )

        return {
            "success": False,
            "message": f"Failed to update {container.name}: {error}",
            "error": str(error),
            "history_id": history.id,
        }

    @staticmethod
    async def rollback_update(db: AsyncSession, history_id: int) -> dict:
        """Rollback a previous update.

        Args:
            db: Database session
            history_id: History ID to rollback

        Returns:
            Result dict
        """
        # Get the history record
        result = await db.execute(select(UpdateHistory).where(UpdateHistory.id == history_id))
        history = result.scalar_one_or_none()

        if not history:
            raise ValueError(f"History {history_id} not found")

        if not history.can_rollback:
            raise ValueError("This update cannot be rolled back")

        if history.rolled_back_at:
            raise ValueError("This update has already been rolled back")

        # Allow rollback of both successful and failed updates (if backup exists)
        if history.status not in ("success", "failed"):
            raise ValueError(
                f"Cannot rollback {history.status} update - only successful or failed updates can be rolled back"
            )

        # Get the container
        result = await db.execute(select(Container).where(Container.id == history.container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise ValueError(f"Container {history.container_id} not found")

        # Concurrency guard: prevent overlapping operations on same container
        in_progress = await db.execute(
            select(UpdateHistory)
            .where(
                UpdateHistory.container_id == container.id,
                UpdateHistory.status == "in_progress",
            )
            .limit(1)
        )
        if in_progress.scalar_one_or_none():
            return {
                "success": False,
                "message": f"Another operation is already in progress for {container.name}",
            }

        # Verify the container is still at the expected version
        if container.current_tag != history.to_tag:
            raise ValueError(
                f"Cannot rollback: container is at {container.current_tag}, "
                f"expected {history.to_tag}. The container may have been updated again."
            )

        logger.info(f"Rolling back {container.name}: {history.to_tag} -> {history.from_tag}")

        await event_bus.publish(
            {
                "type": "rollback-started",
                "container_id": container.id,
                "container_name": container.name,
                "history_id": history.id,
                "from_tag": history.to_tag,
                "to_tag": history.from_tag,
            }
        )

        try:
            # Step 1: Update compose file back to old tag
            success = await ComposeParser.update_compose_file(
                container.compose_file, container.service_name, history.from_tag, db
            )

            if not success:
                raise Exception("Failed to update compose file")

            # Step 1.5: Stop container, then restore data from backup
            data_restore_status = None
            if history.data_backup_id and history.data_backup_status == "success":
                # Stop the container BEFORE restoring data to avoid corruption
                try:
                    import docker
                    from docker.errors import NotFound as DockerNotFound

                    docker_socket = (
                        await SettingsService.get(db, "docker_socket") or "/var/run/docker.sock"
                    )
                    docker_client = docker.DockerClient(base_url=docker_socket)
                    try:
                        target = await asyncio.to_thread(
                            docker_client.containers.get, container.name
                        )
                        await asyncio.to_thread(target.stop, timeout=30)
                        logger.info("Stopped %s before data restore", container.name)
                    except DockerNotFound:
                        logger.debug("Container %s not found (may not be running)", container.name)
                    except Exception as stop_err:
                        logger.warning(
                            "Failed to stop %s before data restore: %s. "
                            "Proceeding anyway.",
                            container.name,
                            stop_err,
                        )
                    finally:
                        docker_client.close()
                except Exception as docker_err:
                    logger.warning("Docker client error during pre-restore stop: %s", docker_err)

                # Now restore data with the container stopped
                try:
                    from app.services.data_backup_service import DataBackupService

                    backup_service = DataBackupService()
                    restore_result = await backup_service.restore_backup(
                        container.name, history.data_backup_id
                    )
                    data_restore_status = restore_result.status
                    if restore_result.status == "success":
                        logger.info(
                            "Data restore completed for %s (backup %s): %d mounts restored",
                            container.name,
                            history.data_backup_id,
                            restore_result.mounts_restored,
                        )
                    else:
                        logger.warning(
                            "Data restore %s for %s: %s. Continuing with image-only rollback.",
                            restore_result.status,
                            container.name,
                            restore_result.error,
                        )
                except Exception as restore_err:
                    data_restore_status = "failed"
                    logger.warning(
                        "Data restore exception for %s: %s. Continuing with image-only rollback.",
                        container.name,
                        restore_err,
                    )
            else:
                logger.info(
                    "No data backup available for %s rollback "
                    "(backup_id=%s, status=%s). Proceeding with image-only rollback.",
                    container.name,
                    history.data_backup_id,
                    history.data_backup_status,
                )

            # Step 2: Execute docker compose (stop + up -d)
            docker_socket = await SettingsService.get(db, "docker_socket") or "/var/run/docker.sock"
            docker_compose_cmd = (
                await SettingsService.get(db, "docker_compose_command", "docker compose")
                or "docker compose"
            )
            result = await UpdateEngine._execute_docker_compose(
                container.compose_file,
                container.service_name,
                docker_socket,
                docker_compose_cmd,
                container.compose_project,
            )
            if not result["success"]:
                raise Exception(f"Docker compose failed: {result['error']}")

            # Step 2.5: Post-compose-up PostgreSQL restore (if applicable)
            # DB needs to be running, so this happens after compose up
            if data_restore_status == "success" and history.data_backup_id:
                try:
                    from app.services.data_backup_service import DataBackupService

                    backup_service = DataBackupService()
                    pg_restored = await backup_service.restore_postgresql(
                        container.name, history.data_backup_id
                    )
                    if pg_restored:
                        logger.info(
                            "PostgreSQL database restored for %s",
                            container.name,
                        )
                except Exception as pg_err:
                    logger.warning(
                        "PostgreSQL post-up restore exception for %s: %s",
                        container.name,
                        pg_err,
                    )

            # Success! Wrap status updates in transaction for atomicity
            async with db.begin_nested():
                container.current_tag = history.from_tag
                container.last_updated = datetime.now(UTC)

                history.rolled_back_at = datetime.now(UTC)
                history.status = "rolled_back"

            await db.commit()

            await event_bus.publish(
                {
                    "type": "rollback-complete",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "status": "success",
                    "to_tag": history.from_tag,
                }
            )

            # Send notifications via dispatcher (handles all enabled services)
            from app.services.notifications.dispatcher import NotificationDispatcher

            dispatcher = NotificationDispatcher(db)
            await dispatcher.notify_rollback(container.name, history.to_tag)

            logger.info(f"Successfully rolled back {container.name} to {history.from_tag}")

            return {
                "success": True,
                "message": f"Rolled back {container.name} to {history.from_tag}",
            }

        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"{error_type} during rollback of {container.name}: {e}")
            await event_bus.publish(
                {
                    "type": "rollback-complete",
                    "container_id": container.id,
                    "container_name": container.name,
                    "history_id": history.id,
                    "status": "failed",
                    "message": str(e),
                }
            )
            return {
                "success": False,
                "message": f"Failed to rollback {container.name}: {str(e)}",
                "error": str(e),
            }

    @staticmethod
    async def _validate_health_check(
        container: Container, timeout: int = 60, db: AsyncSession | None = None
    ) -> dict:
        """Validate container health after update."""
        import time

        import httpx

        from app.services.settings_service import SettingsService

        service_name = container.name
        health_check_url = container.health_check_url
        method = (container.health_check_method or "auto").lower()
        if method not in {"auto", "http", "docker"}:
            method = "auto"

        should_use_http = bool(health_check_url) and method in {"auto", "http"}
        if not should_use_http:
            return await UpdateEngine._check_container_runtime(container)

        logger.info(f"Performing health check for {service_name}: {health_check_url}")

        # Get configurable retry settings
        base_delay = 5  # Default fallback
        use_exponential_backoff = True
        max_delay = 30
        if db:
            base_delay = await SettingsService.get_int(db, "health_check_retry_delay", default=5)
            use_exponential_backoff = await SettingsService.get_bool(
                db, "health_check_use_exponential_backoff", default=True
            )
            max_delay = await SettingsService.get_int(db, "health_check_max_delay", default=30)

        start_time = time.time()
        # Calculate max_retries based on total timeout
        # With exponential backoff: 5, 10, 20, 30, 30... seconds
        # Without: 5, 5, 5... seconds
        if use_exponential_backoff:
            # Estimate retries: sum of geometric series until max_delay, then constant
            total_time = 0
            delay = base_delay
            retries = 0
            while total_time < timeout:
                total_time += delay
                retries += 1
                delay = min(delay * 2, max_delay)
            max_retries = max(retries, 1)
        else:
            max_retries = max(timeout // base_delay, 1)

        for attempt in range(max_retries):
            try:
                headers = {}
                url = str(health_check_url)
                if container.health_check_auth:
                    auth_value = container.health_check_auth.strip()
                    lower_value = auth_value.lower()
                    if lower_value.startswith("header:"):
                        _, value = auth_value.split(":", 1)
                        if "=" in value:
                            header_key, header_value = value.split("=", 1)
                            headers[header_key.strip()] = header_value.strip()
                    elif lower_value.startswith("token:"):
                        _, token = auth_value.split(":", 1)
                        headers["Authorization"] = token.strip()
                    else:
                        # Parse URL to safely add query parameters
                        parsed_url = urlparse(url)
                        query_params = parse_qs(parsed_url.query)

                        # Validate and add auth parameter
                        if "=" in auth_value:
                            # Format: key=value
                            parts = auth_value.split("=", 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                                # Validate key contains only alphanumeric and underscore
                                if key and value and key.replace("_", "").isalnum():
                                    query_params[key] = [value]
                                else:
                                    logger.warning(f"Invalid auth parameter format: {auth_value}")
                        else:
                            # Default to apikey parameter
                            value = auth_value.strip()
                            if value:
                                query_params["apikey"] = [value]

                        # Safely reconstruct URL with encoded parameters
                        encoded_query = urlencode(query_params, doseq=True)
                        url = urlunparse(
                            (
                                parsed_url.scheme,
                                parsed_url.netloc,
                                parsed_url.path,
                                parsed_url.params,
                                encoded_query,
                                parsed_url.fragment,
                            )
                        )

                logger.info(f"Health check for {service_name}: URL={url}, Headers={headers}")
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, timeout=5.0, headers=headers or None)
                    if response.status_code == 200:
                        elapsed = time.time() - start_time
                        logger.info(
                            f"Health check passed for {service_name} after {elapsed:.1f}s "
                            f"(status: {response.status_code})"
                        )
                        return {
                            "success": True,
                            "method": "http_check",
                            "status_code": response.status_code,
                            "elapsed_seconds": elapsed,
                        }

                    # Non-200 status code - retry with backoff
                    logger.warning(
                        f"Health check returned {response.status_code} for {service_name} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )

                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff if enabled
                        if use_exponential_backoff:
                            current_delay = min(base_delay * (2**attempt), max_delay)
                        else:
                            current_delay = base_delay

                        logger.debug(f"Retrying health check in {current_delay}s...")
                        await asyncio.sleep(current_delay)

            except httpx.HTTPStatusError as e:
                if attempt < max_retries - 1:
                    # Calculate delay with exponential backoff if enabled
                    if use_exponential_backoff:
                        current_delay = min(base_delay * (2**attempt), max_delay)
                    else:
                        current_delay = base_delay

                    logger.debug(
                        f"Health check HTTP error (status {e.response.status_code}): {e}, "
                        f"retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                else:
                    elapsed = time.time() - start_time
                    logger.warning(
                        f"HTTP health check failed after {elapsed:.1f}s with status {e.response.status_code}, "
                        f"falling back to Docker inspect"
                    )

                    # Fall back to Docker inspect to verify container is actually unhealthy
                    docker_check = await UpdateEngine._check_container_runtime(container)
                    if docker_check["success"]:
                        logger.info(
                            f"Container {service_name} is running despite HTTP errors, "
                            f"marking health check as passed"
                        )
                        return {
                            "success": True,
                            "method": "docker_inspect_fallback",
                            "elapsed_seconds": elapsed,
                            "note": f"HTTP check failed ({str(e)}) but container is running",
                        }

                    docker_error = docker_check.get("error", "Container is not running")
                    logger.error(
                        f"Health check failed after {elapsed:.1f}s. "
                        f"HTTP error: {e}. Docker status: {docker_error}"
                    )
                    return {
                        "success": False,
                        "method": "docker_inspect",
                        "error": docker_error,
                        "http_error": str(e),
                        "elapsed_seconds": elapsed,
                    }

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    if use_exponential_backoff:
                        current_delay = min(base_delay * (2**attempt), max_delay)
                    else:
                        current_delay = base_delay

                    logger.debug(
                        f"Health check connection/timeout error: {e}, "
                        f"retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                else:
                    elapsed = time.time() - start_time
                    logger.warning(
                        f"HTTP health check failed after {elapsed:.1f}s: {e}, "
                        f"falling back to Docker inspect"
                    )

                    docker_check = await UpdateEngine._check_container_runtime(container)
                    if docker_check["success"]:
                        logger.info(
                            f"Container {service_name} is running despite HTTP errors, "
                            f"marking health check as passed"
                        )
                        return {
                            "success": True,
                            "method": "docker_inspect_fallback",
                            "elapsed_seconds": elapsed,
                            "note": f"HTTP check failed ({str(e)}) but container is running",
                        }

                    docker_error = docker_check.get("error", "Container is not running")
                    logger.error(
                        f"Health check failed after {elapsed:.1f}s. "
                        f"HTTP error: {e}. Docker status: {docker_error}"
                    )
                    return {
                        "success": False,
                        "method": "docker_inspect",
                        "error": docker_error,
                        "http_error": str(e),
                        "elapsed_seconds": elapsed,
                    }

            except (ValueError, KeyError) as e:
                if attempt < max_retries - 1:
                    if use_exponential_backoff:
                        current_delay = min(base_delay * (2**attempt), max_delay)
                    else:
                        current_delay = base_delay

                    logger.debug(f"Health check data error: {e}, retrying in {current_delay}s...")
                    await asyncio.sleep(current_delay)
                else:
                    elapsed = time.time() - start_time
                    logger.warning(
                        f"HTTP health check data error after {elapsed:.1f}s: {e}, "
                        f"falling back to Docker inspect"
                    )

                    docker_check = await UpdateEngine._check_container_runtime(container)
                    if docker_check["success"]:
                        logger.info(
                            f"Container {service_name} is running despite HTTP errors, "
                            f"marking health check as passed"
                        )
                        return {
                            "success": True,
                            "method": "docker_inspect_fallback",
                            "elapsed_seconds": elapsed,
                            "note": f"HTTP check failed ({str(e)}) but container is running",
                        }

                    docker_error = docker_check.get("error", "Container is not running")
                    logger.error(
                        f"Health check failed after {elapsed:.1f}s. "
                        f"Data error: {e}. Docker status: {docker_error}"
                    )
                    return {
                        "success": False,
                        "method": "docker_inspect",
                        "error": docker_error,
                        "http_error": str(e),
                        "elapsed_seconds": elapsed,
                    }

        elapsed = time.time() - start_time
        logger.warning(
            f"HTTP health check timed out after {elapsed:.1f}s for {service_name}, "
            f"falling back to Docker inspect"
        )

        # Fall back to Docker inspect to verify container is actually unhealthy
        docker_check = await UpdateEngine._check_container_runtime(container)
        if docker_check["success"]:
            logger.info(
                f"Container {service_name} is running despite HTTP timeout, "
                f"marking health check as passed"
            )
            return {
                "success": True,
                "method": "docker_inspect_fallback",
                "elapsed_seconds": elapsed,
                "note": "HTTP check timed out but container is running",
            }

        # Container is actually not running
        logger.error(f"Health check failed after {elapsed:.1f}s for {service_name}")
        return {
            "success": False,
            "method": "http_check",
            "error": f"Health check timed out after {timeout}s and container is not running",
            "elapsed_seconds": elapsed,
        }

    @staticmethod
    async def _check_container_runtime(container: Container) -> dict:
        """Check container status via docker inspect instead of HTTP."""
        inspect_targets: list[str] = []
        resolved_name = await UpdateEngine._resolve_container_runtime_name(container)
        if resolved_name:
            inspect_targets.append(resolved_name)
        if container.name not in inspect_targets:
            inspect_targets.append(container.name)

        last_error = None
        for target in inspect_targets:
            # Validate container name to prevent command injection
            try:
                validate_service_name(target)
            except ValidationError as e:
                logger.warning(f"Invalid container name '{target}': {e}, skipping for security")
                continue

            try:
                # Use async subprocess to avoid blocking
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}}",
                    target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(), timeout=10
                    )
                    stdout = stdout_bytes.decode("utf-8").strip() if stdout_bytes else ""

                    if process.returncode == 0:
                        status = stdout
                        if status == "running":
                            logger.info(
                                f"Container {target} is running (docker inspect health check)"
                            )
                            return {
                                "success": True,
                                "method": "docker_inspect",
                                "container": target,
                            }

                        logger.warning(f"Container {target} status: {status}")
                        return {
                            "success": False,
                            "error": f"Container status: {status}",
                            "container": target,
                        }

                    stderr = stderr_bytes.decode("utf-8").strip() if stderr_bytes else ""
                    last_error = stderr or "Failed to inspect container"
                    logger.error(f"Failed to inspect container {target}: {stderr}")

                except TimeoutError:
                    last_error = "Container inspection timed out"
                    logger.error(f"Timeout inspecting container {target}")

            except subprocess.CalledProcessError as e:
                last_error = f"Docker command failed: {str(e)}"
                logger.error(f"Docker inspect command failed for {target}: {e}")
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                last_error = f"Invalid Docker response: {str(e)}"
                logger.error(f"Failed to parse Docker inspect output for {target}: {e}")

        return {
            "success": False,
            "error": last_error or "Unable to inspect container",
            "method": "docker_inspect",
        }

    @staticmethod
    async def _resolve_container_runtime_name(container: Container) -> str | None:
        """Attempt to resolve the actual Docker container name for a compose service."""
        try:
            base_filters = [
                "--filter",
                f"label=com.docker.compose.service={container.service_name}",
            ]

            filter_sets = [base_filters]

            if container.compose_file:
                project_name = Path(container.compose_file).parent.name
                project_filters = base_filters + [
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                ]
                filter_sets.insert(0, project_filters)

            for filters in filter_sets:
                cmd = ["docker", "ps", "--all", "--format", "{{.Names}}", *filters]

                # Use async subprocess to avoid blocking
                try:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(), timeout=10
                    )

                    if process.returncode != 0:
                        stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
                        logger.debug(
                            f"docker ps failed for service {container.service_name}: {stderr}"
                        )
                        continue

                    stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
                    names = [line.strip() for line in stdout.splitlines() if line.strip()]
                    if names:
                        return names[0]

                except TimeoutError:
                    logger.debug(f"Timeout resolving container name for {container.service_name}")
                    continue

        except subprocess.CalledProcessError as e:
            logger.debug(
                f"Docker command failed resolving container name for {container.name}: {e}"
            )
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.debug(
                f"Invalid Docker response resolving container name for {container.name}: {e}"
            )

        return None

    @staticmethod
    async def _fetch_latest_digest(container: Container, db: AsyncSession) -> str | None:
        """Fetch the current digest for a 'latest' tag from the registry.

        Args:
            container: Container to fetch digest for
            db: Database session

        Returns:
            Digest string or None if fetch fails
        """
        registry_client = None
        try:
            # Get registry credentials if needed
            registry = container.registry

            # Create registry client (correct parameters)
            registry_client = await RegistryClientFactory.get_client(registry=registry, db=db)

            # Fetch metadata which includes digest
            metadata = await registry_client.get_tag_metadata(
                container.image, container.current_tag
            )

            if metadata and metadata.get("digest"):
                digest = metadata["digest"]
                logger.info(f"Fetched latest digest for {container.name}: {digest[:16]}...")
                return digest
            else:
                logger.warning(f"Could not fetch digest for {container.name} from {registry}")
                return None

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching digest for {container.name}: {e.response.status_code}"
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"Connection error fetching digest for {container.name}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid registry data for {container.name}: {e}")
            return None
        finally:
            # Close the HTTP client to prevent resource leaks
            if registry_client:
                await registry_client.close()

    @staticmethod
    async def _backup_compose_file(compose_file: str) -> str:
        """Create a backup of the compose file.

        Args:
            compose_file: Path to compose file

        Returns:
            Path to backup file
        """
        import os
        import shutil

        # Store backups in /data directory (writable), not in /compose (read-only)
        backup_dir = "/data/backups"
        os.makedirs(backup_dir, exist_ok=True)

        # Create backup filename from original path (single backup per file, overwrites previous)
        compose_basename = os.path.basename(compose_file)
        backup_filename = f"{compose_basename}.backup"
        backup_path = os.path.join(backup_dir, backup_filename)

        try:
            shutil.copy2(compose_file, backup_path)
            logger.info(f"Created backup: {backup_path}")
            return backup_path
        except PermissionError as e:
            logger.error(f"Permission denied creating backup: {e}")
            raise
        except OSError as e:
            logger.error(f"File system error creating backup: {e}")
            raise

    @staticmethod
    async def _restore_compose_file(compose_file: str, backup_path: str):
        """Restore compose file from backup.

        Args:
            compose_file: Path to compose file
            backup_path: Path to backup file
        """
        try:
            import shutil

            shutil.copy2(backup_path, compose_file)
            logger.info(f"Restored from backup: {backup_path}")
        except PermissionError as e:
            logger.error(f"Permission denied restoring backup: {e}")
            raise
        except OSError as e:
            logger.error(f"File system error restoring backup: {e}")
            raise

    @staticmethod
    async def _execute_docker_compose(
        compose_file: str,
        service_name: str,
        docker_socket: str = "/var/run/docker.sock",
        compose_command: str = "docker compose",
        compose_project: str | None = None,
    ) -> dict:
        """Execute docker compose up for a service.

        Args:
            compose_file: Path to compose file
            service_name: Service name to update
            docker_socket: Docker socket path
            compose_command: Docker compose command template with placeholders
            compose_project: Docker Compose project name (e.g., 'homelab', 'proxies')

        Returns:
            Result dict with success status
        """
        # Validate service name to prevent command injection
        try:
            validated_service = validate_service_name(service_name)
        except ValidationError as e:
            logger.error(f"Invalid service name '{service_name}': {str(e)}")
            return {
                "success": False,
                "error": f"Invalid service name: {str(e)}",
                "stdout": "",
            }

        # Validate compose file path
        try:
            validated_compose_path = validate_compose_file_path(
                compose_file, allowed_base="/compose"
            )
            # Translate container path to host path for docker daemon
            host_compose_path = UpdateEngine._translate_container_path_to_host(
                str(validated_compose_path)
            )
        except ValidationError as e:
            logger.error(f"Invalid compose file path '{compose_file}': {str(e)}")
            return {
                "success": False,
                "error": f"Invalid compose file path: {str(e)}",
                "stdout": "",
            }

        try:
            # Check for .env file in the same directory as compose file (use host path)
            import os

            host_compose_dir = os.path.dirname(host_compose_path)
            env_file_path = os.path.join(host_compose_dir, ".env")
            env_file = Path(env_file_path) if os.path.lexists(env_file_path) else None

            # Validate docker compose command template
            try:
                base_cmd = validate_docker_compose_command(compose_command)
            except ValidationError as e:
                logger.error(f"Invalid docker compose command: {str(e)}")
                return {
                    "success": False,
                    "error": f"Invalid docker compose command: {str(e)}",
                    "stdout": "",
                }

            # First, stop the existing container to avoid name conflicts
            stop_cmd = base_cmd.copy()

            # Add project and compose file flags (use host path)
            if compose_project:
                stop_cmd.extend(["-p", compose_project])
            stop_cmd.extend(["-f", host_compose_path])

            if env_file and env_file.exists():
                stop_cmd.extend(["--env-file", str(env_file)])

            stop_cmd.extend(["stop", validated_service])

            logger.info(f"Stopping container first: {' '.join(stop_cmd)}")

            # Execute stop command (ignore errors if container not running)
            docker_host = (
                docker_socket
                if docker_socket.startswith(("tcp://", "unix://"))
                else f"unix://{docker_socket}"
            )
            import os

            env = os.environ.copy()
            env["DOCKER_HOST"] = docker_host
            # Note: COMPOSE_ROOT uses host path from .env (/srv/raid0/docker/compose)
            # TideWatch mounts this path at BOTH /compose AND the host path
            # This allows both env_file (client-side) and secrets (daemon-side) to work

            try:
                stop_process = await asyncio.create_subprocess_exec(
                    *stop_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                await asyncio.wait_for(stop_process.communicate(), timeout=60)
                logger.info("Container stopped successfully (or was not running)")
            except Exception as e:
                logger.warning(f"Stop command failed (container may not be running): {e}")
                # Continue anyway - container might not have been running

            # Build command using list-based construction (safe)
            cmd = base_cmd.copy()

            # Add project and compose file flags (use host path)
            if compose_project:
                cmd.extend(["-p", compose_project])
            cmd.extend(["-f", host_compose_path])

            # Add env file if it exists
            if env_file and env_file.exists():
                cmd.extend(["--env-file", str(env_file)])
                logger.info(f"Using env file: {env_file}")

            # Add compose up arguments
            cmd.extend(["up", "-d", "--no-deps", "--force-recreate", validated_service])

            logger.info(f"Executing: {' '.join(cmd)}")

            # Use async subprocess to avoid blocking the event loop (env already set above)
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )

                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=300,  # 5 minute timeout (image already pulled separately)
                )

                stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
                stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""

                if process.returncode != 0:
                    logger.error(f"Docker compose failed: {stderr}")
                    return {
                        "success": False,
                        "error": stderr,
                        "stdout": stdout,
                    }

                logger.info(f"Docker compose output: {stdout}")

                return {
                    "success": True,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            except TimeoutError:
                logger.error("Docker compose command timed out after 300 seconds")
                return {
                    "success": False,
                    "error": "Operation timed out after 5 minutes",
                    "stdout": "",
                }

        except ValidationError as e:
            logger.error(f"Validation error executing docker compose: {e}")
            return {
                "success": False,
                "error": str(e),
            }
        except (OSError, PermissionError) as e:
            logger.error(f"File system error executing docker compose: {e}")
            return {
                "success": False,
                "error": str(e),
            }
        except subprocess.SubprocessError as e:
            logger.error(f"Subprocess error executing docker compose: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @staticmethod
    async def _pull_docker_image(
        compose_file: str,
        service_name: str,
        docker_socket: str = "/var/run/docker.sock",
        compose_command: str = "docker compose",
        compose_project: str | None = None,
    ) -> dict:
        """Pull the Docker image for a service before deploying.

        This separates the image pull from the deploy, allowing for:
        - Longer timeout for large images (20 minutes)
        - Better progress feedback to users
        - Clearer error messages

        Args:
            compose_file: Path to compose file
            service_name: Service name to pull
            docker_socket: Docker socket path
            compose_command: Docker compose command template
            compose_project: Docker Compose project name (e.g., 'homelab', 'proxies')

        Returns:
            Result dict with success status
        """
        # Validate service name
        try:
            validated_service = validate_service_name(service_name)
        except ValidationError as e:
            logger.error(f"Invalid service name '{service_name}': {str(e)}")
            return {
                "success": False,
                "error": f"Invalid service name: {str(e)}",
            }

        # Validate compose file path
        try:
            validated_compose_path = validate_compose_file_path(
                compose_file, allowed_base="/compose"
            )
            # Translate container path to host path for docker daemon
            host_compose_path = UpdateEngine._translate_container_path_to_host(
                str(validated_compose_path)
            )
        except ValidationError as e:
            logger.error(f"Invalid compose file path '{compose_file}': {str(e)}")
            return {
                "success": False,
                "error": f"Invalid compose file path: {str(e)}",
            }

        try:
            # Check for .env file (use host path for docker daemon)
            import os

            host_compose_dir = os.path.dirname(host_compose_path)
            env_file_path = os.path.join(host_compose_dir, ".env")
            env_file = Path(env_file_path) if os.path.lexists(env_file_path) else None

            # Validate docker compose command
            try:
                base_cmd = validate_docker_compose_command(compose_command)
            except ValidationError as e:
                logger.error(f"Invalid docker compose command: {str(e)}")
                return {
                    "success": False,
                    "error": f"Invalid docker compose command: {str(e)}",
                }

            # Build pull command
            cmd = base_cmd.copy()

            # Add project and compose file flags (use host path)
            if compose_project:
                cmd.extend(["-p", compose_project])
            cmd.extend(["-f", host_compose_path])

            if env_file and env_file.exists():
                cmd.extend(["--env-file", str(env_file)])

            cmd.extend(["pull", validated_service])

            logger.info(f"Pulling image: {' '.join(cmd)}")

            # Set up environment
            docker_host = (
                docker_socket
                if docker_socket.startswith(("tcp://", "unix://"))
                else f"unix://{docker_socket}"
            )
            env = os.environ.copy()
            env["DOCKER_HOST"] = docker_host
            # COMPOSE_ROOT uses host path - TideWatch mounts it at both /compose and host path

            # Execute pull with 20 minute timeout (large images can be 1GB+)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=1200,  # 20 minute timeout for image pulls
            )

            stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""

            if process.returncode != 0:
                logger.error(f"Docker pull failed: {stderr}")
                return {
                    "success": False,
                    "error": stderr,
                    "stdout": stdout,
                }

            logger.info(f"Image pulled successfully: {stdout}")
            return {
                "success": True,
                "stdout": stdout,
                "stderr": stderr,
            }

        except TimeoutError:
            logger.error("Docker pull timed out after 20 minutes")
            return {
                "success": False,
                "error": "Image pull timed out after 20 minutes",
            }
        except (
            ValidationError,
            OSError,
            PermissionError,
            subprocess.SubprocessError,
        ) as e:
            logger.error(f"Error pulling image: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @staticmethod
    async def _get_vulnforge_client(db: AsyncSession):
        """Get a VulnForge client instance if VulnForge integration is enabled.

        Args:
            db: Database session for reading settings

        Returns:
            VulnForgeClient instance or None if disabled/not configured
        """
        from app.services.vulnforge_client import VulnForgeClient

        # Check if VulnForge is enabled
        vulnforge_enabled = await SettingsService.get_bool(db, "vulnforge_enabled")
        if not vulnforge_enabled:
            return None

        # Get VulnForge configuration
        vulnforge_url = await SettingsService.get(db, "vulnforge_url")
        if not vulnforge_url:
            logger.warning("VulnForge URL not configured")
            return None

        # Get authentication settings
        auth_type = await SettingsService.get(db, "vulnforge_auth_type", "none")
        api_key = await SettingsService.get(db, "vulnforge_api_key")
        username = await SettingsService.get(db, "vulnforge_username")
        password = await SettingsService.get(db, "vulnforge_password")

        return VulnForgeClient(
            base_url=vulnforge_url,  # Guaranteed non-None by check on line 1669
            auth_type=auth_type or "none",
            api_key=api_key,
            username=username,
            password=password,
        )

    @staticmethod
    async def _trigger_vulnforge_rescan(container_name: str, update_id: int) -> None:
        """Trigger VulnForge rescan after update and fetch CVE delta results.

        This is a best-effort operation that doesn't block the update workflow.
        After triggering the scan, waits for it to complete and then fetches
        the CVE delta to store in the Update record.

        Note: This method creates its own database session because it runs
        as an asyncio.create_task() after the main update transaction completes.

        Args:
            container_name: Name of the container to rescan
            update_id: ID of the Update record to store CVE results in
        """
        from app.database import AsyncSessionLocal
        from app.models.update import Update

        try:
            # Create a fresh database session for this background task
            async with AsyncSessionLocal() as db:
                vulnforge = await UpdateEngine._get_vulnforge_client(db)
                if not vulnforge:
                    return

                try:
                    # Step 1: Trigger the scan
                    success = await vulnforge.trigger_scan_by_name(container_name)
                    if not success:
                        logger.warning(
                            f"VulnForge rescan request returned false for {container_name}"
                        )
                        return

                    logger.info(f"Triggered VulnForge rescan for {container_name}")

                    # Step 2: Wait for scan to complete (VulnForge scans typically take 30-90 seconds)
                    # Poll every 15 seconds for up to 3 minutes
                    max_wait_seconds = 180
                    poll_interval = 15
                    elapsed = 0

                    while elapsed < max_wait_seconds:
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval

                        # Step 3: Fetch CVE delta for this container
                        delta = await vulnforge.get_cve_delta(
                            container_name=container_name,
                            since_hours=1,  # Only look at very recent scans
                        )

                        if delta and delta.get("scans"):
                            # Found scan results - get the most recent one for this container
                            latest_scan = delta["scans"][0]
                            cves_fixed = latest_scan.get("cves_fixed", [])
                            cves_introduced = latest_scan.get("cves_introduced", [])
                            total_vulns = latest_scan.get("total_vulns", 0)

                            # Step 4: Update BOTH the Update record and UpdateHistory record with CVE data
                            result = await db.execute(select(Update).where(Update.id == update_id))
                            update_record = result.scalar_one_or_none()

                            if update_record:
                                update_record.cves_fixed = cves_fixed
                                update_record.new_vulns = total_vulns
                                update_record.vuln_delta = len(cves_introduced) - len(cves_fixed)

                                # ALSO update the corresponding UpdateHistory record
                                from app.models.history import UpdateHistory

                                history_result = await db.execute(
                                    select(UpdateHistory).where(
                                        UpdateHistory.update_id == update_id
                                    )
                                )
                                history_record = history_result.scalar_one_or_none()

                                if history_record:
                                    history_record.cves_fixed = cves_fixed
                                    logger.info(
                                        f"Backfilled UpdateHistory {history_record.id} with "
                                        f"{len(cves_fixed)} CVEs for {container_name}"
                                    )

                                await db.commit()

                                logger.info(
                                    f"Updated CVE data for {container_name}: "
                                    f"{len(cves_fixed)} fixed, {len(cves_introduced)} introduced, "
                                    f"{total_vulns} total vulns"
                                )
                            return

                    logger.warning(
                        f"VulnForge scan for {container_name} did not complete within {max_wait_seconds}s"
                    )

                finally:
                    await vulnforge.close()

        except Exception as e:
            # Don't fail - this is best-effort
            logger.warning(f"Failed to trigger VulnForge rescan for {container_name}: {e}")
