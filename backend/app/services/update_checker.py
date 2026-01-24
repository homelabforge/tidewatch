"""Update checker service for discovering available updates."""

import json
import logging
import httpx
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.container import Container
from app.models.update import Update
from app.services.registry_client import RegistryClientFactory
from app.services.vulnforge_client import VulnForgeClient
from app.services.settings_service import SettingsService
from app.services.event_bus import event_bus
from app.services.changelog import ChangelogFetcher, ChangelogClassifier
from app.services.compose_parser import ComposeParser
from app.utils.version import get_version_change_type

# Import UpdateDecisionTrace from update_decision_maker to avoid circular import
from app.services.update_decision_maker import UpdateDecisionTrace

# TYPE_CHECKING import for UpdateDecision to avoid circular import
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.update_decision_maker import UpdateDecision
    from app.services.tag_fetcher import FetchTagsResponse

logger = logging.getLogger(__name__)


class UpdateChecker:
    """Service for checking container updates."""

    @staticmethod
    async def _should_auto_approve(
        container: Container, update: Update, auto_update_enabled: bool
    ) -> tuple[bool, str]:
        """Determine if an update should be automatically approved.

        Args:
            container: Container being updated
            update: Update record
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

        if container.policy == "manual":
            return False, "container policy requires manual approval"

        if container.policy == "auto":
            return (
                True,
                "container policy allows all updates (including breaking changes)",
            )

        if container.policy == "security":
            if update.reason_type == "security":
                return True, "security policy approves security updates"
            else:
                return (
                    False,
                    "security policy requires manual approval for non-security updates",
                )

        # Semver-aware policies
        if container.policy == "patch-only":
            change_type = get_version_change_type(update.from_tag, update.to_tag)
            if change_type == "patch":
                return True, "patch-only policy approves patch updates"
            else:
                return (
                    False,
                    f"patch-only policy requires manual approval for {change_type or 'unknown'} updates",
                )

        if container.policy == "minor-and-patch":
            change_type = get_version_change_type(update.from_tag, update.to_tag)
            if change_type in ["minor", "patch"]:
                return True, f"minor-and-patch policy approves {change_type} updates"
            elif change_type == "major":
                return (
                    False,
                    "minor-and-patch policy requires manual approval for major updates (breaking changes)",
                )
            else:
                return (
                    False,
                    "minor-and-patch policy requires manual approval for unknown version changes",
                )

        return False, "unknown policy"

    @staticmethod
    async def check_all_containers(db: AsyncSession) -> dict:
        """Check all containers for updates.

        Args:
            db: Database session

        Returns:
            Stats dict with counts
        """
        result = await db.execute(
            select(Container).where(Container.policy != "disabled")
        )
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
    async def check_container(
        db: AsyncSession, container: Container
    ) -> Optional[Update]:
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
        digest_changed = False
        new_digest: Optional[str] = None

        try:
            # Get latest tag based on policy scope
            # For 'latest' tags, pass current digest for comparison
            # Get global prerelease setting if container-specific setting is False
            # This allows users to globally filter pre-releases via Settings > Updates
            include_prereleases = container.include_prereleases
            if not include_prereleases:
                global_include_prereleases = await SettingsService.get_bool(
                    db, "include_prereleases", default=False
                )
                include_prereleases = global_include_prereleases

            # Initialize decision trace
            trace = UpdateDecisionTrace()
            trace.set_basics(
                current_tag=container.current_tag,
                scope=container.scope,
                include_prereleases=include_prereleases,
                registry=container.registry,
            )

            latest_tag = await client.get_latest_tag(
                container.image,
                container.current_tag,
                container.scope,
                current_digest=container.current_digest
                if container.current_tag == "latest"
                else None,
                include_prereleases=include_prereleases,
            )

            # ALWAYS check for major updates separately (even if scope blocks them)
            # This provides informational visibility to users about available major versions
            latest_major_tag = None
            if container.scope != "major":  # Optimization: skip if already major
                try:
                    latest_major_tag = await client.get_latest_major_tag(
                        container.image,
                        container.current_tag,
                        include_prereleases=include_prereleases,
                    )

                    # Only store if different from scope-filtered result
                    if latest_major_tag and latest_major_tag != latest_tag:
                        container.latest_major_tag = latest_major_tag
                        logger.info(
                            f"Major update available for {container.name} (blocked by scope={container.scope}): "
                            f"{container.current_tag} -> {latest_major_tag}"
                        )
                    else:
                        container.latest_major_tag = None
                except Exception as e:
                    # Don't fail entire check if major tag check fails
                    logger.warning(
                        f"Failed to check major updates for {container.name}: {e}"
                    )
                    container.latest_major_tag = None
            else:
                container.latest_major_tag = None

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
            container.last_checked = datetime.now(timezone.utc)

            # For 'latest' tag, also fetch and store the digest
            if container.current_tag == "latest":
                try:
                    metadata = await client.get_tag_metadata(container.image, "latest")
                    if metadata and metadata.get("digest"):
                        new_digest = metadata["digest"]
                        if previous_digest is None:
                            container.current_digest = new_digest
                            logger.info(
                                f"Stored initial digest for {container.name}: {new_digest}"
                            )
                        elif previous_digest != new_digest:
                            digest_changed = True
                            logger.info(
                                f"Detected digest change for {container.name}: "
                                f"{previous_digest} -> {new_digest}"
                            )
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        f"Registry HTTP error fetching digest for {container.name}: {e}"
                    )
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.warning(
                        f"Registry connection error fetching digest for {container.name}: {e}"
                    )
                except (ValueError, KeyError, AttributeError) as e:
                    logger.warning(f"Invalid digest metadata for {container.name}: {e}")

            digest_update = (
                container.current_tag == "latest"
                and digest_changed
                and new_digest is not None
            )

            # Capture digest info for trace
            if container.current_tag == "latest":
                trace.set_digest_update(previous_digest, new_digest, digest_changed)

            # Capture tag update info for trace
            if latest_tag and latest_tag != container.current_tag:
                detected_change_type = get_version_change_type(
                    container.current_tag, latest_tag
                )
                trace.set_tag_update(latest_tag, detected_change_type)

            if not latest_tag or latest_tag == container.current_tag:
                if not digest_update:
                    # No update available within scope
                    container.update_available = False
                    container.latest_tag = None
                    # Keep latest_major_tag if it exists (informational only)

                    # Check if there's a major update blocked by scope
                    if (
                        container.latest_major_tag
                        and container.latest_major_tag != container.current_tag
                    ):
                        # Create a scope-violation Update record for history visibility
                        result = await db.execute(
                            select(Update).where(
                                Update.container_id == container.id,
                                Update.from_tag == container.current_tag,
                                Update.to_tag == container.latest_major_tag,
                                Update.status.in_(["pending", "approved"]),
                            )
                        )
                        existing_scope_violation = result.scalar_one_or_none()

                        if not existing_scope_violation:
                            # Create new scope-violation update
                            max_retries = await SettingsService.get_int(
                                db, "update_retry_max_attempts", default=3
                            )
                            backoff_multiplier = await SettingsService.get_int(
                                db, "update_retry_backoff_multiplier", default=3
                            )

                            # Compute change_type for scope-violation update
                            scope_change_type = get_version_change_type(
                                container.current_tag, container.latest_major_tag
                            )

                            scope_update = Update(
                                container_id=container.id,
                                container_name=container.name,
                                from_tag=container.current_tag,
                                to_tag=container.latest_major_tag,
                                registry=container.registry,
                                reason_type="feature",
                                reason_summary=f"Major version update available (blocked by scope={container.scope})",
                                recommendation="Review required - change scope to major to apply",
                                status="pending",
                                scope_violation=1,
                                max_retries=max_retries,
                                backoff_multiplier=backoff_multiplier,
                                decision_trace=trace.to_json(),
                                update_kind="tag",
                                change_type=scope_change_type,
                                created_at=datetime.now(timezone.utc),
                                updated_at=datetime.now(timezone.utc),
                            )

                            db.add(scope_update)
                            try:
                                async with db.begin_nested():
                                    await db.flush()
                                await db.refresh(scope_update)
                                logger.info(
                                    f"Created scope-violation update for {container.name}: "
                                    f"{container.current_tag} -> {container.latest_major_tag} (scope={container.scope})"
                                )
                            except IntegrityError:
                                # Race condition, another process created it
                                logger.debug(
                                    f"Scope-violation update already exists for {container.name}"
                                )
                                await db.rollback()

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

                    return None

                # Treat digest change as an update even though the tag is unchanged
                latest_tag = container.current_tag

            # Update available!
            container.update_available = True
            if digest_update and new_digest:
                container.latest_tag = f"{latest_tag} [{new_digest[:12]}]"
            else:
                container.latest_tag = latest_tag

            logger.info(
                f"Update available for {container.name}: "
                f"{container.current_tag} -> {latest_tag}"
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
                if digest_update and new_digest:
                    existing_update.reason_type = "maintenance"
                    summary = (
                        f"Image digest updated: {previous_digest[:12]} -> {new_digest[:12]}"
                        if previous_digest
                        else "Image digest updated for latest tag"
                    )
                    existing_update.reason_summary = summary
                    existing_update.recommendation = (
                        "Recommended - refreshed image available"
                    )
                    existing_update.changelog = json.dumps(
                        {
                            "type": "digest_update",
                            "from_digest": previous_digest,
                            "to_digest": new_digest,
                        }
                    )
                logger.info(f"Update already exists for {container.name}")
                # Note: No flush needed - changes commit at end of check_all_containers()
                # The existing_update object is already populated from the query
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

            reason_summary = "New version available"
            reason_type = "unknown"
            recommendation: Optional[str] = None
            changelog_payload: Optional[str] = None

            if digest_update and new_digest:
                reason_type = "maintenance"
                if previous_digest:
                    reason_summary = f"Image digest updated: {previous_digest[:12]} → {new_digest[:12]}"
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

            # Get retry settings from configuration
            max_retries = await SettingsService.get_int(
                db, "update_retry_max_attempts", default=3
            )
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
                decision_trace=trace.to_json(),
                update_kind=trace.update_kind,
                change_type=trace.change_type,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            db.add(update)
            try:
                # Use savepoint to isolate insert from other pending changes
                # This prevents StaleDataError if container was modified elsewhere
                async with db.begin_nested():
                    await db.flush()
                await db.refresh(update)
            except IntegrityError as ie:
                # Race condition: another process created the same update
                logger.info(
                    f"Duplicate update detected for {container.name} "
                    f"({container.current_tag} -> {latest_tag}), using existing"
                )
                await db.rollback()
                # Re-fetch the existing update
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
                # If we can't find it, re-raise the error
                raise ie

            # Attempt changelog enrichment
            # Auto-detect release source if not already set
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
                # Try ghcr_token first (GitHub PAT), fallback to github_token if exists
                github_token = await SettingsService.get(
                    db, "ghcr_token"
                ) or await SettingsService.get(db, "github_token")
                fetcher = ChangelogFetcher(github_token=github_token)
                changelog = await fetcher.fetch(
                    release_source, container.image, latest_tag
                )
                if changelog:
                    classified_type, summary = ChangelogClassifier.classify(
                        changelog.raw_text
                    )
                    if classified_type != "unknown":
                        update.reason_type = classified_type
                    if summary:
                        update.reason_summary = summary
                    # Store full changelog and URL for display in UI
                    update.changelog = changelog.raw_text
                    if changelog.url:
                        update.changelog_url = changelog.url
                    # Save the detected source to the container for future use (only if changelog was found)
                    if detected_source:
                        from sqlalchemy import update as sql_update

                        await db.execute(
                            sql_update(Container)
                            .where(Container.id == container.id)
                            .values(release_source=detected_source)
                        )

            # Enrich with VulnForge data if enabled
            if container.vulnforge_enabled and not digest_update:
                await UpdateChecker._enrich_with_vulnforge(db, update, container)
            elif container.vulnforge_enabled and digest_update:
                await UpdateChecker._refresh_vulnforge_baseline(db, container)

            # Check if update should be auto-approved
            auto_update_enabled = await SettingsService.get_bool(
                db, "auto_update_enabled", default=False
            )
            should_approve, approval_reason = await UpdateChecker._should_auto_approve(
                container, update, auto_update_enabled
            )

            if should_approve:
                logger.info(
                    f"Auto-approving update for {container.name}: {approval_reason}"
                )
                update.status = "approved"
                update.approved_by = "system"
                update.approved_at = datetime.now(timezone.utc)
                # Note: No flush needed here - changes are committed at end of check_all_containers()

            # Send notifications via dispatcher (handles all enabled services)
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

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Registry HTTP error checking updates for {container.name}: {e}"
            )
            await event_bus.publish(
                {
                    "type": "update-check-error",
                    "container_id": container.id,
                    "container_name": container.name,
                    "message": f"Registry HTTP error: {str(e)}",
                }
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(
                f"Registry connection error checking updates for {container.name}: {e}"
            )
            await event_bus.publish(
                {
                    "type": "update-check-error",
                    "container_id": container.id,
                    "container_name": container.name,
                    "message": f"Registry connection error: {str(e)}",
                }
            )
            return None
        except OperationalError as e:
            logger.error(f"Database error checking updates for {container.name}: {e}")
            await event_bus.publish(
                {
                    "type": "update-check-error",
                    "container_id": container.id,
                    "container_name": container.name,
                    "message": f"Database error: {str(e)}",
                }
            )
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid data checking updates for {container.name}: {e}")
            await event_bus.publish(
                {
                    "type": "update-check-error",
                    "container_id": container.id,
                    "container_name": container.name,
                    "message": f"Invalid data: {str(e)}",
                }
            )
            return None
        finally:
            try:
                await client.close()
            except Exception as close_error:
                logger.warning(
                    f"Failed to close registry client for {container.name}: {close_error}"
                )

    @staticmethod
    async def apply_decision(
        db: AsyncSession,
        container: Container,
        decision: "UpdateDecision",
        fetch_response: "FetchTagsResponse",
    ) -> Optional[Update]:
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
        logger.debug(
            f"Applying decision for {container.name}: has_update={decision.has_update}"
        )

        # Update last_checked timestamp
        container.last_checked = datetime.now(timezone.utc)

        # Update latest_major_tag for scope visibility
        if (
            decision.latest_major_tag
            and decision.latest_major_tag != container.current_tag
        ):
            container.latest_major_tag = decision.latest_major_tag
        else:
            container.latest_major_tag = None

        # Handle digest update for 'latest' tag
        if decision.digest_changed and decision.new_digest:
            container.current_digest = decision.new_digest

        # Determine if we have an in-scope update
        is_digest_update = decision.update_kind == "digest"

        if not decision.has_update:
            # No update available within scope
            container.update_available = False
            container.latest_tag = None

            # Handle scope violation (major update blocked by scope)
            if decision.is_scope_violation and decision.latest_major_tag:
                await UpdateChecker._create_scope_violation_update(
                    db, container, decision
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

            return None

        # Update available!
        latest_tag = decision.latest_tag or container.current_tag
        container.update_available = True

        if is_digest_update and decision.new_digest:
            container.latest_tag = f"{latest_tag} [{decision.new_digest[:12]}]"
        else:
            container.latest_tag = latest_tag

        logger.info(
            f"Update available for {container.name}: "
            f"{container.current_tag} -> {latest_tag}"
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
                previous_digest = container.current_digest
                existing_update.reason_type = "maintenance"
                summary = f"Image digest updated: {previous_digest[:12] if previous_digest else 'unknown'} -> {decision.new_digest[:12]}"
                existing_update.reason_summary = summary
                existing_update.recommendation = (
                    "Recommended - refreshed image available"
                )
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
        recommendation: Optional[str] = None
        changelog_payload: Optional[str] = None

        if is_digest_update and decision.new_digest:
            previous_digest = container.current_digest
            reason_type = "maintenance"
            if previous_digest:
                reason_summary = f"Image digest updated: {previous_digest[:12]} -> {decision.new_digest[:12]}"
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
        max_retries = await SettingsService.get_int(
            db, "update_retry_max_attempts", default=3
        )
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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
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
                changelog = await fetcher.fetch(
                    release_source, container.image, latest_tag
                )
                if changelog:
                    classified_type, summary = ChangelogClassifier.classify(
                        changelog.raw_text
                    )
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

        # Auto-approval check
        auto_update_enabled = await SettingsService.get_bool(
            db, "auto_update_enabled", default=False
        )
        should_approve, approval_reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled
        )

        if should_approve:
            logger.info(
                f"Auto-approving update for {container.name}: {approval_reason}"
            )
            update.status = "approved"
            update.approved_by = "system"
            update.approved_at = datetime.now(timezone.utc)

        # Send notifications
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
        decision: "UpdateDecision",
    ) -> None:
        """Create an Update record for scope-violated major version.

        Args:
            db: Database session
            container: Container with blocked major update
            decision: UpdateDecision with scope violation info
        """
        if not decision.latest_major_tag:
            return

        # Check if scope-violation update already exists
        result = await db.execute(
            select(Update).where(
                Update.container_id == container.id,
                Update.from_tag == container.current_tag,
                Update.to_tag == decision.latest_major_tag,
                Update.status.in_(["pending", "approved"]),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return

        max_retries = await SettingsService.get_int(
            db, "update_retry_max_attempts", default=3
        )
        backoff_multiplier = await SettingsService.get_int(
            db, "update_retry_backoff_multiplier", default=3
        )

        scope_change_type = get_version_change_type(
            container.current_tag, decision.latest_major_tag
        )

        scope_update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag=container.current_tag,
            to_tag=decision.latest_major_tag,
            registry=container.registry,
            reason_type="feature",
            reason_summary=f"Major version update available (blocked by scope={container.scope})",
            recommendation="Review required - change scope to major to apply",
            status="pending",
            scope_violation=1,
            max_retries=max_retries,
            backoff_multiplier=backoff_multiplier,
            decision_trace=decision.trace.to_json(),
            update_kind="tag",
            change_type=scope_change_type,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db.add(scope_update)
        try:
            async with db.begin_nested():
                await db.flush()
            await db.refresh(scope_update)
            logger.info(
                f"Created scope-violation update for {container.name}: "
                f"{container.current_tag} -> {decision.latest_major_tag} (scope={container.scope})"
            )
        except IntegrityError:
            logger.debug(f"Scope-violation update already exists for {container.name}")
            await db.rollback()

    @staticmethod
    async def get_pending_updates(db: AsyncSession) -> List[Update]:
        """Get all pending updates.

        Args:
            db: Database session

        Returns:
            List of pending updates
        """
        result = await db.execute(
            select(Update)
            .where(Update.status == "pending")
            .order_by(Update.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_auto_approvable_updates(db: AsyncSession) -> List[Update]:
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
        return result.scalars().all()

    @staticmethod
    async def get_security_updates(db: AsyncSession) -> List[Update]:
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
        return result.scalars().all()

    @staticmethod
    async def _enrich_with_vulnforge(
        db: AsyncSession, update: Update, container: Container
    ):
        """Enrich update record with VulnForge vulnerability data.

        Args:
            db: Database session
            update: Update record to enrich
            container: Container being updated
        """
        try:
            # Get VulnForge settings
            vulnforge_enabled = await SettingsService.get_bool(db, "vulnforge_enabled")
            if not vulnforge_enabled:
                logger.debug("VulnForge integration disabled")
                return

            vulnforge_url = await SettingsService.get(db, "vulnforge_url")
            if not vulnforge_url:
                logger.warning("VulnForge URL not configured")
                return

            # Get authentication settings
            auth_type = await SettingsService.get(db, "vulnforge_auth_type") or "none"
            vulnforge_api_key = await SettingsService.get(db, "vulnforge_api_key")
            vulnforge_username = await SettingsService.get(db, "vulnforge_username")
            vulnforge_password = await SettingsService.get(db, "vulnforge_password")

            # Create VulnForge client
            vulnforge = VulnForgeClient(
                base_url=vulnforge_url,
                auth_type=auth_type,
                api_key=vulnforge_api_key,
                username=vulnforge_username,
                password=vulnforge_password,
            )

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

                # Check if update should be blocked
                if container.policy == "security" and not comparison["is_safe"]:
                    logger.warning(
                        f"Blocking update for {container.name}: "
                        f"introduces {comparison['delta']['total']} vulnerabilities"
                    )
                    update.status = "rejected"
                    update.reason_summary = (
                        f"Auto-rejected: {comparison['summary']} (security policy)"
                    )

                # Update container vulnerability count
                if comparison["current"]:
                    container.current_vuln_count = comparison["current"]["total_vulns"]

                logger.info(
                    f"VulnForge enrichment for {container.name}: "
                    f"{comparison['summary']}"
                )

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
        """Remove stale pending/approved update records for a container."""
        await db.execute(
            delete(Update).where(
                Update.container_id == container_id,
                Update.status.in_(("pending", "approved")),
            )
        )

    @staticmethod
    async def _refresh_vulnforge_baseline(
        db: AsyncSession,
        container: Container,
    ) -> None:
        """Refresh current vulnerability count from VulnForge for a container."""
        try:
            vulnforge_enabled = await SettingsService.get_bool(db, "vulnforge_enabled")
            if not vulnforge_enabled:
                return

            vulnforge_url = await SettingsService.get(db, "vulnforge_url")
            if not vulnforge_url:
                logger.debug("VulnForge URL not configured; skipping baseline refresh")
                return

            auth_type = await SettingsService.get(db, "vulnforge_auth_type") or "none"
            vulnforge_api_key = await SettingsService.get(db, "vulnforge_api_key")
            vulnforge_username = await SettingsService.get(db, "vulnforge_username")
            vulnforge_password = await SettingsService.get(db, "vulnforge_password")

            vulnforge = VulnForgeClient(
                base_url=vulnforge_url,
                auth_type=auth_type,
                api_key=vulnforge_api_key,
                username=vulnforge_username,
                password=vulnforge_password,
            )

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
                        f"VulnForge baseline missing for {container.name} "
                        f"({container.current_tag})"
                    )
            finally:
                await vulnforge.close()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"VulnForge HTTP error refreshing baseline for {container.name}: {e}"
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(
                f"VulnForge connection error refreshing baseline for {container.name}: {e}"
            )
        except OperationalError as e:
            logger.error(
                f"Database error refreshing VulnForge baseline for {container.name}: {e}"
            )
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(
                f"Invalid VulnForge data refreshing baseline for {container.name}: {e}"
            )
