"""Discord notification service for TideWatch."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService
from app.utils.url_validation import validate_url_for_ssrf
from app.exceptions import SSRFProtectionError

logger = logging.getLogger(__name__)

# Discord embed color mapping (decimal color values)
COLOR_MAP = {
    "min": 0x808080,  # Gray
    "low": 0x36A64F,  # Green
    "default": 0x2196F3,  # Blue
    "high": 0xFF9800,  # Orange
    "urgent": 0xF44336,  # Red
}


class DiscordNotificationService(NotificationService):
    """Discord webhook notification service implementation."""

    service_name = "discord"

    def __init__(self, webhook_url: str) -> None:
        """Initialize Discord service.

        Args:
            webhook_url: Discord webhook URL

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
            logger.error(f"[discord] Webhook URL failed SSRF validation: {e}")
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
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        """Send a notification via Discord webhook.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (determines embed color)
            tags: Optional list of tags (shown as emoji in title)
            url: Optional click URL

        Returns:
            True if notification sent successfully
        """
        try:
            # Build emoji prefix from tags
            emoji_prefix = ""
            if tags:
                emoji_map = {
                    "package": "\U0001f4e6",
                    "arrow_up": "\u2b06\ufe0f",
                    "shield": "\U0001f6e1\ufe0f",
                    "rotating_light": "\U0001f6a8",
                    "white_check_mark": "\u2705",
                    "x": "\u274c",
                    "warning": "\u26a0\ufe0f",
                    "rewind": "\u23ee\ufe0f",
                    "ocean": "\U0001f30a",
                    "mag": "\U0001f50d",
                    "whale": "\U0001f433",
                    "rocket": "\U0001f680",
                    "sparkles": "\u2728",
                    "hammer_and_wrench": "\U0001f6e0\ufe0f",
                    "gear": "\u2699\ufe0f",
                    "repeat": "\U0001f501",
                    "alarm_clock": "\u23f0",
                    "arrows_counterclockwise": "\U0001f504",
                    "sos": "\U0001f198",
                }
                emojis = [emoji_map.get(tag, "") for tag in tags[:3]]
                emoji_prefix = " ".join(e for e in emojis if e) + " "

            # Build Discord embed
            embed = {
                "title": f"{emoji_prefix}{title}",
                "description": message,
                "color": COLOR_MAP.get(priority, COLOR_MAP["default"]),
                "footer": {"text": "TideWatch"},
            }

            if url:
                embed["url"] = url

            payload = {
                "embeds": [embed],
            }

            response = await self.client.post(
                self.webhook_url,
                json=payload,
            )

            # Discord returns 204 No Content on success
            if response.status_code == 204:
                logger.info(f"[discord] Sent notification: {title}")
                return True
            else:
                response.raise_for_status()
                logger.info(f"[discord] Sent notification: {title}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"[discord] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[discord] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[discord] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test Discord webhook by sending a test notification.

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
