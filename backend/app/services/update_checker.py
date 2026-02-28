"""Update checker service for discovering available updates."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

# TYPE_CHECKING import for UpdateDecision to avoid circular import
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.update import Update
from app.services.changelog import ChangelogClassifier, ChangelogFetcher
from app.services.compose_parser import ComposeParser
from app.services.event_bus import event_bus
from app.services.registry_client import (
    RegistryCheckError,
    RegistryClient,
    RegistryClientFactory,
    is_non_semver_tag,
)
from app.services.settings_service import SettingsService

# Import UpdateDecisionTrace from update_decision_maker to avoid circular import
from app.services.update_decision_maker import UpdateDecisionTrace
from app.services.vulnforge_client import create_vulnforge_client
from app.utils.version import get_version_change_type

if TYPE_CHECKING:
    from app.services.tag_fetcher import FetchTagsResponse
    from app.services.update_decision_maker import UpdateDecision

logger = logging.getLogger(__name__)


class UpdateChecker:
    """Service for checking container updates."""

    @staticmethod
    async def _should_auto_approve(
        container: Container, _update: Update, auto_update_enabled: bool
    ) -> tuple[bool, str]:
        """Determine if an update should be automatically approved.

        Args:
            container: Container being updated
            _update: Update record (reserved for future severity-based rules)
            auto_update_enabled: Global auto-update setting

        Returns:
            tuple[bool, str]: (should_approve, reason)
        """
        # Check global setting
        if not auto_update_enabled:
            return False, "auto_update_enabled is disabled globally"

        # Check container policy
        if container.policy == "disabled":
            return False, "container policy is disabled"

        if container.policy == "monitor":
            return False, "container policy requires manual approval"

        if container.policy == "auto":
            return True, "container policy auto-approves updates within scope"

        return False, "unknown policy"

    @staticmethod
    async def check_all_containers(db: AsyncSession) -> dict:
        """Check all containers for updates.

        Args:
            db: Database session

        Returns:
            Stats dict with counts
        """
        result = await db.execute(select(Container).where(Container.policy != "disabled"))
        containers = result.scalars().all()

        stats = {
            "total": len(containers),
            "checked": 0,
            "updates_found": 0,
            "errors": 0,
        }

        for container in containers:
            try:
                update = await UpdateChecker.check_container(db, container)
                stats["checked"] += 1

                if update:
                    stats["updates_found"] += 1

                # Commit after each container so notifications match persisted state
                await db.commit()

            except OperationalError as e:
                logger.error(f"Database error checking {container.name}: {e}")
                stats["errors"] += 1
                await db.rollback()  # Rollback failed container, continue with next
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid data checking {container.name}: {e}")
                stats["errors"] += 1
                await db.rollback()  # Rollback failed container, continue with next

        return stats

    @staticmethod
    async def check_container(db: AsyncSession, container: Container) -> Update | None:
        """Check a single container for updates.

        Args:
            db: Database session
            container: Container to check

        Returns:
            Update object if update available, None otherwise
        """
        logger.info(
            f"Checking updates for {container.name} ({container.image}:{container.current_tag})"
        )

        await event_bus.publish(
            {
                "type": "update-check-started",
                "container_id": container.id,
                "container_name": container.name,
                "current_tag": container.current_tag,
            }
        )

        # Get registry client with credentials
        try:
            client = await RegistryClientFactory.get_client(container.registry, db)
        except ValueError as e:
            logger.error(f"Unsupported registry for {container.name}: {e}")
            return None

        previous_digest = container.current_digest

        try:
            # Resolve prerelease settings (container-level with global fallback)
            include_prereleases = await UpdateChecker._resolve_prerelease_setting(db, container)

            # Initialize decision trace
            trace = UpdateDecisionTrace()
            trace.set_basics(
                current_tag=container.current_tag,
                scope=container.scope,
                include_prereleases=include_prereleases,
                registry=container.registry,
            )

            # Fetch latest tag from registry
            latest_tag = await client.get_latest_tag(
                container.image,
                container.current_tag,
                container.scope,
                current_digest=container.current_digest
                if is_non_semver_tag(container.current_tag)
                else None,
                include_prereleases=include_prereleases,
                version_track=container.version_track,
            )

            # Persist cross-scheme rejection for UI visibility (one summary log per check)
            calver_blocked = getattr(client, "_best_cross_scheme_rejected", None)
            container.calver_blocked_tag = calver_blocked
            if calver_blocked:
                logger.info(
                    "Cross-scheme candidate blocked for %s — best rejected: %s "
                    "[reason=track_mismatch]",
                    container.name,
                    calver_blocked,
                )

            # Check for major updates (informational visibility)
            await UpdateChecker._check_major_update(
                client, container, include_prereleases, latest_tag, container.version_track
            )

            # Extract suffix from current tag (e.g., "-alpine", "-slim")
            suffix = None
            if "-" in container.current_tag:
                parts = container.current_tag.split("-", 1)
                if len(parts) > 1 and not parts[1][0].isdigit():
                    suffix = parts[1]
            trace.set_suffix_match(suffix)

            # Capture scope blocking info for trace
            if (
                container.latest_major_tag
                and container.latest_major_tag != container.current_tag
                and container.latest_major_tag != latest_tag
            ):
                trace.set_scope_blocking(
                    blocked=True,
                    latest_major_tag=container.latest_major_tag,
                    reason=f"scope={container.scope} blocks major update to {container.latest_major_tag}",
                )

            # Update last_checked
            container.last_checked = datetime.now(UTC)

            # Check digest for non-semver tags (latest, lts, stable, etc.)
            digest_changed, new_digest = await UpdateChecker._check_digest_update(client, container)
            digest_update = (
                is_non_semver_tag(container.current_tag)
                and digest_changed
                and new_digest is not None
            )

            # Capture digest/tag info for trace
            if is_non_semver_tag(container.current_tag):
                trace.set_digest_update(previous_digest, new_digest, digest_changed)
            if latest_tag and latest_tag != container.current_tag:
                detected_change_type = get_version_change_type(container.current_tag, latest_tag)
                trace.set_tag_update(latest_tag, detected_change_type)

            # No update available within scope
            if not latest_tag or latest_tag == container.current_tag:
                if not digest_update:
                    await UpdateChecker._handle_no_update(db, container, trace)
                    return None
                # Treat digest change as an update even though the tag is unchanged
                latest_tag = container.current_tag

            # Update available — set container state
            container.update_available = True
            if digest_update and new_digest:
                container.latest_tag = f"{latest_tag} [{new_digest[:12]}]"
            else:
                container.latest_tag = latest_tag

            logger.info(
                f"Update available for {container.name}: {container.current_tag} -> {latest_tag}"
            )

            # Check if update already exists (in any active state)
            result = await db.execute(
                select(Update).where(
                    Update.container_id == container.id,
                    Update.from_tag == container.current_tag,
                    Update.to_tag == latest_tag,
                    Update.status.in_(["pending", "pending_retry", "approved"]),
                )
            )
            existing_update = result.scalar_one_or_none()

            if existing_update:
                return await UpdateChecker._handle_existing_update(
                    existing_update,
                    container,
                    latest_tag,
                    digest_update,
                    previous_digest,
                    new_digest,
                )

            # Supersede any older pending/approved updates for this container
            # (e.g., v3.10.0 approved while v3.10.1 just arrived)
            await UpdateChecker._clear_pending_updates(db, container.id)

            # Create new update record
            update = await UpdateChecker._create_update_record(
                db, container, latest_tag, trace, digest_update, previous_digest, new_digest
            )

            # Changelog enrichment
            await UpdateChecker._enrich_with_changelog(db, update, container, latest_tag)

            # VulnForge enrichment
            if container.vulnforge_enabled and not digest_update:
                await UpdateChecker._enrich_with_vulnforge(db, update, container)
            elif container.vulnforge_enabled and digest_update:
                await UpdateChecker._refresh_vulnforge_baseline(db, container)

            # Auto-approval + notifications
            await UpdateChecker._process_auto_approval_and_notify(db, update, container)

            logger.info(f"Created update record for {container.name}")

            await event_bus.publish(
                {
                    "type": "update-available",
                    "container_id": container.id,
                    "container_name": container.name,
                    "from_tag": update.from_tag,
                    "to_tag": update.to_tag,
                    "reason_type": update.reason_type,
                    "status": update.status,
                }
            )

            return update

        except RegistryCheckError as e:
            rate_limit_msg = " (rate limited)" if e.is_rate_limit else ""
            await UpdateChecker._publish_check_error(
                container,
                e,
                f"Registry check failed{rate_limit_msg}",
                preserving_updates=True,
            )
            return None
        except httpx.HTTPStatusError as e:
            await UpdateChecker._publish_check_error(container, e, "Registry HTTP error")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            await UpdateChecker._publish_check_error(container, e, "Registry connection error")
            return None
        except OperationalError as e:
            await UpdateChecker._publish_check_error(container, e, "Database error")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            await UpdateChecker._publish_check_error(container, e, "Invalid data")
            return None
        finally:
            try:
                await client.close()
            except Exception as close_error:
                logger.warning(
                    f"Failed to close registry client for {container.name}: {close_error}"
                )

    @staticmethod
    async def _publish_check_error(
        container: Container,
        error: Exception,
        error_category: str,
        *,
        preserving_updates: bool = False,
    ) -> None:
        """Log and publish an update-check-error event.

        Args:
            container: Container that failed the check
            error: The exception that occurred
            error_category: Human-readable error category for the event message
            preserving_updates: If True, use warning-level logging and include
                preserving_updates flag in event (for registry failures)
        """
        if preserving_updates:
            logger.warning(
                f"{error_category} for {container.name}: {error} - "
                "preserving existing pending updates"
            )
        else:
            logger.error(f"{error_category} checking updates for {container.name}: {error}")

        event_data: dict[str, Any] = {
            "type": "update-check-error",
            "container_id": container.id,
            "container_name": container.name,
            "message": f"{error_category}: {error}",
        }
        if preserving_updates:
            event_data["preserving_updates"] = True

        await event_bus.publish(event_data)

    @staticmethod
    async def _resolve_prerelease_setting(db: AsyncSession, container: Container) -> bool:
        """Resolve the effective include_prereleases value.

        Uses tri-state logic:
        - None: inherit from global setting
        - True: force include prereleases
        - False: force stable only

        Args:
            db: Database session
            container: Container to resolve setting for

        Returns:
            True if prereleases should be included
        """
        if container.include_prereleases is not None:
            return container.include_prereleases
        return await SettingsService.get_bool(db, "include_prereleases", default=False)

    @staticmethod
    async def _check_major_update(
        client: RegistryClient,
        container: Container,
        include_prereleases: bool,
        latest_tag: str | None,
        version_track: str | None = None,
    ) -> str | None:
        """Fetch the latest major tag for informational visibility.

        Always checks for major updates separately (even if scope blocks them)
        to provide informational visibility to users about available major versions.

        Args:
            client: Registry client
            container: Container to check
            include_prereleases: Whether to include pre-release versions
            latest_tag: The latest in-scope tag (to avoid storing duplicates)
            version_track: Versioning scheme override (None=auto, "semver", "calver")

        Returns:
            Latest major tag, or None
        """
        if container.scope == "major":
            container.latest_major_tag = None
            return None

        try:
            latest_major_tag = await client.get_latest_major_tag(
                container.image,
                container.current_tag,
                include_prereleases=include_prereleases,
                version_track=version_track,
            )

            if latest_major_tag and latest_major_tag != latest_tag:
                container.latest_major_tag = latest_major_tag
                logger.info(
                    f"Major update available for {container.name} (blocked by scope={container.scope}): "
                    f"{container.current_tag} -> {latest_major_tag}"
                )
            else:
                container.latest_major_tag = None
            return latest_major_tag
        except Exception as e:
            logger.warning(f"Failed to check major updates for {container.name}: {e}")
            container.latest_major_tag = None
            return None

    @staticmethod
    async def _check_digest_update(
        client: RegistryClient,
        container: Container,
    ) -> tuple[bool, str | None]:
        """For 'latest' tag containers, fetch and compare digest from registry.

        Args:
            client: Registry client
            container: Container to check (mutates current_digest if initial)

        Returns:
            Tuple of (digest_changed, new_digest)
        """
        if container.current_tag != "latest":
            return False, None

        previous_digest = container.current_digest
        new_digest: str | None = None
        digest_changed = False

        try:
            metadata = await client.get_tag_metadata(container.image, "latest")
            if metadata and metadata.get("digest"):
                new_digest = metadata["digest"]
                if previous_digest is None:
                    container.current_digest = new_digest
                    logger.info(f"Stored initial digest for {container.name}: {new_digest}")
                elif previous_digest != new_digest:
                    digest_changed = True
                    logger.info(
                        f"Detected digest change for {container.name}: "
                        f"{previous_digest} -> {new_digest}"
                    )
        except httpx.HTTPStatusError as e:
            logger.warning(f"Registry HTTP error fetching digest for {container.name}: {e}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"Registry connection error fetching digest for {container.name}: {e}")
        except (ValueError, KeyError, AttributeError) as e:
            logger.warning(f"Invalid digest metadata for {container.name}: {e}")

        return digest_changed, new_digest

    @staticmethod
    async def _handle_no_update(
        db: AsyncSession,
        container: Container,
        trace: UpdateDecisionTrace,
    ) -> None:
        """Handle the no-update-available branch.

        Creates scope-violation records if a major update is blocked by scope,
        clears stale pending updates, refreshes VulnForge baseline, and
        publishes the completion event.

        Args:
            db: Database session
            container: Container with no in-scope update
            trace: Decision trace for scope-violation records
        """
        container.update_available = False
        container.latest_tag = None

        # Check if there's a major update blocked by scope
        if container.latest_major_tag and container.latest_major_tag != container.current_tag:
            await UpdateChecker._create_scope_violation_update(
                db, container, container.latest_major_tag, trace.to_json()
            )

        logger.info(f"No in-scope updates for {container.name}")

        await UpdateChecker._clear_pending_updates(db, container.id)

        # Refresh VulnForge baseline even without updates
        if container.vulnforge_enabled:
            await UpdateChecker._refresh_vulnforge_baseline(db, container)

        await event_bus.publish(
            {
                "type": "update-check-complete",
                "status": "no_update",
                "container_id": container.id,
                "container_name": container.name,
            }
        )

    @staticmethod
    async def _handle_existing_update(
        existing_update: Update,
        container: Container,
        latest_tag: str,
        digest_update: bool,
        previous_digest: str | None,
        new_digest: str | None,
    ) -> Update:
        """Handle the case where an update record already exists.

        Optionally updates digest fields on the existing record and publishes
        the update-available event.

        Args:
            existing_update: The existing update record
            container: Container being checked
            latest_tag: The latest available tag
            digest_update: Whether this is a digest-only update
            previous_digest: Previous digest value
            new_digest: New digest value

        Returns:
            The existing update record
        """
        if digest_update and new_digest:
            existing_update.reason_type = "maintenance"
            summary = (
                f"Image digest updated: {previous_digest[:12]} -> {new_digest[:12]}"
                if previous_digest
                else "Image digest updated for latest tag"
            )
            existing_update.reason_summary = summary
            existing_update.recommendation = "Recommended - refreshed image available"
            existing_update.changelog = json.dumps(
                {
                    "type": "digest_update",
                    "from_digest": previous_digest,
                    "to_digest": new_digest,
                }
            )
        logger.info(f"Update already exists for {container.name}")
        await event_bus.publish(
            {
                "type": "update-available",
                "container_id": container.id,
                "container_name": container.name,
                "from_tag": container.current_tag,
                "to_tag": latest_tag,
                "reason_type": existing_update.reason_type,
                "status": existing_update.status,
            }
        )
        return existing_update

    @staticmethod
    async def _create_update_record(
        db: AsyncSession,
        container: Container,
        latest_tag: str,
        trace: UpdateDecisionTrace,
        digest_update: bool,
        previous_digest: str | None,
        new_digest: str | None,
    ) -> Update:
        """Build an Update record and insert it with savepoint protection.

        Handles IntegrityError race conditions by re-fetching the existing record.

        Args:
            db: Database session
            container: Container being updated
            latest_tag: The target tag for the update
            trace: Decision trace to attach
            digest_update: Whether this is a digest-only update
            previous_digest: Previous digest value
            new_digest: New digest value

        Returns:
            The newly created Update (or existing on race condition)
        """
        reason_summary = "New version available"
        reason_type = "unknown"
        recommendation: str | None = None
        changelog_payload: str | None = None

        if digest_update and new_digest:
            reason_type = "maintenance"
            if previous_digest:
                reason_summary = (
                    f"Image digest updated: {previous_digest[:12]} \u2192 {new_digest[:12]}"
                )
            else:
                reason_summary = "Image digest updated for latest tag"
            recommendation = "Recommended - refreshed image available"
            changelog_payload = json.dumps(
                {
                    "type": "digest_update",
                    "from_digest": previous_digest,
                    "to_digest": new_digest,
                }
            )

        max_retries = await SettingsService.get_int(db, "update_retry_max_attempts", default=3)
        backoff_multiplier = await SettingsService.get_int(
            db, "update_retry_backoff_multiplier", default=3
        )

        update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag=container.current_tag,
            to_tag=latest_tag,
            registry=container.registry,
            reason_type=reason_type,
            reason_summary=reason_summary,
            recommendation=recommendation,
            changelog=changelog_payload,
            status="pending",
            max_retries=max_retries,
            backoff_multiplier=backoff_multiplier,
            decision_trace=trace.to_json(),
            update_kind=trace.update_kind,
            change_type=trace.change_type,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        db.add(update)
        try:
            async with db.begin_nested():
                await db.flush()
            await db.refresh(update)
        except IntegrityError as ie:
            logger.info(
                f"Duplicate update detected for {container.name} "
                f"({container.current_tag} -> {latest_tag}), using existing"
            )
            await db.rollback()
            result = await db.execute(
                select(Update).where(
                    Update.container_id == container.id,
                    Update.from_tag == container.current_tag,
                    Update.to_tag == latest_tag,
                    Update.status.in_(["pending", "pending_retry", "approved"]),
                )
            )
            existing_update = result.scalar_one_or_none()
            if existing_update:
                return existing_update
            raise ie

        return update

    @staticmethod
    async def _enrich_with_changelog(
        db: AsyncSession,
        update: Update,
        container: Container,
        latest_tag: str,
    ) -> None:
        """Fetch changelog from release source and enrich the update record.

        Auto-detects release source if not already set on the container.
        Classifies changelog content and updates reason_type/reason_summary.

        Args:
            db: Database session
            update: Update record to enrich
            container: Container being updated
            latest_tag: The target tag (used for changelog lookup)
        """
        release_source = container.release_source
        detected_source = None
        if not release_source:
            detected_source = ComposeParser.extract_release_source(container.image)
            if detected_source:
                logger.info(f"Auto-detected release source for {container.name}: {detected_source}")
                release_source = detected_source

        if not release_source:
            return

        github_token = await SettingsService.get(db, "ghcr_token") or await SettingsService.get(
            db, "github_token"
        )
        fetcher = ChangelogFetcher(github_token=github_token)
        changelog = await fetcher.fetch(release_source, container.image, latest_tag)
        if changelog:
            classified_type, summary = ChangelogClassifier.classify(changelog.raw_text)
            if classified_type != "unknown":
                update.reason_type = classified_type
            if summary:
                update.reason_summary = summary
            update.changelog = changelog.raw_text
            if changelog.url:
                update.changelog_url = changelog.url
            # Save the detected source to the container for future use
            if detected_source:
                from sqlalchemy import update as sql_update

                await db.execute(
                    sql_update(Container)
                    .where(Container.id == container.id)
                    .values(release_source=detected_source)
                )

    @staticmethod
    async def _process_auto_approval_and_notify(
        db: AsyncSession,
        update: Update,
        container: Container,
    ) -> None:
        """Check auto-approval policy and send notifications.

        If the update qualifies for auto-approval based on container policy
        and global settings, marks it as approved. Then sends the appropriate
        notification (security or general) via the notification dispatcher.

        Args:
            db: Database session
            update: Update record to potentially auto-approve
            container: Container being updated
        """
        auto_update_enabled = await SettingsService.get_bool(
            db, "auto_update_enabled", default=False
        )
        should_approve, approval_reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled
        )

        if should_approve:
            logger.info(f"Auto-approving update for {container.name}: {approval_reason}")
            update.status = "approved"
            update.approved_by = "system"
            update.approved_at = datetime.now(UTC)

        from app.services.notifications.dispatcher import NotificationDispatcher

        dispatcher = NotificationDispatcher(db)
        if update.reason_type == "security" and update.cves_fixed:
            await dispatcher.notify_security_update(
                container.name,
                update.from_tag,
                update.to_tag,
                update.cves_fixed,
                update.vuln_delta or 0,
            )
        else:
            await dispatcher.notify_update_available(
                container.name,
                update.from_tag,
                update.to_tag,
                update.reason_summary or "New version available",
            )

    @staticmethod
    async def apply_decision(
        db: AsyncSession,
        container: Container,
        decision: UpdateDecision,
        fetch_response: FetchTagsResponse,
    ) -> Update | None:
        """Apply a pre-computed update decision to a container.

        This method is called after tag fetching and decision making have already
        occurred. It handles all database updates, notifications, and events.

        Used by the concurrent check job service to apply results from deduplicated
        container groups.

        Args:
            db: Database session
            container: Container to apply decision to
            decision: Pre-computed UpdateDecision from UpdateDecisionMaker
            fetch_response: FetchTagsResponse containing tag data

        Returns:
            Update object if update available, None otherwise
        """
        logger.debug(f"Applying decision for {container.name}: has_update={decision.has_update}")

        # Update last_checked timestamp
        container.last_checked = datetime.now(UTC)

        # Update latest_major_tag for scope visibility
        if decision.latest_major_tag and decision.latest_major_tag != container.current_tag:
            container.latest_major_tag = decision.latest_major_tag
        else:
            container.latest_major_tag = None

        # Persist cross-scheme rejection for UI visibility (always assign to clear stale values)
        container.calver_blocked_tag = fetch_response.calver_blocked_tag

        # Capture previous digest BEFORE any mutations (for accurate summaries later)
        previous_digest = container.current_digest

        # Handle digest update for 'latest' tag
        if decision.digest_changed and decision.new_digest:
            container.current_digest = decision.new_digest
        elif decision.digest_baseline_needed and decision.new_digest:
            # First run: store the baseline digest without treating it as an update
            container.current_digest = decision.new_digest
            logger.info(f"Stored initial digest for {container.name}: {decision.new_digest}")

        # Determine if we have an in-scope update
        is_digest_update = decision.update_kind == "digest"

        if not decision.has_update:
            # No update available within scope
            container.update_available = False
            container.latest_tag = None

            # Handle scope violation (major update blocked by scope)
            if decision.is_scope_violation and decision.latest_major_tag:
                await UpdateChecker._create_scope_violation_update(
                    db, container, decision.latest_major_tag, decision.trace.to_json()
                )

            logger.info(f"No in-scope updates for {container.name}")

            # Only clear pending updates if the check was successful (no fetch errors)
            # If there was a fetch error, preserve existing pending updates
            if fetch_response.error:
                logger.warning(
                    f"Fetch error for {container.name}: {fetch_response.error} - "
                    "preserving existing pending updates"
                )
            else:
                await UpdateChecker._clear_pending_updates(db, container.id)

            # Refresh VulnForge baseline even without updates
            if container.vulnforge_enabled:
                await UpdateChecker._refresh_vulnforge_baseline(db, container)

            await event_bus.publish(
                {
                    "type": "update-check-complete",
                    "status": "no_update",
                    "container_id": container.id,
                    "container_name": container.name,
                }
            )

            return None

        # Update available!
        latest_tag = decision.latest_tag or container.current_tag
        container.update_available = True

        if is_digest_update and decision.new_digest:
            container.latest_tag = f"{latest_tag} [{decision.new_digest[:12]}]"
        else:
            container.latest_tag = latest_tag

        logger.info(
            f"Update available for {container.name}: {container.current_tag} -> {latest_tag}"
        )

        # Check if update already exists
        result = await db.execute(
            select(Update).where(
                Update.container_id == container.id,
                Update.from_tag == container.current_tag,
                Update.to_tag == latest_tag,
                Update.status.in_(["pending", "pending_retry", "approved"]),
            )
        )
        existing_update = result.scalar_one_or_none()

        if existing_update:
            if is_digest_update and decision.new_digest:
                existing_update.reason_type = "maintenance"
                summary = f"Image digest updated: {previous_digest[:12] if previous_digest else 'unknown'} -> {decision.new_digest[:12]}"
                existing_update.reason_summary = summary
                existing_update.recommendation = "Recommended - refreshed image available"
                existing_update.changelog = json.dumps(
                    {
                        "type": "digest_update",
                        "from_digest": previous_digest,
                        "to_digest": decision.new_digest,
                    }
                )
            logger.info(f"Update already exists for {container.name}")
            await event_bus.publish(
                {
                    "type": "update-available",
                    "container_id": container.id,
                    "container_name": container.name,
                    "from_tag": container.current_tag,
                    "to_tag": latest_tag,
                    "reason_type": existing_update.reason_type,
                    "status": existing_update.status,
                }
            )
            return existing_update

        # Prepare update record fields
        reason_summary = "New version available"
        reason_type = "unknown"
        recommendation: str | None = None
        changelog_payload: str | None = None

        if is_digest_update and decision.new_digest:
            reason_type = "maintenance"
            if previous_digest:
                reason_summary = (
                    f"Image digest updated: {previous_digest[:12]} -> {decision.new_digest[:12]}"
                )
            else:
                reason_summary = "Image digest updated for latest tag"
            recommendation = "Recommended - refreshed image available"
            changelog_payload = json.dumps(
                {
                    "type": "digest_update",
                    "from_digest": previous_digest,
                    "to_digest": decision.new_digest,
                }
            )

        # Get retry settings
        max_retries = await SettingsService.get_int(db, "update_retry_max_attempts", default=3)
        backoff_multiplier = await SettingsService.get_int(
            db, "update_retry_backoff_multiplier", default=3
        )

        # Create new update record
        update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag=container.current_tag,
            to_tag=latest_tag,
            registry=container.registry,
            reason_type=reason_type,
            reason_summary=reason_summary,
            recommendation=recommendation,
            changelog=changelog_payload,
            status="pending",
            max_retries=max_retries,
            backoff_multiplier=backoff_multiplier,
            decision_trace=decision.trace.to_json(),
            update_kind=decision.trace.update_kind,
            change_type=decision.trace.change_type,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        db.add(update)
        try:
            async with db.begin_nested():
                await db.flush()
            await db.refresh(update)
        except IntegrityError as ie:
            logger.info(
                f"Duplicate update detected for {container.name} "
                f"({container.current_tag} -> {latest_tag}), using existing"
            )
            await db.rollback()
            result = await db.execute(
                select(Update).where(
                    Update.container_id == container.id,
                    Update.from_tag == container.current_tag,
                    Update.to_tag == latest_tag,
                    Update.status.in_(["pending", "pending_retry", "approved"]),
                )
            )
            existing_update = result.scalar_one_or_none()
            if existing_update:
                return existing_update
            raise ie

        # Changelog enrichment (skip for digest updates)
        if not is_digest_update:
            release_source = container.release_source
            detected_source = None
            if not release_source:
                detected_source = ComposeParser.extract_release_source(container.image)
                if detected_source:
                    logger.info(
                        f"Auto-detected release source for {container.name}: {detected_source}"
                    )
                    release_source = detected_source

            if release_source:
                github_token = await SettingsService.get(
                    db, "ghcr_token"
                ) or await SettingsService.get(db, "github_token")
                fetcher = ChangelogFetcher(github_token=github_token)
                changelog = await fetcher.fetch(release_source, container.image, latest_tag)
                if changelog:
                    classified_type, summary = ChangelogClassifier.classify(changelog.raw_text)
                    if classified_type != "unknown":
                        update.reason_type = classified_type
                    if summary:
                        update.reason_summary = summary
                    update.changelog = changelog.raw_text
                    if changelog.url:
                        update.changelog_url = changelog.url
                    if detected_source:
                        from sqlalchemy import update as sql_update

                        await db.execute(
                            sql_update(Container)
                            .where(Container.id == container.id)
                            .values(release_source=detected_source)
                        )

        # VulnForge enrichment
        if container.vulnforge_enabled and not is_digest_update:
            await UpdateChecker._enrich_with_vulnforge(db, update, container)
        elif container.vulnforge_enabled and is_digest_update:
            await UpdateChecker._refresh_vulnforge_baseline(db, container)

        # Auto-approval + notifications (shared logic with check_container)
        await UpdateChecker._process_auto_approval_and_notify(db, update, container)

        logger.info(f"Created update record for {container.name}")

        await event_bus.publish(
            {
                "type": "update-available",
                "container_id": container.id,
                "container_name": container.name,
                "from_tag": update.from_tag,
                "to_tag": update.to_tag,
                "reason_type": update.reason_type,
                "status": update.status,
            }
        )

        return update

    @staticmethod
    async def _create_scope_violation_update(
        db: AsyncSession,
        container: Container,
        target_tag: str,
        trace_json: str,
    ) -> None:
        """Create an Update record for a scope-violated major version.

        Skips creation if a scope-violation record already exists for
        this container + target tag (pending, approved, or rejected/dismissed).

        Args:
            db: Database session
            container: Container with blocked major update
            target_tag: The major version tag blocked by scope
            trace_json: JSON string of the decision trace
        """
        # Skip if scope-violation already exists (pending, approved, or dismissed)
        result = await db.execute(
            select(Update).where(
                Update.container_id == container.id,
                Update.from_tag == container.current_tag,
                Update.to_tag == target_tag,
                Update.scope_violation == 1,
                Update.status.in_(["pending", "approved", "rejected"]),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return

        max_retries = await SettingsService.get_int(db, "update_retry_max_attempts", default=3)
        backoff_multiplier = await SettingsService.get_int(
            db, "update_retry_backoff_multiplier", default=3
        )

        scope_change_type = get_version_change_type(container.current_tag, target_tag)

        scope_update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag=container.current_tag,
            to_tag=target_tag,
            registry=container.registry,
            reason_type="feature",
            reason_summary=f"Major version update available (blocked by scope={container.scope})",
            recommendation="Review required - change scope to major to apply",
            status="pending",
            scope_violation=1,
            max_retries=max_retries,
            backoff_multiplier=backoff_multiplier,
            decision_trace=trace_json,
            update_kind="tag",
            change_type=scope_change_type,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        db.add(scope_update)
        try:
            async with db.begin_nested():
                await db.flush()
            await db.refresh(scope_update)
            logger.info(
                f"Created scope-violation update for {container.name}: "
                f"{container.current_tag} -> {target_tag} (scope={container.scope})"
            )
        except IntegrityError:
            logger.debug(f"Scope-violation update already exists for {container.name}")
            await db.rollback()

    @staticmethod
    async def get_pending_updates(db: AsyncSession) -> list[Update]:
        """Get all pending updates.

        Args:
            db: Database session

        Returns:
            List of pending updates
        """
        result = await db.execute(
            select(Update).where(Update.status == "pending").order_by(Update.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_auto_approvable_updates(db: AsyncSession) -> list[Update]:
        """Get updates that can be auto-approved.

        Returns updates for containers with policy="auto".

        Args:
            db: Database session

        Returns:
            List of auto-approvable updates
        """
        result = await db.execute(
            select(Update)
            .join(Container)
            .where(
                Update.status == "pending",
                Container.policy == "auto",
            )
            .order_by(Update.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_security_updates(db: AsyncSession) -> list[Update]:
        """Get security-related updates.

        Returns updates with CVE fixes or vulnerability deltas.

        Args:
            db: Database session

        Returns:
            List of security updates
        """
        result = await db.execute(
            select(Update)
            .where(
                Update.status == "pending",
                Update.reason_type == "security",
            )
            .order_by(Update.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _enrich_with_vulnforge(db: AsyncSession, update: Update, container: Container):
        """Enrich update record with VulnForge vulnerability data.

        Args:
            db: Database session
            update: Update record to enrich
            container: Container being updated
        """
        try:
            # Get VulnForge client (handles enabled check, URL, and auth)
            vulnforge = await create_vulnforge_client(db)
            if not vulnforge:
                logger.debug("VulnForge integration disabled or not configured")
                return

            try:
                # Compare vulnerabilities
                comparison = await vulnforge.compare_vulnerabilities(
                    container.image,
                    container.current_tag,
                    update.to_tag,
                    container.registry,
                )

                if not comparison:
                    current_data = await vulnforge.get_image_vulnerabilities(
                        container.image,
                        container.current_tag,
                        container.registry,
                    )

                    if current_data:
                        update.current_vulns = current_data["total_vulns"]
                        update.new_vulns = current_data["total_vulns"]
                        update.vuln_delta = 0
                        update.cves_fixed = []
                        container.current_vuln_count = current_data["total_vulns"]

                        if not update.reason_summary:
                            update.reason_summary = (
                                f"VulnForge reports {current_data['total_vulns']} "
                                f"vulnerabilities for {container.current_tag}; "
                                f"no scan data available for {update.to_tag} yet."
                            )

                        logger.info(
                            f"VulnForge current data for {container.name}: "
                            f"{current_data['total_vulns']} vulnerabilities "
                            f"(new tag {update.to_tag} not scanned)"
                        )
                    else:
                        logger.info(
                            f"VulnForge has no vulnerability data for "
                            f"{container.name} ({container.current_tag})"
                        )

                    return

                # Update the record with vulnerability data
                update.current_vulns = comparison["current"]["total_vulns"]
                update.new_vulns = comparison["new"]["total_vulns"]
                update.vuln_delta = comparison["delta"]["total"]
                update.cves_fixed = comparison["cves_fixed"]

                # Determine reason type
                if len(comparison["cves_fixed"]) > 0:
                    update.reason_type = "security"
                    update.reason_summary = comparison["summary"]
                elif comparison["delta"]["total"] < 0:
                    update.reason_type = "security"
                    update.reason_summary = comparison["summary"]
                else:
                    update.reason_type = "maintenance"
                    update.reason_summary = comparison["summary"]

                # Store recommendation from VulnForge analysis
                update.recommendation = comparison.get("recommendation", "Optional")

                # Update container vulnerability count
                if comparison["current"]:
                    container.current_vuln_count = comparison["current"]["total_vulns"]

                logger.info(f"VulnForge enrichment for {container.name}: {comparison['summary']}")

            finally:
                await vulnforge.close()

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge HTTP error enriching data: {e}")
            # Don't fail the update creation if VulnForge fails
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error enriching data: {e}")
            # Don't fail the update creation if VulnForge fails
        except OperationalError as e:
            logger.error(f"Database error enriching with VulnForge data: {e}")
            # Don't fail the update creation if VulnForge fails
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge data: {e}")
            # Don't fail the update creation if VulnForge fails

    @staticmethod
    async def _clear_pending_updates(db: AsyncSession, container_id: int) -> None:
        """Remove stale pending/approved update records for a container.

        Preserves scope-violation records (scope_violation=1) since those
        persist until the user explicitly dismisses them.
        """
        await db.execute(
            delete(Update).where(
                Update.container_id == container_id,
                Update.status.in_(("pending", "approved")),
                Update.scope_violation == 0,
            )
        )

    @staticmethod
    async def _refresh_vulnforge_baseline(
        db: AsyncSession,
        container: Container,
    ) -> None:
        """Refresh current vulnerability count from VulnForge for a container."""
        try:
            # Get VulnForge client (handles enabled check, URL, and auth)
            vulnforge = await create_vulnforge_client(db)
            if not vulnforge:
                return

            try:
                data = await vulnforge.get_image_vulnerabilities(
                    container.image,
                    container.current_tag,
                    container.registry,
                )

                if data:
                    container.current_vuln_count = data["total_vulns"]
                    logger.info(
                        f"VulnForge baseline for {container.name}: "
                        f"{data['total_vulns']} vulnerabilities"
                    )
                else:
                    logger.info(
                        f"VulnForge baseline missing for {container.name} ({container.current_tag})"
                    )
            finally:
                await vulnforge.close()

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge HTTP error refreshing baseline for {container.name}: {e}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(
                f"VulnForge connection error refreshing baseline for {container.name}: {e}"
            )
        except OperationalError as e:
            logger.error(f"Database error refreshing VulnForge baseline for {container.name}: {e}")
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge data refreshing baseline for {container.name}: {e}")
