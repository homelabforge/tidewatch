"""Gotify notification service for TideWatch."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService
from app.utils.url_validation import validate_url_for_ssrf
from app.exceptions import SSRFProtectionError

logger = logging.getLogger(__name__)

# Gotify priority mapping (0-10 scale)
PRIORITY_MAP = {
    "min": 1,
    "low": 3,
    "default": 5,
    "high": 7,
    "urgent": 10,
}


class GotifyNotificationService(NotificationService):
    """Gotify push notification service implementation."""

    service_name = "gotify"

    def __init__(self, server_url: str, app_token: str) -> None:
        """Initialize Gotify service.

        Args:
            server_url: Gotify server URL (e.g., https://gotify.example.com)
            app_token: Application token for authentication

        Raises:
            SSRFProtectionError: If server URL fails SSRF validation
        """
        # Validate server URL to prevent SSRF attacks
        # Allow both HTTP and HTTPS for self-hosted Gotify instances
        try:
            validate_url_for_ssrf(
                server_url,
                allowed_schemes=["http", "https"],
                block_private_ips=False,  # Allow for self-hosted instances
            )
        except SSRFProtectionError as e:
            logger.error(f"[gotify] Server URL failed SSRF validation: {e}")
            raise

        self.server_url = server_url.rstrip("/")
        self.app_token = app_token
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
        """Send a notification via Gotify.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, urgent)
            tags: Optional list of tags (added to message as prefix)
            url: Optional click URL (added to extras)

        Returns:
            True if notification sent successfully
        """
        try:
            endpoint = f"{self.server_url}/message"

            # Build message with optional tags prefix
            full_message = message
            if tags:
                # Convert tag names to emoji where possible
                tag_str = " ".join(f"[{tag}]" for tag in tags[:3])
                full_message = f"{tag_str}\n{message}"

            payload = {
                "title": title,
                "message": full_message,
                "priority": PRIORITY_MAP.get(priority, 5),
            }

            # Add click URL as extra if provided
            if url:
                payload["extras"] = {
                    "client::notification": {
                        "click": {"url": url}
                    }
                }

            response = await self.client.post(
                endpoint,
                json=payload,
                headers={"X-Gotify-Key": self.app_token},
            )
            response.raise_for_status()

            logger.info(f"[gotify] Sent notification: {title}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"[gotify] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[gotify] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[gotify] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test Gotify connection by sending a test notification.

        Returns:
            Tuple of (success, message)
        """
        try:
            success = await self.send(
                title="TideWatch Test",
                message="This is a test notification from TideWatch.",
                priority="low",
            )

            if success:
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
