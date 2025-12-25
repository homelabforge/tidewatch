"""Notification dispatcher for routing events to enabled services."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SettingsService
from app.services.notifications.base import NotificationService
from app.services.notifications.ntfy import NtfyNotificationService
from app.services.notifications.gotify import GotifyNotificationService
from app.services.notifications.pushover import PushoverNotificationService
from app.services.notifications.slack import SlackNotificationService
from app.services.notifications.discord import DiscordNotificationService
from app.services.notifications.telegram import TelegramNotificationService
from app.services.notifications.email import EmailNotificationService

logger = logging.getLogger(__name__)

# Event type to settings key mapping
EVENT_SETTINGS_MAP = {
    # Updates
    "update_available": ("notify_updates_enabled", "notify_updates_available"),
    "update_applied_success": (
        "notify_updates_enabled",
        "notify_updates_applied_success",
    ),
    "update_applied_failed": (
        "notify_updates_enabled",
        "notify_updates_applied_failed",
    ),
    "update_rollback": ("notify_updates_enabled", "notify_updates_rollback"),
    # Restarts
    "restart_scheduled": ("notify_restarts_enabled", "notify_restarts_scheduled"),
    "restart_success": ("notify_restarts_enabled", "notify_restarts_success"),
    "restart_failure": ("notify_restarts_enabled", "notify_restarts_failure"),
    "restart_max_retries": ("notify_restarts_enabled", "notify_restarts_max_retries"),
    # System
    "check_complete": ("notify_system_enabled", "notify_system_check_complete"),
    "dockerfile_update": ("notify_system_enabled", "notify_system_dockerfile_updates"),
}

# Priority mapping for different event types
EVENT_PRIORITY_MAP = {
    "update_available": "default",
    "update_applied_success": "low",
    "update_applied_failed": "high",
    "update_rollback": "default",
    "restart_scheduled": "default",
    "restart_success": "low",
    "restart_failure": "high",
    "restart_max_retries": "urgent",
    "check_complete": "default",
    "dockerfile_update": "default",
}

# Tags mapping for different event types
EVENT_TAGS_MAP = {
    "update_available": ["package", "arrow_up"],
    "update_applied_success": ["white_check_mark", "package"],
    "update_applied_failed": ["x", "warning"],
    "update_rollback": ["warning", "rewind"],
    "restart_scheduled": ["arrows_counterclockwise", "alarm_clock"],
    "restart_success": ["white_check_mark", "rocket"],
    "restart_failure": ["warning", "x"],
    "restart_max_retries": ["rotating_light", "sos"],
    "check_complete": ["ocean", "mag"],
    "dockerfile_update": ["whale", "arrow_up"],
}

# Service-specific retry delay multipliers
SERVICE_RETRY_MULTIPLIERS = {
    "discord": 1.5,  # Discord rate limits - slightly longer delay
    "slack": 1.2,  # Slack can be sensitive too
    "telegram": 1.0,  # Telegram is robust
    "ntfy": 1.0,  # Self-hosted, usually fast
    "gotify": 1.0,  # Self-hosted
    "pushover": 1.0,  # Cloud service, robust
    "email": 2.0,  # SMTP can be slow, longer delays
}


class NotificationDispatcher:
    """Routes notification events to all enabled notification services."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the dispatcher.

        Args:
            db: Database session for reading settings
        """
        self.db = db

    async def _is_event_enabled(self, event_type: str) -> bool:
        """Check if an event type is enabled in settings.

        Args:
            event_type: The event type to check

        Returns:
            True if the event should trigger notifications
        """
        settings_keys = EVENT_SETTINGS_MAP.get(event_type)
        if not settings_keys:
            logger.warning(f"Unknown event type: {event_type}")
            return False

        group_key, event_key = settings_keys

        # Check if group is enabled
        group_enabled = await SettingsService.get_bool(
            self.db, group_key, default=False
        )
        if not group_enabled:
            return False

        # Check if specific event is enabled
        event_enabled = await SettingsService.get_bool(
            self.db, event_key, default=False
        )
        return event_enabled

    async def _get_enabled_services(self) -> list[NotificationService]:
        """Get list of enabled and configured notification services.

        Returns:
            List of instantiated notification services
        """
        services: list[NotificationService] = []

        # Check ntfy
        if await SettingsService.get_bool(self.db, "ntfy_enabled", default=False):
            server = await SettingsService.get(self.db, "ntfy_server")
            topic = await SettingsService.get(
                self.db, "ntfy_topic", default="tidewatch"
            )
            api_key = await SettingsService.get(self.db, "ntfy_token")
            if server and topic:
                services.append(NtfyNotificationService(server, topic, api_key))

        # Check gotify
        if await SettingsService.get_bool(self.db, "gotify_enabled", default=False):
            server = await SettingsService.get(self.db, "gotify_server")
            token = await SettingsService.get(self.db, "gotify_token")
            if server and token:
                services.append(GotifyNotificationService(server, token))

        # Check pushover
        if await SettingsService.get_bool(self.db, "pushover_enabled", default=False):
            user_key = await SettingsService.get(self.db, "pushover_user_key")
            api_token = await SettingsService.get(self.db, "pushover_api_token")
            if user_key and api_token:
                services.append(PushoverNotificationService(user_key, api_token))

        # Check slack
        if await SettingsService.get_bool(self.db, "slack_enabled", default=False):
            webhook_url = await SettingsService.get(self.db, "slack_webhook_url")
            if webhook_url:
                services.append(SlackNotificationService(webhook_url))

        # Check discord
        if await SettingsService.get_bool(self.db, "discord_enabled", default=False):
            webhook_url = await SettingsService.get(self.db, "discord_webhook_url")
            if webhook_url:
                services.append(DiscordNotificationService(webhook_url))

        # Check telegram
        if await SettingsService.get_bool(self.db, "telegram_enabled", default=False):
            bot_token = await SettingsService.get(self.db, "telegram_bot_token")
            chat_id = await SettingsService.get(self.db, "telegram_chat_id")
            if bot_token and chat_id:
                services.append(TelegramNotificationService(bot_token, chat_id))

        # Check email
        if await SettingsService.get_bool(self.db, "email_enabled", default=False):
            smtp_host = await SettingsService.get(self.db, "email_smtp_host")
            smtp_port = await SettingsService.get_int(
                self.db, "email_smtp_port", default=587
            )
            smtp_user = await SettingsService.get(self.db, "email_smtp_user")
            smtp_password = await SettingsService.get(self.db, "email_smtp_password")
            from_address = await SettingsService.get(self.db, "email_from")
            to_address = await SettingsService.get(self.db, "email_to")
            use_tls = await SettingsService.get_bool(
                self.db, "email_smtp_tls", default=True
            )
            if (
                smtp_host
                and smtp_user
                and smtp_password
                and from_address
                and to_address
            ):
                services.append(
                    EmailNotificationService(
                        smtp_host,
                        smtp_port,
                        smtp_user,
                        smtp_password,
                        from_address,
                        to_address,
                        use_tls,
                    )
                )

        return services

    async def dispatch(
        self,
        event_type: str,
        title: str,
        message: str,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification to all enabled services for this event type.

        Args:
            event_type: Event type (e.g., "update_available")
            title: Notification title
            message: Notification body
            priority: Optional priority override
            tags: Optional tags override
            url: Optional click URL

        Returns:
            Dict of {service_name: success_bool}
        """
        results: dict[str, bool] = {}

        # Check if this event type is enabled
        if not await self._is_event_enabled(event_type):
            logger.debug(
                f"Event type '{event_type}' is disabled, skipping notifications"
            )
            return results

        # Get enabled services
        services = await self._get_enabled_services()
        if not services:
            logger.debug("No notification services enabled")
            return results

        # Use default priority/tags if not provided
        final_priority = priority or EVENT_PRIORITY_MAP.get(event_type, "default")
        final_tags = tags or EVENT_TAGS_MAP.get(event_type, [])

        # Load global retry settings once
        max_attempts = await SettingsService.get_int(
            self.db, "notification_retry_attempts", default=3
        )
        base_delay = float(
            await SettingsService.get(
                self.db, "notification_retry_delay", default="2.0"
            )
        )

        # Send to all enabled services
        for service in services:
            try:
                # Adapt delay per service
                multiplier = SERVICE_RETRY_MULTIPLIERS.get(service.service_name, 1.0)
                service_delay = base_delay * multiplier

                # Use retry for high-priority events, direct send for low-priority
                if final_priority in ("urgent", "high"):
                    success = await service.send_with_retry(
                        title=title,
                        message=message,
                        priority=final_priority,
                        tags=final_tags,
                        url=url,
                        max_attempts=max_attempts,
                        retry_delay=service_delay,
                    )
                else:
                    success = await service.send(
                        title=title,
                        message=message,
                        priority=final_priority,
                        tags=final_tags,
                        url=url,
                    )
                results[service.service_name] = success
            except Exception as e:
                logger.error(f"Error sending to {service.service_name}: {e}")
                results[service.service_name] = False
            finally:
                await service.close()

        return results

    # Convenience methods for common notification types

    async def notify_update_available(
        self,
        container_name: str,
        from_tag: str,
        to_tag: str,
        reason: str,
    ) -> dict[str, bool]:
        """Send notification about available update."""
        return await self.dispatch(
            event_type="update_available",
            title=f"Update Available: {container_name}",
            message=f"{container_name}: {from_tag} → {to_tag}\n\n{reason}",
        )

    async def notify_security_update(
        self,
        container_name: str,
        from_tag: str,
        to_tag: str,
        cves_fixed: list[str],
        vuln_delta: int,
    ) -> dict[str, bool]:
        """Send notification about security update."""
        cve_list = ", ".join(cves_fixed[:5])
        if len(cves_fixed) > 5:
            cve_list += f" +{len(cves_fixed) - 5} more"

        message = f"{container_name}: {from_tag} → {to_tag}\n\n"
        message += f"Fixes {len(cves_fixed)} CVE(s): {cve_list}\n"
        message += f"Vulnerability delta: {vuln_delta}"

        return await self.dispatch(
            event_type="update_available",
            title=f"Security Update: {container_name}",
            message=message,
            priority="high",
            tags=["shield", "rotating_light"],
        )

    async def notify_update_applied(
        self,
        container_name: str,
        to_tag: str,
        success: bool,
        reason_type: Optional[str] = None,
        reason_summary: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about applied update."""
        event_type = "update_applied_success" if success else "update_applied_failed"

        reason_label = (reason_type or "update").replace("_", " ").title()
        detail = f" – {reason_label}"
        if reason_summary:
            detail += f": {reason_summary}"

        if success:
            title = f"Update Applied: {container_name}"
            message = f"Updated {container_name} to {to_tag}{detail}"
        else:
            title = f"Update Failed: {container_name}"
            message = f"Failed to update {container_name} to {to_tag}{detail}"

        return await self.dispatch(
            event_type=event_type,
            title=title,
            message=message,
        )

    async def notify_rollback(
        self,
        container_name: str,
        from_tag: str,
    ) -> dict[str, bool]:
        """Send notification about rollback."""
        return await self.dispatch(
            event_type="update_rollback",
            title=f"Rollback: {container_name}",
            message=f"{container_name} rolled back from {from_tag}",
        )

    async def notify_check_complete(
        self,
        checked: int,
        updates_found: int,
        errors: int,
    ) -> dict[str, bool]:
        """Send notification about update check completion."""
        message = f"Checked {checked} container(s)\n"
        message += f"Found {updates_found} update(s)\n"
        if errors > 0:
            message += f"Errors: {errors}"

        priority = "high" if updates_found > 0 else "default"

        return await self.dispatch(
            event_type="check_complete",
            title="TideWatch: Update Check Complete",
            message=message,
            priority=priority,
        )

    async def notify_restart_scheduled(
        self,
        container_name: str,
        attempt: int,
        delay_seconds: float,
        reason: str,
    ) -> dict[str, bool]:
        """Send notification that a restart has been scheduled."""
        return await self.dispatch(
            event_type="restart_scheduled",
            title=f"Restart Scheduled: {container_name}",
            message=f"Attempt {attempt} scheduled in {delay_seconds:.0f}s\nReason: {reason}",
        )

    async def notify_restart_success(
        self,
        container_name: str,
        attempt: int,
    ) -> dict[str, bool]:
        """Send notification about successful restart."""
        return await self.dispatch(
            event_type="restart_success",
            title=f"Restart Success: {container_name}",
            message=f"{container_name} successfully restarted after {attempt} attempt(s)",
        )

    async def notify_restart_failure(
        self,
        container_name: str,
        attempt: int,
        error: str,
    ) -> dict[str, bool]:
        """Send notification about failed restart attempt."""
        return await self.dispatch(
            event_type="restart_failure",
            title=f"Restart Failed: {container_name}",
            message=f"Attempt {attempt} failed\nError: {error}",
        )

    async def notify_max_retries_reached(
        self,
        container_name: str,
        attempts: int,
        exit_code: int,
    ) -> dict[str, bool]:
        """Send notification that max restart attempts have been reached."""
        return await self.dispatch(
            event_type="restart_max_retries",
            title=f"Max Restarts Reached: {container_name}",
            message=f"Failed {attempts} restart attempts\nExit code: {exit_code}\nManual intervention required.",
        )

    async def notify_dockerfile_update(
        self,
        image_name: str,
        from_tag: str,
        to_tag: str,
        dependency_type: str = "base_image",
    ) -> dict[str, bool]:
        """Send notification about Dockerfile dependency update."""
        dep_label = "Base Image" if dependency_type == "base_image" else "Build Image"
        return await self.dispatch(
            event_type="dockerfile_update",
            title="Dockerfile Update Available",
            message=f"{dep_label}: {image_name}\n{from_tag} → {to_tag}",
        )
