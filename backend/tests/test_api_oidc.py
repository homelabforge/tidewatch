"""Tests for OIDC API (app/api/oidc.py).

Tests OIDC/OAuth2 authentication endpoints:
- GET /api/v1/auth/oidc/config - Get OIDC configuration
- PUT /api/v1/auth/oidc/config - Update OIDC configuration
- POST /api/v1/auth/oidc/test - Test OIDC connection
- GET /api/v1/auth/oidc/login - Initiate OIDC flow
- GET /api/v1/auth/oidc/callback - OIDC callback
- POST /api/v1/auth/oidc/link-account - Link OIDC account
"""

import pytest
from fastapi import status
from unittest.mock import patch, AsyncMock


class TestOIDCConfigEndpoint:
    """Test suite for GET /api/v1/auth/oidc/config endpoint."""

    async def test_get_config_returns_configuration(self, authenticated_client, db):
        """Test returns OIDC configuration."""
        from app.services.settings_service import SettingsService

        # Set up OIDC configuration
        await SettingsService.set(db, "oidc_enabled", "true")
        await SettingsService.set(db, "oidc_issuer_url", "https://auth.example.com")
        await SettingsService.set(db, "oidc_client_id", "test-client-id")
        await SettingsService.set(db, "oidc_client_secret", "super-secret-key")
        await SettingsService.set(db, "oidc_provider_name", "Example Provider")

        response = await authenticated_client.get("/api/v1/auth/oidc/config")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["enabled"] is True
        assert data["issuer_url"] == "https://auth.example.com"
        assert data["client_id"] == "test-client-id"
        assert data["provider_name"] == "Example Provider"

    async def test_get_config_masks_client_secret(self, authenticated_client, db):
        """Test client secret is masked in response."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(
            db, "oidc_client_secret", "very-long-secret-key-that-should-be-masked"
        )

        response = await authenticated_client.get("/api/v1/auth/oidc/config")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Secret should be masked
        assert "very-long-secret-key-that-should-be-masked" not in data["client_secret"]
        assert "*" in data["client_secret"]

    async def test_get_config_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/auth/oidc/config")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateOIDCConfigEndpoint:
    """Test suite for PUT /api/v1/auth/oidc/config endpoint."""

    async def test_update_config_success(self, authenticated_client, db):
        """Test updates OIDC configuration successfully."""
        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.newprovider.com",
            "client_id": "new-client-id",
            "client_secret": "new-secret",
            "provider_name": "New Provider",
            "scopes": "openid profile email",
            "redirect_uri": "https://tidewatch.local/api/v1/auth/oidc/callback",
        }

        response = await authenticated_client.put(
            "/api/v1/auth/oidc/config", json=config_data
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data
        assert "updated successfully" in data["message"].lower()

    async def test_update_config_preserves_masked_secret(
        self, authenticated_client, db
    ):
        """Test preserves existing secret when masked value sent."""
        from app.services.settings_service import SettingsService

        # Set initial secret
        await SettingsService.set(db, "oidc_client_secret", "original-secret")

        # Update with masked secret
        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com",
            "client_id": "test-client",
            "client_secret": "********",  # Masked
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        response = await authenticated_client.put(
            "/api/v1/auth/oidc/config", json=config_data
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify original secret preserved
        secret = await SettingsService.get(db, "oidc_client_secret")
        assert secret == "original-secret"

    async def test_update_config_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com",
            "client_id": "test",
            "client_secret": "secret",
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        response = await client.put("/api/v1/auth/oidc/config", json=config_data)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestOIDCTestEndpoint:
    """Test suite for POST /api/v1/auth/oidc/test endpoint."""

    async def test_oidc_test_connection_success(self, authenticated_client, db):
        """Test OIDC connection test with valid configuration."""
        from app.services.settings_service import SettingsService

        # Set up valid configuration
        await SettingsService.set(db, "oidc_client_secret", "test-secret")

        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com",
            "client_id": "test-client",
            "client_secret": "********",  # Will use stored secret
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        # Mock the test_oidc_connection to return success
        with patch(
            "app.routes.oidc.oidc_service.test_oidc_connection", new_callable=AsyncMock
        ) as mock_test:
            mock_test.return_value = {
                "success": True,
                "message": "Successfully connected to OIDC provider",
                "provider_name": "Provider",
                "issuer": "https://auth.example.com",
            }

            response = await authenticated_client.post(
                "/api/v1/auth/oidc/test", json=config_data
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True

    async def test_oidc_test_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com",
            "client_id": "test",
            "client_secret": "secret",
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        response = await client.post("/api/v1/auth/oidc/test", json=config_data)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestOIDCLoginEndpoint:
    """Test suite for GET /api/v1/auth/oidc/login endpoint."""

    async def test_login_disabled_oidc_returns_400(self, client, db):
        """Test OIDC disabled returns 400."""
        from app.services.settings_service import SettingsService
        from app.models.setting import Setting

        # Ensure setup is complete
        setting = Setting(key="setup_complete", value="true")
        db.add(setting)
        await db.commit()

        # Disable OIDC
        await SettingsService.set(db, "oidc_enabled", "false")

        response = await client.get("/api/v1/auth/oidc/login")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not enabled" in response.json()["detail"].lower()

    async def test_login_setup_incomplete_returns_400(self, client, db):
        """Test setup incomplete returns 400."""
        response = await client.get("/api/v1/auth/oidc/login")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not enabled" in response.json()["detail"].lower()

    async def test_login_valid_config_redirects(self, client, db):
        """Test valid configuration returns redirect."""
        from app.services.settings_service import SettingsService
        from app.models.setting import Setting

        # Mark setup complete
        setting = Setting(key="setup_complete", value="true")
        db.add(setting)
        await db.commit()

        # Configure OIDC
        await SettingsService.set(db, "oidc_enabled", "true")
        await SettingsService.set(db, "oidc_issuer_url", "https://auth.example.com")
        await SettingsService.set(db, "oidc_client_id", "test-client-id")

        # Mock provider metadata and authorization URL creation
        with patch(
            "app.routes.oidc.oidc_service.get_provider_metadata", new_callable=AsyncMock
        ) as mock_metadata:
            with patch(
                "app.routes.oidc.oidc_service.create_authorization_url",
                new_callable=AsyncMock,
            ) as mock_auth_url:
                mock_metadata.return_value = {
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                }
                mock_auth_url.return_value = (
                    "https://auth.example.com/authorize?state=abc123",
                    "abc123",
                )

                response = await client.get(
                    "/api/v1/auth/oidc/login", follow_redirects=False
                )

                assert response.status_code == status.HTTP_302_FOUND
                assert "location" in response.headers

    @pytest.mark.skip(reason="Requires OIDC provider mocking infrastructure")
    async def test_login_generates_state_token(self, client, db):
        """Test generates state token for CSRF protection."""
        pass

    @pytest.mark.skip(reason="Requires OIDC provider mocking infrastructure")
    async def test_login_stores_state_in_database(self, client, db):
        """Test stores state in database."""
        pass


class TestOIDCCallbackEndpoint:
    """Test suite for GET /api/v1/auth/oidc/callback endpoint."""

    async def test_callback_invalid_state(self, client):
        """Test invalid state returns 400 (CSRF protection)."""
        response = await client.get(
            "/api/v1/auth/oidc/callback?code=abc123&state=invalid-state"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid or expired state" in response.json()["detail"].lower()

    @pytest.mark.skip(
        reason="Requires complete OIDC flow mocking with state/nonce validation"
    )
    async def test_callback_valid_state_code_returns_token(self, client, db):
        """Test valid state + code returns JWT token."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_callback_invalid_code(self, client, db):
        """Test invalid authorization code returns error."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_callback_links_to_admin_account(self, client, db):
        """Test links OIDC identity to admin account."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_callback_nonce_validation(self, client, db):
        """Test nonce validation."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_callback_id_token_signature_verification(self, client, db):
        """Test ID token signature verification."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_callback_pending_link_redirect(self, client, db):
        """Test redirects to link account page when password verification required."""
        pass


class TestOIDCLinkAccountEndpoint:
    """Test suite for POST /api/v1/auth/oidc/link-account endpoint."""

    @pytest.mark.skip(
        reason="Requires complete OIDC flow mocking and pending link token generation"
    )
    async def test_link_account_valid_token_password(self, client, db):
        """Test links account with valid token and password."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_link_account_invalid_token(self, client):
        """Test invalid token returns 401."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_link_account_invalid_password(self, client, db):
        """Test invalid password returns 401."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_link_account_max_attempts(self, client, db):
        """Test max password attempts locks token."""
        pass

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking")
    async def test_link_account_sets_jwt_cookie(self, client, db):
        """Test sets JWT cookie on successful link."""
        pass
