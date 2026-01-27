"""Pushover notification service for TideWatch."""

import logging

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Pushover priority mapping (-2 to 2 scale)
PRIORITY_MAP = {
    "min": -2,  # No notification
    "low": -1,  # Quiet notification
    "default": 0,  # Normal priority
    "high": 1,  # High priority, bypass quiet hours
    "urgent": 2,  # Emergency, requires acknowledgment
}

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotificationService(NotificationService):
    """Pushover push notification service implementation."""

    service_name = "pushover"

    def __init__(self, user_key: str, api_token: str) -> None:
        """Initialize Pushover service.

        Args:
            user_key: Pushover user key
            api_token: Pushover application API token
        """
        self.user_key = user_key
        self.api_token = api_token
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
        """Send a notification via Pushover.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, urgent)
            tags: Optional list of tags (added to message as prefix)
            url: Optional click URL

        Returns:
            True if notification sent successfully
        """
        try:
            # Build message with optional tags prefix
            full_message = message
            if tags:
                tag_str = " ".join(f"[{tag}]" for tag in tags[:3])
                full_message = f"{tag_str}\n{message}"

            pushover_priority = PRIORITY_MAP.get(priority, 0)

            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "title": title,
                "message": full_message,
                "priority": pushover_priority,
            }

            if url:
                payload["url"] = url
                payload["url_title"] = "Open TideWatch"

            # Emergency priority requires retry and expire parameters
            if pushover_priority == 2:
                payload["retry"] = 60  # Retry every 60 seconds
                payload["expire"] = 3600  # Expire after 1 hour

            response = await self.client.post(PUSHOVER_API_URL, data=payload)
            response.raise_for_status()

            result = response.json()
            if result.get("status") == 1:
                logger.info(f"[pushover] Sent notification: {title}")
                return True
            else:
                logger.error(
                    f"[pushover] API error: {result.get('errors', 'Unknown error')}"
                )
                return False

        except httpx.HTTPStatusError as e:
            logger.error(f"[pushover] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[pushover] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[pushover] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test Pushover connection by validating credentials.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Use validate endpoint to check credentials without sending
            validate_url = "https://api.pushover.net/1/users/validate.json"
            response = await self.client.post(
                validate_url,
                data={
                    "token": self.api_token,
                    "user": self.user_key,
                },
            )

            result = response.json()
            if result.get("status") == 1:
                # Also send a test notification
                success = await self.send(
                    title="TideWatch Test",
                    message="This is a test notification from TideWatch.",
                    priority="low",
                )
                if success:
                    return True, "Credentials valid, test notification sent"
                return True, "Credentials valid but test notification failed"
            else:
                errors = result.get("errors", ["Unknown error"])
                return False, f"Validation failed: {', '.join(errors)}"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
