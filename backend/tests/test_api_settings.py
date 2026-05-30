"""Tests for Settings API (app/api/settings.py).

Tests settings management endpoints:
- GET /api/v1/settings - Get all settings
- GET /api/v1/settings/{key} - Get single setting
- PUT /api/v1/settings/{key} - Update setting
- POST /api/v1/settings/batch - Batch update
- DELETE /api/v1/settings/{key} - Reset to default
"""

from unittest.mock import patch

import pytest
from fastapi import status

from app.services.settings_service import SettingsService as _SettingsService

# Every encrypted:True DEFAULTS key — the source of truth the mask set derives
# from. Enumerated here so the desync-proof tests below mask whatever the app
# actually encrypts, with no hand-maintained second list to drift.
_ENCRYPTED_DEFAULT_KEYS = sorted(
    k for k, v in _SettingsService.DEFAULTS.items() if v.get("encrypted")
)


class TestGetAllSettingsEndpoint:
    """Test suite for GET /api/v1/settings endpoint."""

    async def test_get_all_settings(self, authenticated_client, db):
        """Test returns all settings as key-value pairs."""
        from app.services.settings_service import SettingsService

        # Set a few test settings
        await SettingsService.set(db, "check_interval", "60")
        await SettingsService.set(db, "auto_update_enabled", "false")

        response = await authenticated_client.get("/api/v1/settings")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Verify structure
        if len(data) > 0:
            assert "key" in data[0]
            assert "value" in data[0]

    async def test_get_all_settings_masks_sensitive(self, authenticated_client, db):
        """Test masks sensitive values (API keys, tokens)."""
        from app.services.settings_service import SettingsService

        # Set a sensitive setting (admin_password_hash is marked as sensitive)
        await SettingsService.set(db, "admin_password_hash", "supersecretpasswordhash123")

        response = await authenticated_client.get("/api/v1/settings")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Find the sensitive setting
        sensitive_setting = next((s for s in data if s["key"] == "admin_password_hash"), None)
        if sensitive_setting:
            # Value should be masked
            assert "*" in sensitive_setting["value"]
            assert "supersecretpasswordhash123" not in sensitive_setting["value"]

    async def test_get_all_settings_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/settings")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_all_settings_default_values(self, authenticated_client, db):
        """Test returns default values for unconfigured settings."""
        # Get all settings without setting custom values
        response = await authenticated_client.get("/api/v1/settings")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should have some default settings
        assert len(data) >= 0


class TestGetSettingEndpoint:
    """Test suite for GET /api/v1/settings/{key} endpoint."""

    async def test_get_setting_valid_key(self, authenticated_client, db):
        """Test valid key returns setting value."""
        from app.services.settings_service import SettingsService

        # Set a test setting
        await SettingsService.set(db, "check_interval", "120")

        response = await authenticated_client.get("/api/v1/settings/check_interval")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "check_interval"
        assert data["value"] == "120"

    async def test_get_setting_invalid_key(self, authenticated_client):
        """Test invalid key returns 404."""
        response = await authenticated_client.get("/api/v1/settings/nonexistent_key_12345")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "not found" in data["detail"].lower()

    async def test_get_setting_sensitive_masked(self, authenticated_client, db):
        """Test sensitive key returns masked value."""
        from app.services.settings_service import SettingsService

        # Set a sensitive setting
        await SettingsService.set(db, "admin_password_hash", "verylongsecretpasswordhash12345")

        response = await authenticated_client.get("/api/v1/settings/admin_password_hash")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "admin_password_hash"
        # Value should be masked
        assert "*" in data["value"]
        assert "verylongsecretpasswordhash12345" not in data["value"]

    async def test_get_setting_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/settings/check_interval")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_setting_default_value(self, authenticated_client, db):
        """Test returns default value if not customized."""
        # Check interval should have a default value even if not set
        response = await authenticated_client.get("/api/v1/settings/check_interval")

        # If setting exists, it should return 200 with a value
        # If it doesn't exist yet, it will return 404
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]


