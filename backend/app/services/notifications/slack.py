"""Slack notification service for TideWatch."""

import logging

import httpx

from app.exceptions import SSRFProtectionError
from app.services.notifications.base import NotificationService
from app.utils.security import sanitize_log_message
from app.utils.url_validation import validate_url_for_ssrf

logger = logging.getLogger(__name__)

# Slack color mapping for attachments
COLOR_MAP = {
    "min": "#808080",  # Gray
    "low": "#36a64f",  # Green
    "default": "#2196F3",  # Blue
    "high": "#ff9800",  # Orange
    "urgent": "#f44336",  # Red
}


class SlackNotificationService(NotificationService):
    """Slack webhook notification service implementation."""

    service_name = "slack"

    def __init__(self, webhook_url: str) -> None:
        """Initialize Slack service.

        Args:
            webhook_url: Slack incoming webhook URL

        Raises:
            SSRFProtectionError: If webhook URL fails SSRF validation
        """
        # Validate webhook URL to prevent SSRF attacks
        try:
            validate_url_for_ssrf(
                webhook_url,
                allowed_schemes=["https"],
                block_private_ips=True,
            )
        except SSRFProtectionError as e:
            logger.error(f"[slack] Webhook URL failed SSRF validation: {e}")
            raise

        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
    ) -> bool:
        """Send a notification via Slack webhook.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (determines attachment color)
            tags: Optional list of tags (shown as emoji)
            url: Optional click URL

        Returns:
            True if notification sent successfully
        """
        try:
            # Build emoji prefix from tags
            emoji_prefix = ""
            if tags:
                emoji_map = {
                    "package": ":package:",
                    "arrow_up": ":arrow_up:",
                    "shield": ":shield:",
                    "rotating_light": ":rotating_light:",
                    "white_check_mark": ":white_check_mark:",
                    "x": ":x:",
                    "warning": ":warning:",
                    "rewind": ":rewind:",
                    "ocean": ":ocean:",
                    "mag": ":mag:",
                    "whale": ":whale:",
                    "rocket": ":rocket:",
                    "sparkles": ":sparkles:",
                    "hammer_and_wrench": ":hammer_and_wrench:",
                    "gear": ":gear:",
                    "repeat": ":repeat:",
                    "alarm_clock": ":alarm_clock:",
                    "arrows_counterclockwise": ":arrows_counterclockwise:",
                    "sos": ":sos:",
                }
                emojis = [emoji_map.get(tag, f":{tag}:") for tag in tags[:3]]
                emoji_prefix = " ".join(emojis) + " "

            # Build attachment with color based on priority
            attachment = {
                "color": COLOR_MAP.get(priority, COLOR_MAP["default"]),
                "title": f"{emoji_prefix}{title}",
                "text": message,
                "footer": "TideWatch",
            }

            if url:
                attachment["title_link"] = url

            payload = {
                "attachments": [attachment],
            }

            response = await self.client.post(
                self.webhook_url,
                json=payload,
            )
            response.raise_for_status()

            # Slack returns "ok" for successful webhook posts
            if response.text == "ok":
                logger.info(f"[slack] Sent notification: {sanitize_log_message(title)}")
                return True
            else:
                logger.error(f"[slack] Unexpected response: {sanitize_log_message(response.text)}")
                return False

        except httpx.HTTPStatusError as e:
            logger.error(f"[slack] HTTP error: {sanitize_log_message(str(e))}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[slack] Connection error: {sanitize_log_message(str(e))}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[slack] Invalid data: {sanitize_log_message(str(e))}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test Slack webhook by sending a test notification.

        Returns:
            Tuple of (success, message)
        """
        try:
            success = await self.send(
                title="TideWatch Test",
                message="This is a test notification from TideWatch.",
                priority="low",
                tags=["white_check_mark"],
            )

            if success:
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
