"""Service layer for webhook management and delivery."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook
from app.schemas.webhook import (
    WebhookCreate,
    WebhookSchema,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


class WebhookService:
    """Service for managing and triggering webhooks."""

    # SSRF protection: block these IP ranges
    BLOCKED_IP_RANGES = [
        ipaddress.ip_network("127.0.0.0/8"),  # Loopback
        ipaddress.ip_network("10.0.0.0/8"),  # Private
        ipaddress.ip_network("172.16.0.0/12"),  # Private
        ipaddress.ip_network("192.168.0.0/16"),  # Private
        ipaddress.ip_network("169.254.0.0/16"),  # Link-local
        ipaddress.ip_network("::1/128"),  # IPv6 loopback
        ipaddress.ip_network("fc00::/7"),  # IPv6 private
        ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ]

    @staticmethod
    def _is_private_ip(hostname: str) -> bool:
        """Check if hostname resolves to a private IP address (SSRF protection).

        Args:
            hostname: Hostname or IP to check

        Returns:
            True if hostname resolves to private/loopback IP
        """
        try:
            # Resolve hostname to IP
            ip_str = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(ip_str)

            # Check against blocked ranges
            for blocked_range in WebhookService.BLOCKED_IP_RANGES:
                if ip in blocked_range:
                    logger.warning(f"Blocked private IP: {hostname} -> {ip_str}")
                    return True

            return False

        except (socket.gaierror, ValueError) as e:
            logger.warning(f"Failed to resolve hostname {hostname}: {e}")
            # If we can't resolve, block it to be safe
            return True

    @staticmethod
    async def create_webhook(db: AsyncSession, webhook_data: WebhookCreate) -> WebhookSchema:
        """Create a new webhook with SSRF protection.

        Args:
            db: Database session
            webhook_data: Webhook configuration

        Returns:
            Created webhook

        Raises:
            ValueError: If URL points to private IP (SSRF protection)
        """
        # SSRF protection - check if URL points to private IP
        parsed_url = urlparse(str(webhook_data.url))
        if parsed_url.hostname and WebhookService._is_private_ip(parsed_url.hostname):
            raise ValueError(
                f"Webhook URL cannot point to private/internal IP addresses. "
                f"Host: {parsed_url.hostname}"
            )

        # Encrypt the secret before storing
        encrypted_secret = encrypt_value(webhook_data.secret)

        # Create webhook
        webhook = Webhook(
            name=webhook_data.name,
            url=str(webhook_data.url),
            secret=encrypted_secret,
            events=webhook_data.events,
            enabled=webhook_data.enabled,
            retry_count=webhook_data.retry_count,
        )

        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        return WebhookSchema.model_validate(webhook)

    @staticmethod
    async def list_webhooks(db: AsyncSession) -> list[WebhookSchema]:
        """List all webhooks.

        Args:
            db: Database session

        Returns:
            List of webhooks
        """
        result = await db.execute(select(Webhook).order_by(Webhook.created_at.desc()))
        webhooks = result.scalars().all()
        return [WebhookSchema.model_validate(w) for w in webhooks]

    @staticmethod
    async def get_webhook(db: AsyncSession, webhook_id: int) -> WebhookSchema | None:
        """Get webhook by ID.

        Args:
            db: Database session
            webhook_id: Webhook ID

        Returns:
            Webhook or None if not found
        """
        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        webhook = result.scalar_one_or_none()

        if webhook:
            return WebhookSchema.model_validate(webhook)
        return None

    @staticmethod
    async def update_webhook(
        db: AsyncSession, webhook_id: int, webhook_data: WebhookUpdate
    ) -> WebhookSchema | None:
        """Update an existing webhook.

        Args:
            db: Database session
            webhook_id: Webhook ID
            webhook_data: Updated webhook data

        Returns:
            Updated webhook or None if not found

        Raises:
            ValueError: If new URL points to private IP
        """
        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        webhook = result.scalar_one_or_none()

        if not webhook:
            return None

        # If URL is being updated, check SSRF protection
        if webhook_data.url:
            parsed_url = urlparse(str(webhook_data.url))
            if parsed_url.hostname and WebhookService._is_private_ip(parsed_url.hostname):
                raise ValueError(
                    f"Webhook URL cannot point to private/internal IP addresses. "
                    f"Host: {parsed_url.hostname}"
                )
            webhook.url = str(webhook_data.url)

        # Update fields
        if webhook_data.name is not None:
            webhook.name = webhook_data.name
        if webhook_data.secret is not None:
            webhook.secret = encrypt_value(webhook_data.secret)
        if webhook_data.events is not None:
            webhook.events = webhook_data.events
        if webhook_data.enabled is not None:
            webhook.enabled = webhook_data.enabled
        if webhook_data.retry_count is not None:
            webhook.retry_count = webhook_data.retry_count

        await db.commit()
        await db.refresh(webhook)

        return WebhookSchema.model_validate(webhook)

    @staticmethod
    async def delete_webhook(db: AsyncSession, webhook_id: int) -> bool:
        """Delete a webhook.

        Args:
            db: Database session
            webhook_id: Webhook ID

        Returns:
            True if deleted, False if not found
        """
        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        webhook = result.scalar_one_or_none()

        if not webhook:
            return False

        await db.delete(webhook)
        await db.commit()
        return True

    @staticmethod
    def _generate_signature(payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for webhook payload.

        Args:
            payload: JSON payload string
            secret: Secret key

        Returns:
            Hex-encoded signature
        """
        signature = hmac.new(
            secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return signature

    @staticmethod
    async def trigger_webhook(
        db: AsyncSession, webhook_id: int, event: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Trigger a specific webhook with an event payload.

        Args:
            db: Database session
            webhook_id: Webhook ID
            event: Event type
            payload: Event data

        Returns:
            Delivery result with success status and details
        """
        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        webhook = result.scalar_one_or_none()

        if not webhook:
            return {"success": False, "error": "Webhook not found"}

        if not webhook.enabled:
            return {"success": False, "error": "Webhook is disabled"}

        if event not in webhook.events:
            return {
                "success": False,
                "error": f"Webhook not subscribed to event '{event}'",
            }

        # Decrypt secret
        try:
            decrypted_secret = decrypt_value(webhook.secret)
        except Exception as e:
            logger.error(f"Failed to decrypt webhook secret for {webhook.name}: {e}")
            return {"success": False, "error": "Failed to decrypt webhook secret"}

        # Prepare payload
        webhook_payload = {
            "event": event,
            "timestamp": time.time(),
            "data": payload,
        }
        payload_json = json.dumps(webhook_payload)

        # Generate signature
        signature = WebhookService._generate_signature(payload_json, decrypted_secret)

        # Attempt delivery with retries
        last_error = None
        for attempt in range(webhook.retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        webhook.url,
                        json=webhook_payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-Webhook-Signature": signature,
                            "X-Webhook-Event": event,
                            "User-Agent": "TideWatch-Webhook/1.0",
                        },
                    )

                    if response.status_code >= 200 and response.status_code < 300:
                        # Success
                        webhook.last_triggered = datetime.now(UTC)
                        webhook.last_status = "success"
                        webhook.last_error = None
                        await db.commit()

                        return {
                            "success": True,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        }
                    else:
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"

            # If not last attempt, wait before retrying
            if attempt < webhook.retry_count:
                await asyncio.sleep(2**attempt)  # Exponential backoff

        # All attempts failed
        webhook.last_triggered = datetime.now(UTC)
        webhook.last_status = "failed"
        webhook.last_error = last_error
        await db.commit()

        logger.error(
            f"Webhook {webhook.name} delivery failed after {webhook.retry_count + 1} attempts: {last_error}"
        )
        return {
            "success": False,
            "error": last_error,
            "attempts": webhook.retry_count + 1,
        }

    @staticmethod
    async def test_webhook(db: AsyncSession, webhook_id: int) -> WebhookTestResponse:
        """Send a test payload to a webhook.

        Args:
            db: Database session
            webhook_id: Webhook ID

        Returns:
            Test result with success status and details
        """
        start_time = time.time()

        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        webhook = result.scalar_one_or_none()

        if not webhook:
            return WebhookTestResponse(
                success=False, message="Webhook not found", error="Webhook not found"
            )

        # Decrypt secret
        try:
            decrypted_secret = decrypt_value(webhook.secret)
        except Exception as e:
            logger.error(f"Failed to decrypt webhook secret: {e}")
            return WebhookTestResponse(
                success=False, message="Failed to decrypt webhook secret", error=str(e)
            )

        # Test payload
        test_payload = {
            "event": "test",
            "timestamp": time.time(),
            "data": {
                "message": "This is a test webhook from TideWatch",
                "webhook_id": webhook_id,
                "webhook_name": webhook.name,
            },
        }
        payload_json = json.dumps(test_payload)
        signature = WebhookService._generate_signature(payload_json, decrypted_secret)

        # Send test request
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook.url,
                    json=test_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                        "X-Webhook-Event": "test",
                        "User-Agent": "TideWatch-Webhook/1.0",
                    },
                )

                response_time = (time.time() - start_time) * 1000

                if response.status_code >= 200 and response.status_code < 300:
                    return WebhookTestResponse(
                        success=True,
                        status_code=response.status_code,
                        response_time_ms=response_time,
                        message=f"Test successful (HTTP {response.status_code})",
                    )
                else:
                    return WebhookTestResponse(
                        success=False,
                        status_code=response.status_code,
                        response_time_ms=response_time,
                        message=f"Test failed (HTTP {response.status_code})",
                        error=response.text[:200],
                    )

        except httpx.TimeoutException:
            return WebhookTestResponse(
                success=False,
                message="Test failed (timeout)",
                error="Request timeout after 10 seconds",
            )
        except httpx.RequestError as e:
            return WebhookTestResponse(
                success=False, message="Test failed (connection error)", error=str(e)
            )
        except Exception as e:
            logger.error(f"Webhook test failed: {e}")
            return WebhookTestResponse(
                success=False, message="Test failed (unexpected error)", error=str(e)
            )
