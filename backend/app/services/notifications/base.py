"""Abstract base class for notification services."""

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class NotificationService(ABC):
    """Abstract base class for all notification services.

    Each notification service implementation must inherit from this class
    and implement the required methods.
    """

    # Service identifier used in settings keys and logging
    service_name: str = "base"

    @abstractmethod
    async def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
    ) -> bool:
        """Send a notification.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, urgent)
            tags: Optional list of tags/emoji
            url: Optional click URL

        Returns:
            True if notification was sent successfully
        """
        pass

    async def send_with_retry(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
        max_attempts: int = 3,
        retry_delay: float = 2.0,
    ) -> bool:
        """Send with simple retry logic for transient failures.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, urgent)
            tags: Optional list of tags/emoji
            url: Optional click URL
            max_attempts: Maximum number of send attempts
            retry_delay: Delay in seconds between attempts

        Returns:
            True if notification was sent successfully within max_attempts
        """
        for attempt in range(max_attempts):
            try:
                if await self.send(title, message, priority, tags, url):
                    return True
            except Exception as e:
                logger.warning(
                    f"[{self.service_name}] Attempt {attempt + 1}/{max_attempts} failed: {e}"
                )

            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay)

        logger.error(f"[{self.service_name}] All {max_attempts} attempts failed")
        return False

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """Test the service connection.

        Returns:
            Tuple of (success, message)
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (close HTTP clients, etc.)."""
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False
