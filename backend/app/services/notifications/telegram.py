"""Telegram notification service for TideWatch."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramNotificationService(NotificationService):
    """Telegram bot notification service implementation."""

    service_name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        """Initialize Telegram service.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Target chat/channel ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
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
        """Send a notification via Telegram bot.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (affects notification sound)
            tags: Optional list of tags (shown as emoji)
            url: Optional click URL (added as inline button)

        Returns:
            True if notification sent successfully
        """
        try:
            endpoint = f"{TELEGRAM_API_URL}/bot{self.bot_token}/sendMessage"

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

            # Format message with HTML
            text = f"<b>{emoji_prefix}{title}</b>\n\n{message}"

            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": priority in ("min", "low"),
            }

            # Add inline button for URL if provided
            if url:
                payload["reply_markup"] = {
                    "inline_keyboard": [[{"text": "Open TideWatch", "url": url}]]
                }

            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                logger.info(f"[telegram] Sent notification: {title}")
                return True
            else:
                logger.error(f"[telegram] API error: {result.get('description', 'Unknown error')}")
                return False

        except httpx.HTTPStatusError as e:
            logger.error(f"[telegram] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[telegram] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[telegram] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test Telegram bot connection.

        Returns:
            Tuple of (success, message)
        """
        try:
            # First verify the bot token
            endpoint = f"{TELEGRAM_API_URL}/bot{self.bot_token}/getMe"
            response = await self.client.get(endpoint)
            result = response.json()

            if not result.get("ok"):
                return False, f"Invalid bot token: {result.get('description', 'Unknown error')}"

            bot_name = result.get("result", {}).get("username", "Unknown")

            # Send a test message
            success = await self.send(
                title="TideWatch Test",
                message=f"This is a test notification from TideWatch.\nBot: @{bot_name}",
                priority="low",
                tags=["white_check_mark"],
            )

            if success:
                return True, f"Connected to @{bot_name}, test message sent"
            return False, f"Bot @{bot_name} valid, but failed to send message to chat {self.chat_id}"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
