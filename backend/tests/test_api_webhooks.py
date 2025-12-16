"""Tests for Webhooks API (app/api/webhooks.py).

Tests webhook management endpoints:
- GET /api/v1/webhooks - List all webhooks
- POST /api/v1/webhooks - Create webhook
- GET /api/v1/webhooks/{id} - Get webhook by ID
- PUT /api/v1/webhooks/{id} - Update webhook
- DELETE /api/v1/webhooks/{id} - Delete webhook
- POST /api/v1/webhooks/{id}/test - Test webhook delivery
"""

from fastapi import status
from unittest.mock import AsyncMock, patch, MagicMock
from app.models.webhook import Webhook
from app.utils.encryption import encrypt_value


class TestListWebhooksEndpoint:
    """Test suite for GET /api/v1/webhooks endpoint."""

    async def test_list_webhooks_empty(self, authenticated_client, db):
        """Test listing webhooks when none exist."""
        response = await authenticated_client.get("/api/v1/webhooks")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_list_webhooks_multiple(self, authenticated_client, db):
        """Test listing multiple webhooks."""
        # Create webhooks
        webhooks = [
            Webhook(
                name=f"webhook-{i}",
                url=f"https://example.com/webhook{i}",
                secret=encrypt_value(f"secret-{i}"),
                events=["update_applied", "update_failed"],
                enabled=True,
            )
            for i in range(3)
        ]
        db.add_all(webhooks)
        await db.commit()

        response = await authenticated_client.get("/api/v1/webhooks")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3
        assert all("id" in w and "name" in w for w in data)

    async def test_list_webhooks_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/webhooks")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCreateWebhookEndpoint:
    """Test suite for POST /api/v1/webhooks endpoint."""

    async def test_create_webhook_valid(self, authenticated_client, db):
        """Test creating webhook with valid data."""
        webhook_data = {
            "name": "test-webhook",
            "url": "https://example.com/webhook",
            "secret": "super_secret_key_123",
            "events": ["update_applied", "update_failed"],
            "enabled": True,
            "retry_count": 3,
        }

        response = await authenticated_client.post("/api/v1/webhooks", json=webhook_data)

        if response.status_code != status.HTTP_201_CREATED:
            print(f"Response status: {response.status_code}")
            print(f"Response body: {response.json()}")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "test-webhook"
        assert data["url"] == "https://example.com/webhook"
        assert data["enabled"] is True
        assert "id" in data
        assert "created_at" in data

    async def test_create_webhook_invalid_url(self, authenticated_client):
        """Test creating webhook with invalid URL returns 422."""
        webhook_data = {
            "name": "bad-webhook",
            "url": "not-a-valid-url",
            "secret": "secret123",
            "events": ["update_applied"],
        }

        response = await authenticated_client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_create_webhook_ssrf_protection(self, authenticated_client):
        """Test SSRF protection blocks private IPs."""
        webhook_data = {
            "name": "ssrf-webhook",
            "url": "http://localhost:8080/webhook",
            "secret": "secret123",
            "events": ["update_applied"],
        }

        response = await authenticated_client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "private" in response.json()["detail"].lower() or "internal" in response.json()["detail"].lower()

    async def test_create_webhook_duplicate_name(self, authenticated_client, db):
        """Test creating webhook with duplicate name returns 409."""
        # Create first webhook
        webhook = Webhook(
            name="duplicate",
            url="https://example.com/webhook1",
            secret=encrypt_value("test_secret"),
            events=["update_applied"],
        )
        db.add(webhook)
        await db.commit()

        # Try to create webhook with same name
        webhook_data = {
            "name": "duplicate",
            "url": "https://example.com/webhook2",
            "secret": "secret123",
            "events": ["update_applied"],
        }

        response = await authenticated_client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_create_webhook_invalid_events(self, authenticated_client):
        """Test creating webhook with invalid event types returns 422."""
        webhook_data = {
            "name": "bad-events",
            "url": "https://example.com/webhook",
            "secret": "secret123",
            "events": ["invalid_event", "another_bad_event"],
        }

        response = await authenticated_client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_create_webhook_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        webhook_data = {
            "name": "test",
            "url": "https://example.com/webhook",
            "secret": "secret123",
            "events": ["update_applied"],
        }

        response = await client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetWebhookEndpoint:
    """Test suite for GET /api/v1/webhooks/{id} endpoint."""

    async def test_get_webhook_valid_id(self, authenticated_client, db):
        """Test getting webhook by valid ID."""
        webhook = Webhook(
            name="test-webhook",
            url="https://example.com/webhook",
            secret=encrypt_value("test_secret"),
            events=["update_applied"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        response = await authenticated_client.get(f"/api/v1/webhooks/{webhook.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == webhook.id
        assert data["name"] == "test-webhook"

    async def test_get_webhook_invalid_id(self, authenticated_client):
        """Test getting webhook with invalid ID returns 404."""
        response = await authenticated_client.get("/api/v1/webhooks/99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_webhook_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/webhooks/1")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateWebhookEndpoint:
    """Test suite for PUT /api/v1/webhooks/{id} endpoint."""

    async def test_update_webhook_valid(self, authenticated_client, db):
        """Test updating webhook with valid data."""
        webhook = Webhook(
            name="old-name",
            url="https://example.com/old",
            secret=encrypt_value("test_secret"),
            events=["update_applied"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        update_data = {
            "name": "new-name",
            "url": "https://example.com/new",
            "events": ["update_applied", "update_failed"],
        }

        response = await authenticated_client.put(f"/api/v1/webhooks/{webhook.id}", json=update_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "new-name"
        assert data["url"] == "https://example.com/new"
        assert len(data["events"]) == 2

    async def test_update_webhook_invalid_id(self, authenticated_client):
        """Test updating non-existent webhook returns 404."""
        update_data = {"name": "new-name"}

        response = await authenticated_client.put("/api/v1/webhooks/99999", json=update_data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_update_webhook_ssrf_protection(self, authenticated_client, db):
        """Test SSRF protection on URL update."""
        webhook = Webhook(
            name="test",
            url="https://example.com/webhook",
            secret=encrypt_value("test_secret"),
            events=["update_applied"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        update_data = {"url": "http://192.168.1.1/webhook"}

        response = await authenticated_client.put(f"/api/v1/webhooks/{webhook.id}", json=update_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_update_webhook_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        update_data = {"name": "new-name"}

        response = await client.put("/api/v1/webhooks/1", json=update_data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteWebhookEndpoint:
    """Test suite for DELETE /api/v1/webhooks/{id} endpoint."""

    async def test_delete_webhook_valid(self, authenticated_client, db):
        """Test deleting webhook."""
        webhook = Webhook(
            name="to-delete",
            url="https://example.com/webhook",
            secret=encrypt_value("test_secret"),
            events=["update_applied"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        response = await authenticated_client.delete(f"/api/v1/webhooks/{webhook.id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify webhook was deleted
        verify_response = await authenticated_client.get(f"/api/v1/webhooks/{webhook.id}")
        assert verify_response.status_code == status.HTTP_404_NOT_FOUND

    async def test_delete_webhook_invalid_id(self, authenticated_client):
        """Test deleting non-existent webhook returns 404."""
        response = await authenticated_client.delete("/api/v1/webhooks/99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_delete_webhook_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.delete("/api/v1/webhooks/1")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestTestWebhookEndpoint:
    """Test suite for POST /api/v1/webhooks/{id}/test endpoint."""

    async def test_test_webhook_success(self, authenticated_client, db):
        """Test sending test payload to webhook."""
        webhook = Webhook(
            name="test-webhook",
            url="https://httpbin.org/post",
            secret=encrypt_value("test_secret"),
            events=["test"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            response = await authenticated_client.post(f"/api/v1/webhooks/{webhook.id}/test")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "response_time_ms" in data

    async def test_test_webhook_failure(self, authenticated_client, db):
        """Test webhook test with failed delivery."""
        webhook = Webhook(
            name="fail-webhook",
            url="https://httpbin.org/status/500",
            secret=encrypt_value("test_secret"),
            events=["test"],
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)

        # Mock failing HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            response = await authenticated_client.post(f"/api/v1/webhooks/{webhook.id}/test")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is False
            assert data["status_code"] == 500

    async def test_test_webhook_invalid_id(self, authenticated_client):
        """Test testing non-existent webhook returns 404."""
        response = await authenticated_client.post("/api/v1/webhooks/99999/test")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_test_webhook_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/webhooks/1/test")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
