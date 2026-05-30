"""Tests for OIDC API (app/api/oidc.py).

Tests OIDC/OAuth2 authentication endpoints:
- GET /api/v1/auth/oidc/config - Get OIDC configuration
- PUT /api/v1/auth/oidc/config - Update OIDC configuration
- POST /api/v1/auth/oidc/test - Test OIDC connection
- GET /api/v1/auth/oidc/login - Initiate OIDC flow
- GET /api/v1/auth/oidc/callback - OIDC callback
- POST /api/v1/auth/oidc/link-account - Link OIDC account
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status


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
        """Test client secret returns the canonical "********" placeholder when set."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(
            db, "oidc_client_secret", "very-long-secret-key-that-should-be-masked"
        )

        response = await authenticated_client.get("/api/v1/auth/oidc/config")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Canonical wire contract per plan §5.4(3): literal "********" when stored, "" when absent.
        assert data["client_secret"] == "********"
        assert "very-long-secret-key-that-should-be-masked" not in data["client_secret"]

    async def test_get_config_empty_secret_returns_empty_string(self, authenticated_client, db):
        """When no secret is stored, GET returns empty string (not the placeholder)."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "oidc_client_secret", "")

        response = await authenticated_client.get("/api/v1/auth/oidc/config")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["client_secret"] == ""

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

        response = await authenticated_client.put("/api/v1/auth/oidc/config", json=config_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data
        assert "updated successfully" in data["message"].lower()

    async def test_update_config_preserves_masked_secret(self, authenticated_client, db):
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

        response = await authenticated_client.put("/api/v1/auth/oidc/config", json=config_data)

        assert response.status_code == status.HTTP_200_OK

        # Verify original secret preserved
        secret = await SettingsService.get(db, "oidc_client_secret")
        assert secret == "original-secret"

    async def test_update_config_round_trips_all_fields(self, authenticated_client, db):
        """Test all 11 config fields survive PUT → GET round-trip."""
        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.roundtrip.com",
            "client_id": "rt-client-id",
            "client_secret": "rt-secret",
            "provider_name": "RoundTrip Provider",
            "scopes": "openid profile",
            "redirect_uri": "https://tidewatch.local/callback",
            "username_claim": "sub",
            "email_claim": "mail",
            "link_token_expire_minutes": 10,
            "link_max_password_attempts": 5,
        }

        put_response = await authenticated_client.put("/api/v1/auth/oidc/config", json=config_data)
        assert put_response.status_code == status.HTTP_200_OK

        get_response = await authenticated_client.get("/api/v1/auth/oidc/config")
        assert get_response.status_code == status.HTTP_200_OK
        data = get_response.json()

        assert data["enabled"] is True
        assert data["issuer_url"] == "https://auth.roundtrip.com"
        assert data["client_id"] == "rt-client-id"
        assert data["provider_name"] == "RoundTrip Provider"
        assert data["scopes"] == "openid profile"
        assert data["redirect_uri"] == "https://tidewatch.local/callback"
        assert data["username_claim"] == "sub"
        assert data["email_claim"] == "mail"
        assert data["link_token_expire_minutes"] == 10
        assert data["link_max_password_attempts"] == 5
        # Canonical mask per §5.4(3).
        assert data["client_secret"] == "********"

    async def test_update_config_preserves_secret_on_empty_string(self, authenticated_client, db):
        """Empty client_secret on PUT MUST preserve the stored secret (§5.4(2))."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "oidc_client_secret", "preserved-secret")

        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com",
            "client_id": "test-client",
            "client_secret": "",  # Empty = preserve
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        response = await authenticated_client.put("/api/v1/auth/oidc/config", json=config_data)
        assert response.status_code == status.HTTP_200_OK

        secret = await SettingsService.get(db, "oidc_client_secret")
        assert secret == "preserved-secret"

    async def test_update_config_strips_issuer_trailing_slash(self, authenticated_client, db):
        """Backend MUST rstrip trailing slash from issuer_url (§5.4(1))."""
        from app.services.settings_service import SettingsService

        config_data = {
            "enabled": True,
            "issuer_url": "https://auth.example.com/auth/v1/",
            "client_id": "test-client",
            "client_secret": "secret",
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        response = await authenticated_client.put("/api/v1/auth/oidc/config", json=config_data)
        assert response.status_code == status.HTTP_200_OK

        stored = await SettingsService.get(db, "oidc_issuer_url")
        assert stored == "https://auth.example.com/auth/v1"

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
        """Test OIDC connection test returns canonical {ok, issuer, algorithms_supported}."""
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

        # Mock the verbose service response; route should map to canonical envelope.
        with patch(
            "app.routes.oidc.oidc_service.test_oidc_connection", new_callable=AsyncMock
        ) as mock_test:
            mock_test.return_value = {
                "success": True,
                "provider_reachable": True,
                "metadata_valid": True,
                "endpoints_found": True,
                "errors": [],
                "metadata": {
                    "issuer": "https://auth.example.com",
                    "id_token_signing_alg_values_supported": ["EdDSA", "RS256"],
                },
            }

            response = await authenticated_client.post("/api/v1/auth/oidc/test", json=config_data)

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["ok"] is True
            assert data["issuer"] == "https://auth.example.com"
            assert data["algorithms_supported"] == ["EdDSA", "RS256"]

    async def test_oidc_test_connection_failure_returns_canonical_error(
        self, authenticated_client, db
    ):
        """Test failure path returns canonical {ok: false, error, detail}."""
        config_data = {
            "enabled": True,
            "issuer_url": "https://bad.example.com",
            "client_id": "test-client",
            "client_secret": "",
            "provider_name": "Provider",
            "scopes": "openid",
            "redirect_uri": "",
        }

        with patch(
            "app.routes.oidc.oidc_service.test_oidc_connection", new_callable=AsyncMock
        ) as mock_test:
            mock_test.return_value = {
                "success": False,
                "provider_reachable": False,
                "metadata_valid": False,
                "endpoints_found": False,
                "errors": ["Failed to fetch provider metadata"],
                "metadata": None,
            }

            response = await authenticated_client.post("/api/v1/auth/oidc/test", json=config_data)
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["ok"] is False
            assert data["error"] == "unreachable"
            assert "fetch provider metadata" in (data.get("detail") or "")

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
        from app.models.setting import Setting
        from app.services.settings_service import SettingsService

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
        from app.models.setting import Setting
        from app.services.settings_service import SettingsService

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

                response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)

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
        response = await client.get("/api/v1/auth/oidc/callback?code=abc123&state=invalid-state")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid or expired state" in response.json()["detail"].lower()

    @pytest.mark.skip(reason="Requires complete OIDC flow mocking with state/nonce validation")
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

    @staticmethod
    def _patch_callback_boundary(*, sub: str, userinfo=None):
        """Patch the OIDC network boundary so link_oidc_to_admin runs for real.

        Returns a list of context managers (state, metadata, token exchange,
        id-token verification, userinfo) ready to enter via ExitStack/with.
        """
        return [
            patch(
                "app.routes.oidc.oidc_service.validate_and_consume_state",
                new_callable=AsyncMock,
                return_value={
                    "redirect_uri": "https://tidewatch.local/api/v1/auth/oidc/callback",
                    "nonce": "nonce-value",
                    "code_verifier": "verifier-value",
                    "created_at": None,
                },
            ),
            patch(
                "app.routes.oidc.oidc_service.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "jwks_uri": "https://auth.example.com/jwks",
                },
            ),
            patch(
                "app.routes.oidc.oidc_service.exchange_code_for_tokens",
                new_callable=AsyncMock,
                return_value={"id_token": "id-token", "access_token": "access-token"},
            ),
            patch(
                "app.routes.oidc.oidc_service.verify_id_token",
                new_callable=AsyncMock,
                return_value={"sub": sub, "preferred_username": "admin"},
            ),
            patch(
                "app.routes.oidc.oidc_service.get_userinfo",
                new_callable=AsyncMock,
                return_value=userinfo,
            ),
        ]

    @staticmethod
    async def _seed_admin(db, *, oidc_subject=None, auth_method="local"):
        from app.models.user import User
        from app.services.auth import hash_password
        from app.services.settings_service import SettingsService

        db.add(
            User(
                username="admin",
                email="admin@example.com",
                password_hash=hash_password("Password123!"),
                auth_method=auth_method,
                oidc_subject=oidc_subject,
            )
        )
        await SettingsService.set(db, "oidc_enabled", "true")
        await SettingsService.set(db, "oidc_issuer_url", "https://auth.example.com")
        await SettingsService.set(db, "oidc_client_id", "client-id")
        await SettingsService.set(db, "oidc_provider_name", "Example")
        # The config-save path (PUT /oidc/config) always writes these; mirror it
        # so the pending-link flow has valid integers to parse.
        await SettingsService.set(db, "oidc_link_token_expire_minutes", "5")
        await SettingsService.set(db, "oidc_link_max_password_attempts", "3")
        await db.commit()

    async def test_callback_pending_link_redirect(self, client, db):
        """First OIDC login for a password-protected admin redirects to the
        password-gated link page and binds nothing."""
        from contextlib import ExitStack

        from sqlalchemy import select

        from app.models.oidc_pending_link import OIDCPendingLink
        from app.services.auth import _get_admin_user

        await self._seed_admin(db, oidc_subject=None)

        with ExitStack() as stack:
            for cm in self._patch_callback_boundary(sub="oidc-user-1"):
                stack.enter_context(cm)
            response = await client.get(
                "/api/v1/auth/oidc/callback?code=abc&state=xyz", follow_redirects=False
            )

        assert response.status_code == status.HTTP_302_FOUND
        assert "/auth/link-account?token=" in response.headers["location"]

        # Nothing bound; a pending-link row was created.
        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject is None
        rows = (await db.execute(select(OIDCPendingLink))).scalars().all()
        assert len(rows) == 1

    async def test_callback_relogin_matching_sub_sets_cookie(self, client, db):
        """Re-login from the bound subject issues a JWT cookie and lands on the app."""
        from contextlib import ExitStack

        await self._seed_admin(db, oidc_subject="oidc-user-1", auth_method="oidc")

        with ExitStack() as stack:
            for cm in self._patch_callback_boundary(sub="oidc-user-1"):
                stack.enter_context(cm)
            response = await client.get(
                "/api/v1/auth/oidc/callback?code=abc&state=xyz", follow_redirects=False
            )

        assert response.status_code == status.HTTP_302_FOUND
        assert "/auth/link-account" not in response.headers["location"]
        set_cookie = response.headers.get("set-cookie", "")
        assert "tidewatch_token=" in set_cookie

    async def test_callback_mismatched_sub_returns_403(self, client, db):
        """A different subject at the same provider is rejected with 403."""
        from contextlib import ExitStack

        from app.services.auth import _get_admin_user

        await self._seed_admin(db, oidc_subject="oidc-user-1", auth_method="oidc")

        with ExitStack() as stack:
            for cm in self._patch_callback_boundary(sub="evil-user-2"):
                stack.enter_context(cm)
            response = await client.get(
                "/api/v1/auth/oidc/callback?code=abc&state=xyz", follow_redirects=False
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        # Binding unchanged.
        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject == "oidc-user-1"


class TestOIDCLinkAccountEndpoint:
    """Test suite for POST /api/v1/auth/oidc/link-account endpoint."""

    _SUCCESS_RESULT = {
        "success": True,
        "claims": {"sub": "oidc-user-123", "preferred_username": "admin"},
        "userinfo": {"email": "admin@example.com"},
        "provider_name": "Test Provider",
        "error": None,
    }

    _ADMIN_PROFILE = {
        "username": "admin",
        "full_name": "Admin User",
    }

    async def test_link_account_valid_token_password(self, client, db):
        """Test links account with valid token and password, persists OIDC link."""
        with (
            patch(
                "app.routes.oidc.oidc_service.verify_pending_link",
                new_callable=AsyncMock,
                return_value=self._SUCCESS_RESULT,
            ) as mock_verify,
            patch(
                "app.routes.oidc.oidc_service.link_oidc_to_admin",
                new_callable=AsyncMock,
            ) as mock_link,
            patch(
                "app.services.auth.get_admin_profile",
                new_callable=AsyncMock,
                return_value=self._ADMIN_PROFILE,
            ),
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "test-token", "password": "test-password"},
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["token_type"] == "bearer"
            assert "access_token" in data

            # Verify the service was called correctly
            mock_verify.assert_called_once_with(db, "test-token", "test-password")

            # Verify link_oidc_to_admin was called to persist the link, with the
            # password-verified flag set (the link-account flow already proved
            # the password).
            mock_link.assert_called_once_with(
                db,
                self._SUCCESS_RESULT["claims"],
                self._SUCCESS_RESULT["userinfo"],
                {"provider_name": "Test Provider"},
                password_verified=True,
            )

    async def test_link_account_accepts_json_body(self, client, db):
        """The endpoint accepts the real frontend JSON body shape {token, password}.

        Guards the contract fix (#1 Change E): the previous query-param signature
        would 422 against this body.
        """
        with (
            patch(
                "app.routes.oidc.oidc_service.verify_pending_link",
                new_callable=AsyncMock,
                return_value=self._SUCCESS_RESULT,
            ),
            patch(
                "app.routes.oidc.oidc_service.link_oidc_to_admin",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.auth.get_admin_profile",
                new_callable=AsyncMock,
                return_value=self._ADMIN_PROFILE,
            ),
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "test-token", "password": "test-password"},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.status_code != status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_link_account_invalid_token(self, client):
        """Test invalid token returns 401."""
        with patch(
            "app.routes.oidc.oidc_service.verify_pending_link",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "claims": None,
                "userinfo": None,
                "provider_name": None,
                "error": "Invalid or expired token",
            },
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "bad-token", "password": "test-password"},
            )

            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid or expired token" in response.json()["detail"]

    async def test_link_account_invalid_password(self, client):
        """Test invalid password returns 401."""
        with patch(
            "app.routes.oidc.oidc_service.verify_pending_link",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "claims": None,
                "userinfo": None,
                "provider_name": None,
                "error": "Invalid password",
            },
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "test-token", "password": "wrong-password"},
            )

            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid password" in response.json()["detail"]

    async def test_link_account_max_attempts(self, client):
        """Test max password attempts returns 401."""
        with patch(
            "app.routes.oidc.oidc_service.verify_pending_link",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "claims": None,
                "userinfo": None,
                "provider_name": None,
                "error": "Maximum password attempts exceeded",
            },
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "test-token", "password": "test-password"},
            )

            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Maximum password attempts exceeded" in response.json()["detail"]

    async def test_link_account_sets_jwt_cookie(self, client, db):
        """Test sets httponly JWT cookie on successful link."""
        with (
            patch(
                "app.routes.oidc.oidc_service.verify_pending_link",
                new_callable=AsyncMock,
                return_value=self._SUCCESS_RESULT,
            ),
            patch(
                "app.routes.oidc.oidc_service.link_oidc_to_admin",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.auth.get_admin_profile",
                new_callable=AsyncMock,
                return_value=self._ADMIN_PROFILE,
            ),
        ):
            response = await client.post(
                "/api/v1/auth/oidc/link-account",
                json={"token": "test-token", "password": "test-password"},
            )

            assert response.status_code == status.HTTP_200_OK

            # Check Set-Cookie header for httponly JWT
            set_cookie = response.headers.get("set-cookie", "")
            assert "tidewatch_token=" in set_cookie
            assert "httponly" in set_cookie.lower()


