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
    "min": 0x808080,      # Gray
    "low": 0x36a64f,      # Green
    "default": 0x2196F3,  # Blue
    "high": 0xff9800,     # Orange
    "urgent": 0xf44336,   # Red
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
                    "package": "\U0001F4E6",
                    "arrow_up": "\u2B06\uFE0F",
                    "shield": "\U0001F6E1\uFE0F",
                    "rotating_light": "\U0001F6A8",
                    "white_check_mark": "\u2705",
                    "x": "\u274C",
                    "warning": "\u26A0\uFE0F",
                    "rewind": "\u23EE\uFE0F",
                    "ocean": "\U0001F30A",
                    "mag": "\U0001F50D",
                    "whale": "\U0001F433",
                    "rocket": "\U0001F680",
                    "sparkles": "\u2728",
                    "hammer_and_wrench": "\U0001F6E0\uFE0F",
                    "gear": "\u2699\uFE0F",
                    "repeat": "\U0001F501",
                    "alarm_clock": "\u23F0",
                    "arrows_counterclockwise": "\U0001F504",
                    "sos": "\U0001F198",
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
