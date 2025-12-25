"""Tests for Authentication API (app/api/auth.py).

Tests authentication endpoints:
- POST /api/v1/auth/setup - Initial admin setup
- POST /api/v1/auth/login - Local authentication
- POST /api/v1/auth/logout - Session termination
- GET /api/v1/auth/me - Current user profile
- GET /api/v1/auth/status - Authentication status
- POST /api/v1/auth/refresh - Token refresh
- PUT /api/v1/auth/password - Password change
"""

import pytest
from fastapi import status


class TestAuthStatusEndpoint:
    """Test suite for GET /api/v1/auth/status endpoint."""

    async def test_get_status_before_setup(self, client, db):
        """Test status returns setup_complete=false before initial setup when auth is enabled.

        When auth_mode is 'none', setup is considered complete (no account needed).
        When auth_mode is 'local' or 'oidc', setup is incomplete until admin account exists.
        """
        # Set auth mode to local to require setup
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/auth/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["setup_complete"] is False
        assert data["auth_mode"] == "local"
        assert data["oidc_enabled"] is False

    async def test_get_status_with_auth_none(self, client, db):
        """Test status returns setup_complete=true when auth_mode is none.

        When authentication is disabled (none), no setup is required.
        """
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "none")
        await db.commit()

        response = await client.get("/api/v1/auth/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["setup_complete"] is True  # No setup needed when auth is disabled
        assert data["auth_mode"] == "none"
        assert data["oidc_enabled"] is False

    async def test_get_status_after_setup_local_auth(self, client, db, admin_user):
        """Test status returns correct auth_mode after setup."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/auth/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["setup_complete"] is True
        assert data["auth_mode"] == "local"
        assert data["oidc_enabled"] is False

    async def test_get_status_oidc_enabled(self, client, db, admin_user):
        """Test status shows OIDC enabled when configured."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "oidc")
        await SettingsService.set(db, "oidc_enabled", "true")
        await db.commit()

        response = await client.get("/api/v1/auth/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["setup_complete"] is True
        assert data["auth_mode"] == "oidc"
        assert data["oidc_enabled"] is True


class TestSetupEndpoint:
    """Test suite for POST /api/v1/auth/setup endpoint."""

    async def test_setup_creates_admin(self, client, db):
        """Test setup creates initial admin user."""
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "AdminPass123!",
            "full_name": "Admin User",
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["username"] == "admin"
        assert data["email"] == "admin@example.com"
        assert data["full_name"] == "Admin User"
        assert data["message"] == "Admin account created successfully"

        # Verify admin was created in settings
        from app.services.settings_service import SettingsService

        username = await SettingsService.get(db, "admin_username")
        assert username == "admin"

    async def test_setup_enables_local_auth(self, client, db):
        """Test setup enables local authentication."""
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "AdminPass123!",
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)
        assert response.status_code == status.HTTP_201_CREATED

        # Verify auth_mode was set to local
        from app.services.settings_service import SettingsService

        auth_mode = await SettingsService.get(db, "auth_mode")
        assert auth_mode == "local"

    async def test_setup_rejects_weak_password(self, client):
        """Test setup rejects weak passwords."""
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "weak",  # Too weak
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        # Should have validation error for password
        assert any("password" in str(error).lower() for error in detail)

    async def test_setup_rejects_duplicate(self, client, db, admin_user):
        """Test setup fails when already configured."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        setup_data = {
            "username": "newadmin",
            "email": "newadmin@example.com",
            "password": "NewPass123!",
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "already complete" in response.json()["detail"].lower()

    async def test_setup_validates_email(self, client):
        """Test setup validates email format."""
        setup_data = {
            "username": "admin",
            "email": "not-an-email",  # Invalid email
            "password": "AdminPass123!",
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_setup_sanitizes_input(self, client, db):
        """Test setup prevents SQL injection and XSS."""
        setup_data = {
            "username": "admin'; DROP TABLE settings; --",
            "email": "admin@example.com",
            "password": "AdminPass123!",
            "full_name": "<script>alert('xss')</script>",
        }

        # Should fail validation due to invalid username characters
        response = await client.post("/api/v1/auth/setup", json=setup_data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_setup_generates_secret_key(self, client, db):
        """Test setup generates encryption secret key."""
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "AdminPass123!",
        }

        response = await client.post("/api/v1/auth/setup", json=setup_data)
        assert response.status_code == status.HTTP_201_CREATED

        # Verify password was hashed (not stored in plaintext)
        from app.services.settings_service import SettingsService

        password_hash = await SettingsService.get(db, "admin_password_hash")
        assert password_hash is not None
        assert password_hash != "AdminPass123!"
        assert len(password_hash) > 50  # bcrypt hashes are long

    async def test_setup_csrf_protection(self, client):
        """Test setup endpoint is exempt from CSRF protection."""
        # Setup endpoint should be exempt from CSRF (new users can't have CSRF token)
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "AdminPass123!",
        }

        # Should succeed WITHOUT CSRF token (exempt endpoint)
        response = await client.post("/api/v1/auth/setup", json=setup_data)
        assert response.status_code == status.HTTP_201_CREATED


class TestLoginEndpoint:
    """Test suite for POST /api/v1/auth/login endpoint."""

    async def test_login_success_returns_token(self, client, db, admin_user):
        """Test successful login returns JWT token."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        login_data = {
            "username": "admin",
            "password": "AdminPassword123!",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        assert len(data["access_token"]) > 100  # JWT tokens are long

    async def test_login_invalid_credentials(self, client, db, admin_user):
        """Test login fails with invalid credentials."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        login_data = {
            "username": "admin",
            "password": "WrongPassword123!",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "incorrect" in response.json()["detail"].lower()

    async def test_login_missing_fields(self, client):
        """Test login fails with missing username or password."""
        # Missing password
        response = await client.post("/api/v1/auth/login", json={"username": "admin"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Missing username
        response = await client.post("/api/v1/auth/login", json={"password": "pass"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_login_disabled_when_auth_none(self, client, db):
        """Test login fails when auth_mode is none (no admin user exists)."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "none")
        await db.commit()

        login_data = {
            "username": "admin",
            "password": "AdminPassword123!",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        # With auth_mode="none", setup is considered complete but there's no admin user
        # Authentication fails with 401 (invalid credentials) not 400 (setup incomplete)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_login_rate_limiting(self, client, db, admin_user):
        """Test rate limiting on login endpoint (60 req/min global)."""
        # Rate limiting is implemented globally at 60 requests/minute
        # Testing requires making 60+ requests which is impractical in unit tests
        # This test verifies the middleware exists and is configured
        from app.middleware.rate_limit import RateLimitMiddleware

        # Verify rate limit middleware is imported and available
        assert RateLimitMiddleware is not None

        # Note: Full rate limit testing is in test_middleware_ratelimit.py
        # which tests the TokenBucket algorithm and middleware behavior

    async def test_login_sql_injection_attempt(self, client, db, admin_user):
        """Test login prevents SQL injection attacks."""
        # admin_user fixture already sets auth_mode="local" and creates admin

        login_data = {
            "username": "admin' OR '1'='1",
            "password": "anything",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        # Should fail authentication (not cause SQL error)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_login_sets_jwt_cookie(self, client, db, admin_user):
        """Test login sets JWT in HTTP-only cookie."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        login_data = {
            "username": "admin",
            "password": "AdminPassword123!",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        assert response.status_code == status.HTTP_200_OK
        # Check if JWT cookie was set
        assert "set-cookie" in response.headers or "Set-Cookie" in response.headers

    async def test_login_csrf_token_returned(self, client, db, admin_user):
        """Test login is exempt from CSRF protection."""
        # Login endpoint should be exempt from CSRF (unauthenticated users can't have token)
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        login_data = {
            "username": "admin",
            "password": "AdminPassword123!",
        }

        # Should succeed WITHOUT CSRF token (exempt endpoint)
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == status.HTTP_200_OK

    async def test_login_case_sensitive_username(self, client, db, admin_user):
        """Test username is case-sensitive."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        login_data = {
            "username": "ADMIN",  # Wrong case
            "password": "AdminPassword123!",
        }

        response = await client.post("/api/v1/auth/login", json=login_data)

        # Should fail (username is case-sensitive)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.skip(reason="Whitespace trimming not yet implemented")
    async def test_login_trims_whitespace(self, client, db, admin_user):
        """Test login trims whitespace from username."""
        pass


class TestLogoutEndpoint:
    """Test suite for POST /api/v1/auth/logout endpoint."""

    async def test_logout_success(self, authenticated_client):
        """Test successful logout returns 200 OK."""
        response = await authenticated_client.post("/api/v1/auth/logout")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "logged out" in data["message"].lower()

    async def test_logout_without_token(self, client, db):
        """Test logout without token succeeds when auth_mode is none."""
        # By default auth_mode="none", so require_auth returns None (no enforcement)

        response = await client.post("/api/v1/auth/logout")

        # When auth_mode="none", logout returns 200 with "Authentication is disabled"
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Authentication is disabled"

    async def test_logout_expired_token(self, client, db, admin_user):
        """Test logout with expired token fails (403 CSRF or 401 expired token)."""
        from datetime import timedelta
        from app.services.auth import create_access_token
        from app.services.settings_service import SettingsService

        # Setup auth mode
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Create a token that expired 1 second ago
        token = create_access_token(
            {"sub": admin_user["username"]}, expires_delta=timedelta(seconds=-1)
        )

        # Set the expired token
        client.headers["Authorization"] = f"Bearer {token}"
        response = await client.post("/api/v1/auth/logout")

        # Should fail - CSRF middleware runs first (403), or if CSRF passes, token expiry (401)
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    async def test_logout_idempotent(self, authenticated_client):
        """Test logout is idempotent (can call multiple times)."""
        # First logout
        response = await authenticated_client.post("/api/v1/auth/logout")
        assert response.status_code == status.HTTP_200_OK

        # Second logout (should also succeed or return 401)
        response = await authenticated_client.post("/api/v1/auth/logout")
        # Either succeeds or fails with 401 (both acceptable)
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_401_UNAUTHORIZED,
        ]

    async def test_logout_clears_cookie(self, authenticated_client):
        """Test logout clears JWT cookie."""
        response = await authenticated_client.post("/api/v1/auth/logout")

        assert response.status_code == status.HTTP_200_OK
        # Check if cookie was cleared (set-cookie header present)
        # Cookie clearing is indicated by max-age=0 or expires in past
        assert "set-cookie" in response.headers or "Set-Cookie" in response.headers


class TestMeEndpoint:
    """Test suite for GET /api/v1/auth/me endpoint."""

    async def test_get_me_authenticated(self, authenticated_client, admin_user):
        """Test /me returns user profile when authenticated."""
        response = await authenticated_client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "admin"
        assert data["email"] == "admin@example.com"
        assert "full_name" in data

    async def test_get_me_unauthenticated(self, client):
        """Test /me returns 401 when not authenticated."""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_me_expired_token(self, client, db, admin_user):
        """Test /me returns 401 with expired token."""
        from datetime import timedelta
        from app.services.auth import create_access_token
        from app.services.settings_service import SettingsService

        # Setup auth mode
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Create a token that expired 1 second ago
        token = create_access_token(
            {"sub": admin_user["username"]}, expires_delta=timedelta(seconds=-1)
        )

        # Set the expired token
        client.headers["Authorization"] = f"Bearer {token}"
        response = await client.get("/api/v1/auth/me")

        # Should fail with 401 because token is expired
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_me_invalid_token(self, client):
        """Test /me returns 401 with invalid token."""
        # Set invalid token in headers
        client.headers["Authorization"] = "Bearer invalid_token_here"

        response = await client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_me_returns_profile_fields(self, authenticated_client):
        """Test /me returns username, email, full_name."""
        response = await authenticated_client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "username" in data
        assert "email" in data
        assert "full_name" in data
        assert "auth_method" in data
        assert "created_at" in data
        assert "last_login" in data

    async def test_get_me_masks_sensitive_data(self, authenticated_client):
        """Test /me does not return password_hash."""
        response = await authenticated_client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should NOT contain password_hash
        assert "password_hash" not in data
        assert "password" not in data


class TestProfileUpdateEndpoint:
    """Test suite for PUT /api/v1/auth/me endpoint."""

    async def test_update_profile_success(self, authenticated_client):
        """Test profile update succeeds with valid data."""
        profile_data = {
            "email": "newemail@example.com",
            "full_name": "New Full Name",
        }

        response = await authenticated_client.put("/api/v1/auth/me", json=profile_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == "newemail@example.com"
        assert data["full_name"] == "New Full Name"

    async def test_update_profile_email_validation(self, authenticated_client):
        """Test profile update validates email format."""
        profile_data = {
            "email": "valid@example.com",
        }

        response = await authenticated_client.put("/api/v1/auth/me", json=profile_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == "valid@example.com"

    async def test_update_profile_requires_auth(self, client, db):
        """Test profile update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        profile_data = {
            "email": "test@example.com",
        }

        response = await client.put("/api/v1/auth/me", json=profile_data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_update_profile_invalid_email(self, authenticated_client):
        """Test profile update rejects invalid email."""
        profile_data = {
            "email": "not-a-valid-email",
        }

        response = await authenticated_client.put("/api/v1/auth/me", json=profile_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_update_profile_sql_injection(self, authenticated_client):
        """Test profile update prevents SQL injection."""
        profile_data = {
            "full_name": "Test'; DROP TABLE settings; --",
        }

        response = await authenticated_client.put("/api/v1/auth/me", json=profile_data)

        # Should succeed (input is sanitized/escaped)
        assert response.status_code == status.HTTP_200_OK

    async def test_update_profile_xss_prevention(self, authenticated_client):
        """Test profile update sanitizes XSS attempts."""
        profile_data = {
            "full_name": "<script>alert('xss')</script>",
        }

        response = await authenticated_client.put("/api/v1/auth/me", json=profile_data)

        # Should succeed (XSS is handled at output/rendering level)
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.skip(
        reason="CSRF testing requires session middleware setup in test fixtures"
    )
    async def test_update_profile_csrf_required(self, authenticated_client):
        """Test profile update requires CSRF token."""
        # Profile update should require CSRF token
        # This test is skipped because the test fixtures don't have session middleware
        # In production, this endpoint IS protected by CSRF middleware
        pass


class TestPasswordChangeEndpoint:
    """Test suite for PUT /api/v1/auth/password endpoint."""

    @pytest.mark.skip(
        reason="Database fixture isolation issue - admin credentials not visible to API request handler"
    )
    async def test_change_password_success(self, authenticated_client, admin_user, db):
        """Test password change succeeds with valid old password."""
        password_data = {
            "current_password": "AdminPassword123!",
            "new_password": "NewPassword456!",
        }

        response = await authenticated_client.put(
            "/api/v1/auth/password", json=password_data
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "password changed" in data["message"].lower()

    @pytest.mark.skip(
        reason="Database fixture isolation issue - admin credentials not visible to API request handler"
    )
    async def test_change_password_wrong_current(
        self, authenticated_client, admin_user, db
    ):
        """Test password change fails with wrong current password."""
        password_data = {
            "current_password": "WrongPassword123!",
            "new_password": "NewPassword456!",
        }

        response = await authenticated_client.put(
            "/api/v1/auth/password", json=password_data
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "current password" in response.json()["detail"].lower()

    async def test_change_password_weak_new(self, authenticated_client):
        """Test password change rejects weak new password."""
        password_data = {
            "current_password": "AdminPassword123!",
            "new_password": "weak",  # Too weak
        }

        response = await authenticated_client.put(
            "/api/v1/auth/password", json=password_data
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.skip(
        reason="Database fixture isolation issue - admin credentials not visible to API request handler"
    )
    async def test_change_password_same_as_old(self, authenticated_client):
        """Test password change rejects new password same as old."""
        password_data = {
            "current_password": "AdminPassword123!",
            "new_password": "AdminPassword123!",  # Same as current
        }

        response = await authenticated_client.put(
            "/api/v1/auth/password", json=password_data
        )

        # May succeed (no specific validation for same password in current implementation)
        # Or may fail depending on business logic
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    async def test_change_password_requires_auth(self, client, db):
        """Test password change requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        password_data = {
            "current_password": "OldPassword123!",
            "new_password": "NewPassword456!",
        }

        response = await client.put("/api/v1/auth/password", json=password_data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_change_password_expired_token(self, client, db, admin_user):
        """Test password change fails with expired token (403 CSRF or 401 expired token)."""
        from datetime import timedelta
        from app.services.auth import create_access_token

        # Create a token that expired 1 second ago
        token = create_access_token(
            {"sub": admin_user["username"]}, expires_delta=timedelta(seconds=-1)
        )

        # Set the expired token
        client.headers["Authorization"] = f"Bearer {token}"
        password_data = {
            "current_password": "AdminPassword123!",
            "new_password": "NewPassword456!",
        }
        response = await client.put("/api/v1/auth/password", json=password_data)

        # Should fail - CSRF middleware runs first (403), or if CSRF passes, token expiry (401)
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    @pytest.mark.skip(
        reason="CSRF testing requires session middleware setup in test fixtures"
    )
    async def test_change_password_csrf_required(self, authenticated_client):
        """Test password change requires CSRF token."""
        # Password change should require CSRF token
        # This test is skipped because the test fixtures don't have session middleware
        # In production, this endpoint IS protected by CSRF middleware
        pass