class TestExchangeCodeForTokensLogging:
    """Token-exchange error logging must not leak the client_secret (N4)."""

    _SECRET = "super-secret-client-value-1234567890"
    _CONFIG = {"client_id": "client", "client_secret": _SECRET}
    _METADATA = {"token_endpoint": "https://auth.example.com/token"}

    def _echoing_response(self, status_code):
        import httpx

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        # A reflective provider echoes the posted secret + a long body.
        resp.text = f"error: rejected client_secret={self._SECRET} " + ("x" * 600)
        return resp

    async def test_non_200_branch_does_not_log_secret(self, caplog):
        from app.services import oidc as oidc_service

        resp = self._echoing_response(400)
        # raise_for_status raises so only the non-200 log fires, then the
        # HTTPStatusError branch fires — both must redact.
        import httpx

        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=resp)

        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.validate_oidc_url"),
            caplog.at_level(logging.ERROR, logger="app.services.oidc"),
        ):
            result = await oidc_service.exchange_code_for_tokens(
                "code", self._CONFIG, self._METADATA, "https://rp.example.com/cb"
            )

        assert result is None
        assert self._SECRET not in caplog.text
        assert "<redacted>" in caplog.text
        # Bounded: the 600-char filler is truncated to the snippet cap.
        assert ("x" * 400) not in caplog.text
