"""Email (SMTP) notification service for TideWatch."""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import aiosmtplib

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Priority to X-Priority header mapping
PRIORITY_MAP = {
    "min": "5",       # Lowest
    "low": "4",       # Low
    "default": "3",   # Normal
    "high": "2",      # High
    "urgent": "1",    # Highest
}


class EmailNotificationService(NotificationService):
    """Email SMTP notification service implementation."""

    service_name = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_address: str,
        to_address: str,
        use_tls: bool = True,
    ) -> None:
        """Initialize Email service.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_password: SMTP password
            from_address: Sender email address
            to_address: Recipient email address
            use_tls: Whether to use TLS (STARTTLS)
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.to_address = to_address
        self.use_tls = use_tls

    async def close(self) -> None:
        """No persistent connection to close."""
        pass

    async def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        """Send a notification via email.

        Args:
            title: Email subject
            message: Email body
            priority: Priority level (sets X-Priority header)
            tags: Optional list of tags (added to subject)
            url: Optional link (added to email body)

        Returns:
            True if email sent successfully
        """
        try:
            # Build subject with optional tags
            subject = title
            if tags:
                emoji_map = {
                    "package": "\U0001F4E6",
                    "arrow_up": "\u2B06",
                    "shield": "\U0001F6E1",
                    "rotating_light": "\U0001F6A8",
                    "white_check_mark": "\u2705",
                    "x": "\u274C",
                    "warning": "\u26A0",
                    "rewind": "\u23EE",
                    "ocean": "\U0001F30A",
                    "whale": "\U0001F433",
                    "rocket": "\U0001F680",
                }
                emojis = [emoji_map.get(tag, "") for tag in tags[:2]]
                prefix = "".join(e for e in emojis if e)
                if prefix:
                    subject = f"{prefix} {title}"

            # Build HTML email
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[TideWatch] {subject}"
            msg["From"] = self.from_address
            msg["To"] = self.to_address
            msg["X-Priority"] = PRIORITY_MAP.get(priority, "3")

            # Plain text version
            text_body = f"{title}\n\n{message}"
            if url:
                text_body += f"\n\nView in TideWatch: {url}"
            text_body += "\n\n--\nSent by TideWatch"

            # HTML version
            html_body = f"""
            <html>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: #14b8a6; color: white; padding: 15px 20px;">
                        <h2 style="margin: 0; font-size: 18px;">{title}</h2>
                    </div>
                    <div style="padding: 20px;">
                        <p style="margin: 0; white-space: pre-wrap; color: #333;">{message}</p>
                        {f'<p style="margin-top: 20px;"><a href="{url}" style="color: #14b8a6;">View in TideWatch →</a></p>' if url else ''}
                    </div>
                    <div style="padding: 15px 20px; background: #f9f9f9; border-top: 1px solid #eee; font-size: 12px; color: #666;">
                        Sent by TideWatch
                    </div>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Send email
            if self.use_tls:
                # Use STARTTLS
                await aiosmtplib.send(
                    msg,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_user,
                    password=self.smtp_password,
                    start_tls=True,
                )
            else:
                # Direct connection (use with caution)
                await aiosmtplib.send(
                    msg,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_user,
                    password=self.smtp_password,
                )

            logger.info(f"[email] Sent notification: {title}")
            return True

        except aiosmtplib.SMTPException as e:
            logger.error(f"[email] SMTP error: {e}")
            return False
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"[email] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[email] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        """Test SMTP connection by sending a test email.

        Returns:
            Tuple of (success, message)
        """
        try:
            success = await self.send(
                title="Test Notification",
                message="This is a test notification from TideWatch.\n\nIf you received this email, your SMTP settings are configured correctly.",
                priority="low",
                tags=["white_check_mark"],
            )

            if success:
                return True, f"Test email sent to {self.to_address}"
            return False, "Failed to send test email"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