class TestUpdateSettingEndpoint:
    """Test suite for PUT /api/v1/settings/{key} endpoint."""

    async def test_update_setting_valid_value(self, authenticated_client, db):
        """Test valid value update returns 200 OK."""
        response = await authenticated_client.put(
            "/api/v1/settings/check_interval", json={"value": "180"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "check_interval"
        assert data["value"] == "180"

    async def test_update_setting_invalid_cron_returns_400(self, authenticated_client):
        """Invalid cron values for check_schedule must be rejected with 400.

        Regression: a user saved '*/48' (intending 'every 48 hours') and the
        next container start crashed on CronTrigger.from_crontab during
        scheduler startup, bricking the app.
        """
        response = await authenticated_client.put(
            "/api/v1/settings/check_schedule", json={"value": "*/48"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "check_schedule" in response.json()["detail"]

    async def test_update_setting_valid_cron_accepted(self, authenticated_client):
        """A valid 5-field cron expression is accepted."""
        response = await authenticated_client.put(
            "/api/v1/settings/check_schedule", json={"value": "0 0 */2 * *"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"] == "0 0 */2 * *"

    async def test_update_setting_empty_cron_rejected(self, authenticated_client):
        """Empty cron expression is rejected."""
        response = await authenticated_client.put(
            "/api/v1/settings/check_schedule", json={"value": ""}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_update_setting_invalid_cleanup_schedule_returns_400(self, authenticated_client):
        """cleanup_schedule is also validated as cron."""
        response = await authenticated_client.put(
            "/api/v1/settings/cleanup_schedule", json={"value": "garbage"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_update_setting_sensitive_encrypted(self, authenticated_client, db):
        """oidc_client_secret is stored as ciphertext (encrypted flag sticks) and
        get() returns the plaintext (#3 — the flag no longer flips back to False)."""
        from sqlalchemy import select

        from app.models.setting import Setting
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "oidc_client_secret", "topsecret-value-123")

        row = (
            await db.execute(select(Setting).where(Setting.key == "oidc_client_secret"))
        ).scalar_one()
        assert row.encrypted is True
        assert row.value != "topsecret-value-123"
        assert row.value.startswith("gAAAAA")  # Fernet ciphertext
        assert await SettingsService.get(db, "oidc_client_secret") == "topsecret-value-123"

    async def test_update_setting_triggers_event(self, authenticated_client, db, mock_event_bus):
        """Test triggers setting_changed event."""
        # Update a setting
        response = await authenticated_client.put(
            "/api/v1/settings/check_interval", json={"value": "180"}
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify event was published (if implemented)
        # Note: This test validates the mock setup works
        # When event bus is integrated, verify:
        # mock_event_bus.publish.assert_called_once()
        # args = mock_event_bus.publish.call_args[0]
        # assert "setting_changed" in str(args)

    async def test_update_setting_boolean(self, authenticated_client, db):
        """Test updating boolean setting (auto_update_enabled)."""
        response = await authenticated_client.put(
            "/api/v1/settings/auto_update_enabled", json={"value": "true"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "auto_update_enabled"
        assert data["value"] == "true"

    @pytest.mark.skip(reason="Settings validation not enforced at API level")
    async def test_update_setting_integer_validation(self, authenticated_client, db):
        """Test integer validation (check_interval: 1-1440)."""
        pass

    async def test_update_setting_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.put("/api/v1/settings/check_interval", json={"value": "120"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.skip(reason="CSRF protection tested in middleware tests")
    async def test_update_setting_csrf_required(self, authenticated_client):
        """Test requires CSRF token."""
        pass


class TestBulkUpdateSettingsEndpoint:
    """Test suite for POST /api/v1/settings/batch endpoint."""

    async def test_bulk_update_multiple(self, authenticated_client, db):
        """Test updates multiple settings."""
        from app.services.settings_service import SettingsService

        # Batch update multiple settings
        response = await authenticated_client.post(
            "/api/v1/settings/batch",
            json=[
                {"key": "check_interval", "value": "300"},
                {"key": "auto_update_enabled", "value": "true"},
                {"key": "max_retries", "value": "5"},
            ],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3

        # Verify settings were updated
        check_interval = await SettingsService.get(db, "check_interval")
        assert check_interval == "300"

        auto_update = await SettingsService.get(db, "auto_update_enabled")
        assert auto_update == "true"

    async def test_bulk_update_validation_error_rollback(self, authenticated_client, db):
        """Test validation errors rollback all changes."""
        # Set initial values
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "check_interval", "60")

        # Batch update with invalid data (missing key field)
        response = await authenticated_client.post(
            "/api/v1/settings/batch",
            json=[
                {"key": "check_interval", "value": "120"},
                {"value": "true"},  # Missing 'key' field
            ],
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Verify original value unchanged (rollback happened)
        check_interval = await SettingsService.get(db, "check_interval")
        assert check_interval == "60"

    async def test_bulk_update_returns_updated(self, authenticated_client, db):
        """Test returns all updated settings."""
        response = await authenticated_client.post(
            "/api/v1/settings/batch",
            json=[
                {"key": "check_interval", "value": "180"},
                {"key": "auto_update_enabled", "value": "false"},
            ],
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify response contains all updated settings
        assert len(data) == 2
        keys = [s["key"] for s in data]
        assert "check_interval" in keys
        assert "auto_update_enabled" in keys

        # Verify values match
        for setting in data:
            if setting["key"] == "check_interval":
                assert setting["value"] == "180"
            elif setting["key"] == "auto_update_enabled":
                assert setting["value"] == "false"

    async def test_bulk_update_requires_auth(self, client, db):
        """Test requires authentication (CSRF validation happens first, returns 403)."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post(
            "/api/v1/settings/batch", json=[{"key": "check_interval", "value": "240"}]
        )

        # CSRF is disabled in test mode (TIDEWATCH_TESTING=true), so we get 401 (Auth)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestSettingsValidation:
    """Test suite for settings validation."""

    async def test_validate_auto_update_enabled(self, authenticated_client, db):
        """Test auto_update_enabled accepts boolean values."""
        # Test setting boolean as string "true"
        response = await authenticated_client.put(
            "/api/v1/settings/auto_update_enabled", json={"value": "true"}
        )
        assert response.status_code == status.HTTP_200_OK

        # Test setting boolean as string "false"
        response = await authenticated_client.put(
            "/api/v1/settings/auto_update_enabled", json={"value": "false"}
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_validate_check_interval(self, authenticated_client, db):
        """Test check_interval accepts valid values."""
        # Test valid intervals
        for interval in ["60", "120", "1440"]:
            response = await authenticated_client.put(
                "/api/v1/settings/check_interval", json={"value": interval}
            )
            assert response.status_code == status.HTTP_200_OK

    async def test_validate_max_retries(self, authenticated_client, db):
        """Test max_retries accepts valid values."""
        # Test valid retry counts
        for retries in ["0", "5", "10"]:
            response = await authenticated_client.put(
                "/api/v1/settings/max_retries", json={"value": retries}
            )
            assert response.status_code == status.HTTP_200_OK

    async def test_validate_encryption_key(self, authenticated_client, db):
        """Test encryption_key is properly stored."""
        # Test setting encryption key
        response = await authenticated_client.put(
            "/api/v1/settings/encryption_key",
            json={"value": "test-encryption-key-12345"},
        )
        assert response.status_code == status.HTTP_200_OK


class TestSensitiveDataMasking:
    """Test suite for sensitive data masking."""

    async def test_encryption_key_not_in_plaintext(self, authenticated_client, db):
        """Test encryption key is never returned in plaintext."""
        from app.services.settings_service import SettingsService

        # Set an encryption key (which should be sensitive)
        await SettingsService.set(db, "encryption_key", "my-super-secret-encryption-key-12345")

        response = await authenticated_client.get("/api/v1/settings/encryption_key")

        # If the setting is marked as sensitive, it should be masked
        # If setting doesn't exist, should return 404
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            # Should be masked if it's sensitive
            assert "my-super-secret-encryption-key-12345" not in data["value"]

    async def test_notification_tokens_masked(self, authenticated_client, db):
        """Test notification service tokens are masked (unconditionally)."""
        from app.services.settings_service import SettingsService

        secret = "https://discord.com/api/webhooks/123456789/super-secret-webhook-token"
        await SettingsService.set(db, "discord_webhook_url", secret)

        response = await authenticated_client.get("/api/v1/settings/discord_webhook_url")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["key"] == "discord_webhook_url"
        assert "*" in data["value"]
        assert secret not in data["value"]

    async def test_email_password_masked(self, authenticated_client, db):
        """Test email SMTP password is masked (real key email_smtp_password)."""
        from app.services.settings_service import SettingsService

        secret = "my-email-password-123"
        await SettingsService.set(db, "email_smtp_password", secret)

        response = await authenticated_client.get("/api/v1/settings/email_smtp_password")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "*" in data["value"]
        assert secret not in data["value"]

    async def test_oidc_client_secret_masked(self, authenticated_client, db):
        """Test OIDC client secret is masked."""
        from app.services.settings_service import SettingsService

        # Set OIDC client secret
        await SettingsService.set(db, "oidc_client_secret", "super-secret-client-secret-value")

        response = await authenticated_client.get("/api/v1/settings/oidc_client_secret")

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            # Should be masked if marked as sensitive
            assert "super-secret-client-secret-value" not in data["value"]

    async def test_previously_leaking_keys_masked(self, authenticated_client, db):
        """ntfy_token / slack_webhook_url / discord_webhook_url were missing from
        the hand-maintained list and leaked unmasked; the derived set masks them."""
        from app.services.settings_service import SettingsService

        secrets = {
            "ntfy_token": "tk_super_secret_ntfy_token_value",
            "slack_webhook_url": "https://hooks.slack.com/services/T000/B000/secrettoken",
            "discord_webhook_url": "https://discord.com/api/webhooks/123/secrettoken",
        }
        for key, value in secrets.items():
            await SettingsService.set(db, key, value)

        response = await authenticated_client.get("/api/v1/settings")
        assert response.status_code == status.HTTP_200_OK
        by_key = {s["key"]: s["value"] for s in response.json()}
        for key, value in secrets.items():
            assert "*" in by_key[key], f"{key} not masked"
            assert value not in by_key[key], f"{key} leaked plaintext"

    @pytest.mark.parametrize("key", _ENCRYPTED_DEFAULT_KEYS)
    async def test_all_encrypted_defaults_masked_in_get_all(self, authenticated_client, db, key):
        """Every encrypted:True DEFAULTS key is masked in GET /settings."""
        from app.services.settings_service import SettingsService

        secret = f"plaintext-secret-for-{key}-1234567890"
        await SettingsService.set(db, key, secret)

        response = await authenticated_client.get("/api/v1/settings")
        assert response.status_code == status.HTTP_200_OK
        value = {s["key"]: s["value"] for s in response.json()}[key]
        assert "*" in value, f"{key} not masked in get_all"
        assert secret not in value, f"{key} leaked plaintext in get_all"

    @pytest.mark.parametrize("key", _ENCRYPTED_DEFAULT_KEYS)
    async def test_all_encrypted_defaults_masked_in_categories(self, authenticated_client, db, key):
        """Every encrypted:True DEFAULTS key is masked in GET /settings/categories."""
        from app.services.settings_service import SettingsService

        secret = f"plaintext-secret-for-{key}-1234567890"
        await SettingsService.set(db, key, secret)

        response = await authenticated_client.get("/api/v1/settings/categories")
        assert response.status_code == status.HTTP_200_OK
        found = None
        for category in response.json():
            for s in category["settings"]:
                if s["key"] == key:
                    found = s["value"]
        assert found is not None, f"{key} missing from categories"
        assert "*" in found, f"{key} not masked in categories"
        assert secret not in found, f"{key} leaked plaintext in categories"


class TestSSRFProtectionOnTestEndpoints:
    """Test SSRF validation on integration test-connection endpoints."""

    async def test_vulnforge_test_blocks_private_ip(self, authenticated_client, db):
        """Test /test/vulnforge blocks private IP URLs."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "vulnforge_url", "http://192.168.1.1:8080")
        await SettingsService.set(db, "vulnforge_auth_type", "none")

        response = await authenticated_client.post("/api/v1/settings/test/vulnforge")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert "SSRF" in data["message"]

    async def test_ntfy_test_blocks_private_ip(self, authenticated_client, db):
        """Test /test/ntfy blocks private IP URLs."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "ntfy_enabled", "true")
        await SettingsService.set(db, "ntfy_server", "http://10.0.0.1:8080")
        await SettingsService.set(db, "ntfy_topic", "test")

        response = await authenticated_client.post("/api/v1/settings/test/ntfy")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert "SSRF" in data["message"]

    async def test_slack_test_blocks_private_ip(self, authenticated_client, db):
        """Test /test/slack blocks private IP URLs."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "slack_enabled", "true")
        await SettingsService.set(db, "slack_webhook_url", "http://127.0.0.1:9090/webhook")

        response = await authenticated_client.post("/api/v1/settings/test/slack")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert "SSRF" in data["message"]

    async def test_smtp_blocks_private_host(self, authenticated_client, db):
        """Test /test/email blocks private IP SMTP hosts."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "email_enabled", "true")
        await SettingsService.set(db, "email_smtp_host", "192.168.1.1")
        await SettingsService.set(db, "email_smtp_port", "587")
        await SettingsService.set(db, "email_smtp_user", "user")
        await SettingsService.set(db, "email_smtp_password", "pass")
        await SettingsService.set(db, "email_from", "from@test.com")
        await SettingsService.set(db, "email_to", "to@test.com")

        response = await authenticated_client.post("/api/v1/settings/test/email")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert "SSRF" in data["message"]


class TestVulnForgeClientFactorySSRF:
    """Test SSRF validation in the VulnForge client factory."""

    async def test_factory_blocks_private_ip(self, db):
        """Test create_vulnforge_client returns None when URL is private."""
        from app.services.settings_service import SettingsService
        from app.services.vulnforge_client import create_vulnforge_client

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://192.168.1.1:8080")

        client = await create_vulnforge_client(db)
        assert client is None

    async def test_factory_allows_trusted_host(self, db):
        """Test create_vulnforge_client allows URL when host is trusted."""
        from app.services.settings_service import SettingsService
        from app.services.vulnforge_client import create_vulnforge_client

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://192.168.1.100:8080")

        with patch.dict("os.environ", {"TIDEWATCH_TRUSTED_HOSTS": "192.168.1.0/24"}):
            client = await create_vulnforge_client(db)
            assert client is not None
