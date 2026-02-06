"""ntfy notification service for TideWatch."""

import logging

import httpx

from app.exceptions import SSRFProtectionError
from app.services.notifications.base import NotificationService
from app.utils.url_validation import validate_url_for_ssrf

logger = logging.getLogger(__name__)


class NtfyNotificationService(NotificationService):
    """ntfy push notification service implementation."""

    service_name = "ntfy"

    def __init__(
        self,
        server_url: str,
        topic: str,
        api_key: str | None = None,
    ) -> None:
        """Initialize ntfy service.

        Args:
            server_url: ntfy server URL (e.g., https://ntfy.sh)
            topic: ntfy topic to publish to
            api_key: Optional API key for authentication

        Raises:
            SSRFProtectionError: If server URL fails SSRF validation
        """
        # Validate server URL to prevent SSRF attacks
        # Allow both HTTP and HTTPS for self-hosted ntfy instances
        try:
            validate_url_for_ssrf(
                server_url,
                allowed_schemes=["http", "https"],
                block_private_ips=False,  # Allow for self-hosted instances
            )
        except SSRFProtectionError as e:
            logger.error(f"[ntfy] Server URL failed SSRF validation: {e}")
            raise

        self.server_url = server_url.rstrip("/")
        self.topic = topic
        self.headers: dict[str, str] = {}

        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

        self.client = httpx.AsyncClient(timeout=10.0, headers=self.headers)

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
        """Send a notification via ntfy.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, urgent)
            tags: Optional list of emoji tags
            url: Optional click URL

        Returns:
            True if notification sent successfully
        """
        try:
            endpoint = f"{self.server_url}/{self.topic}"

            headers = self.headers.copy()
            if title:
                headers["Title"] = title
            if priority:
                headers["Priority"] = priority
            if tags:
                headers["Tags"] = ",".join(tags)
            if url:
                headers["Click"] = url

            # HTTP headers with non-ASCII content (emojis) need special handling
            # httpx accepts bytes values for headers, which bypass ASCII validation
            # ntfy will interpret the raw UTF-8 bytes correctly
            encoded_headers: list[tuple] = []
            for key, value in headers.items():
                if isinstance(value, str):
                    try:
                        # Try ASCII first (most headers)
                        value.encode("ascii")
                        encoded_headers.append((key, value))
                    except UnicodeEncodeError:
                        # For Unicode (emojis), pass raw UTF-8 bytes
                        encoded_headers.append((key.encode("utf-8"), value.encode("utf-8")))
                else:
                    encoded_headers.append((key, value))

            response = await self.client.post(endpoint, content=message, headers=encoded_headers)
            response.raise_for_status()

            logger.info(f"[ntfy] Sent notification: {title}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"[ntfy] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[ntfy] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[ntfy] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test ntfy connection by sending a test notification.

        Returns:
            Tuple of (success, message)
        """
        try:
            success = await self.send(
                title="TideWatch Test",
                message="This is a test notification from TideWatch.",
                priority="low",
                tags=["white_check_mark", "test_tube"],
            )

            if success:
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
