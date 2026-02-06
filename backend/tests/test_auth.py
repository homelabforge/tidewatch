"""Tests for authentication service (app/services/auth.py).

Tests JWT authentication, password hashing, and admin management:
- JWT token creation/validation/expiration
- Password hashing with Argon2id
- Secret key generation and persistence
- Admin profile management
- Session validation
- Auth mode switching (none/local/oidc)
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from authlib.jose import jwt
from fastapi import HTTPException

from app.services import auth
from app.services.auth import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_admin,
    create_access_token,
    decode_token,
    get_admin_profile,
    get_auth_mode,
    get_or_create_secret_key,
    hash_password,
    is_setup_complete,
    update_admin_password,
    update_admin_profile,
    verify_password,
)


class TestPasswordHashing:
    """Test suite for Argon2id password hashing."""

    def test_hash_password_creates_valid_hash(self):
        """Test hash_password() creates Argon2 hash."""
        password = "SecurePassword123!"
        hashed = hash_password(password)

        # Argon2 hashes start with $argon2id$
        assert hashed.startswith("$argon2id$")
        assert len(hashed) > 50  # Argon2 hashes are long

    def test_hash_password_different_each_time(self):
        """Test hashing same password produces different hashes (salt)."""
        password = "TestPassword123"

        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Different due to random salt

    def test_verify_password_correct_password(self):
        """Test verify_password() returns True for correct password."""
        password = "MySecretPassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect_password(self):
        """Test verify_password() returns False for wrong password."""
        password = "CorrectPassword"
        wrong_password = "WrongPassword"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_case_sensitive(self):
        """Test password verification is case-sensitive."""
        password = "CaseSensitive"
        hashed = hash_password(password)

        assert verify_password("casesensitive", hashed) is False
        assert verify_password("CASESENSITIVE", hashed) is False

    def test_verify_password_invalid_hash_format(self):
        """Test verify_password() returns False for invalid hash."""
        assert verify_password("password", "invalid_hash") is False
        assert verify_password("password", "$2b$12$invalid") is False

    def test_hash_password_various_lengths(self):
        """Test hashing passwords of various lengths."""
        passwords = [
            "short",
            "medium_length_password",
            "very_long_password_" + "x" * 100,
        ]

        for password in passwords:
            hashed = hash_password(password)
            assert verify_password(password, hashed) is True

    def test_hash_password_special_characters(self):
        """Test hashing passwords with special characters."""
        passwords = [
            "P@ssw0rd!",
            "password_with_$pecial_chars",
            "unicode_emoji_🔐",
            "newline\\n",
            "tab\\t",
        ]

        for password in passwords:
            hashed = hash_password(password)
            assert verify_password(password, hashed) is True


class TestSecretKeyManagement:
    """Test suite for JWT secret key generation and persistence."""

    def test_get_or_create_secret_key_creates_new_key(self):
        """Test get_or_create_secret_key() creates key file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "test.key"

            # Mock sanitize_path to return our temp file
            with patch("app.utils.security.sanitize_path", return_value=key_file):
                secret_key = get_or_create_secret_key(key_file)

                # Key should be created
                assert len(secret_key) > 30
                assert key_file.exists()

                # Key should be persisted
                saved_key = key_file.read_text().strip()
                assert saved_key == secret_key

    def test_get_or_create_secret_key_loads_existing_key(self):
        """Test get_or_create_secret_key() loads existing key file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "existing.key"
            existing_key = "existing_secret_key_12345"
            key_file.write_text(existing_key)

            with patch("app.utils.security.sanitize_path", return_value=key_file):
                loaded_key = get_or_create_secret_key(key_file)
                assert loaded_key == existing_key

    def test_get_or_create_secret_key_file_permissions(self):
        """Test secret key file has restrictive permissions (0600)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "test.key"

            with patch("app.utils.security.sanitize_path", return_value=key_file):
                get_or_create_secret_key(key_file)

                # Check file permissions (owner read/write only)
                stat_info = key_file.stat()
                permissions = oct(stat_info.st_mode)[-3:]
                assert permissions == "600"

    def test_get_or_create_secret_key_fallback_on_path_error(self):
        """Test fallback to in-memory key on path validation error."""
        with patch("app.utils.security.sanitize_path", side_effect=ValueError("Invalid path")):
            secret_key = get_or_create_secret_key(Path("/invalid/path"))

            # Should still return a key (in-memory)
            assert len(secret_key) > 30

    def test_get_or_create_secret_key_creates_parent_directory(self):
        """Test key file creation creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "nested" / "dir" / "test.key"

            with patch("app.utils.security.sanitize_path", return_value=key_file):
                get_or_create_secret_key(key_file)

                assert key_file.exists()
                assert key_file.parent.exists()

    def test_get_or_create_secret_key_empty_file_regenerates(self):
        """Test empty key file triggers regeneration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "empty.key"
            key_file.write_text("")  # Empty file

            with patch("app.utils.security.sanitize_path", return_value=key_file):
                secret_key = get_or_create_secret_key(key_file)

                # Should generate new key
                assert len(secret_key) > 30
                assert key_file.read_text().strip() == secret_key


class TestJWTOperations:
    """Test suite for JWT token creation and validation."""

    @pytest.fixture
    def sample_payload(self):
        """Sample JWT payload for testing."""
        return {"sub": "admin", "username": "admin", "email": "admin@example.com"}

    def test_create_access_token_includes_required_fields(self, sample_payload):
        """Test create_access_token() includes exp and iat fields."""
        token = create_access_token(sample_payload)

        # Decode without verification for testing
        decoded = jwt.decode(token, auth._SECRET_KEY)

        assert "exp" in decoded
        assert "iat" in decoded
        assert decoded["sub"] == "admin"
        assert decoded["username"] == "admin"

    def test_create_access_token_default_expiration(self, sample_payload):
        """Test token expires after default time (24 hours)."""
        token = create_access_token(sample_payload)
        decoded = jwt.decode(token, auth._SECRET_KEY)

        exp = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        iat = datetime.fromtimestamp(decoded["iat"], tz=UTC)

        # Should expire in approximately 24 hours
        expected_delta = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        actual_delta = exp - iat

        assert abs((actual_delta - expected_delta).total_seconds()) < 5  # 5 second tolerance

    def test_create_access_token_custom_expiration(self, sample_payload):
        """Test token with custom expiration delta."""
        custom_delta = timedelta(minutes=30)
        token = create_access_token(sample_payload, expires_delta=custom_delta)
        decoded = jwt.decode(token, auth._SECRET_KEY)

        exp = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        iat = datetime.fromtimestamp(decoded["iat"], tz=UTC)

        actual_delta = exp - iat
        assert abs((actual_delta - custom_delta).total_seconds()) < 5

    def test_create_access_token_preserves_payload(self, sample_payload):
        """Test token preserves all payload fields."""
        token = create_access_token(sample_payload)
        decoded = jwt.decode(token, auth._SECRET_KEY)

        for key, value in sample_payload.items():
            assert decoded[key] == value

    def test_decode_token_valid_token(self, sample_payload):
        """Test decode_token() successfully decodes valid token."""
        token = create_access_token(sample_payload)
        decoded = decode_token(token)

        assert decoded["sub"] == sample_payload["sub"]
        assert decoded["username"] == sample_payload["username"]

    def test_decode_token_expired_token_raises_exception(self, sample_payload):
        """Test decode_token() raises HTTPException for expired token."""
        # Create token that expires immediately
        expired_delta = timedelta(seconds=-1)
        token = create_access_token(sample_payload, expires_delta=expired_delta)

        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    def test_decode_token_invalid_signature_raises_exception(self, sample_payload):
        """Test decode_token() raises HTTPException for tampered token."""
        token = create_access_token(sample_payload)

        # Tamper with token
        tampered_token = token[:-5] + "XXXXX"

        with pytest.raises(HTTPException) as exc_info:
            decode_token(tampered_token)

        assert exc_info.value.status_code == 401

    def test_decode_token_malformed_token_raises_exception(self):
        """Test decode_token() raises HTTPException for malformed token."""
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.valid.jwt.token")

        assert exc_info.value.status_code == 401

    def test_create_access_token_uses_hs256_algorithm(self, sample_payload):
        """Test JWT uses HS256 algorithm."""
        token = create_access_token(sample_payload)

        # Decode header
        import base64
        import json

        header_b64 = token.split(".")[0]
        # Add padding if needed
        header_b64 += "=" * (4 - len(header_b64) % 4)
        header_json = base64.urlsafe_b64decode(header_b64)
        header = json.loads(header_json)

        assert header["alg"] == "HS256"


class TestAdminProfileManagement:
    """Test suite for admin profile management."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_settings_service(self):
        """Mock SettingsService."""
        with patch("app.services.auth.SettingsService") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_is_setup_complete_auth_disabled(self, mock_db, mock_settings_service):
        """Test is_setup_complete() returns True when auth disabled."""
        mock_settings_service.get = AsyncMock(return_value="none")

        result = await is_setup_complete(mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_setup_complete_admin_exists(self, mock_db, mock_settings_service):
        """Test is_setup_complete() returns True when admin exists."""
        # First call returns 'local', second call returns 'admin_user'
        mock_settings_service.get = AsyncMock(side_effect=["local", "admin_user"])

        result = await is_setup_complete(mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_setup_complete_no_admin(self, mock_db, mock_settings_service):
        """Test is_setup_complete() returns False when no admin."""
        mock_settings_service.get = AsyncMock(side_effect=["local", ""])

        result = await is_setup_complete(mock_db)

        assert result is False

    @pytest.mark.asyncio
    async def test_get_admin_profile_returns_profile(self, mock_db, mock_settings_service):
        """Test get_admin_profile() returns complete profile dict."""

        async def mock_get(db, key, default=""):
            profile_data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_email": "admin@example.com",
                "admin_full_name": "Administrator",
                "admin_auth_method": "local",
                "admin_oidc_provider": "",
                "admin_created_at": "2025-01-01T00:00:00Z",
                "admin_last_login": "2025-01-15T10:30:00Z",
            }
            return profile_data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)

        profile = await get_admin_profile(mock_db)
        assert profile is not None

        assert profile["username"] == "admin"
        assert profile["email"] == "admin@example.com"
        assert profile["full_name"] == "Administrator"
        assert profile["auth_method"] == "local"

    @pytest.mark.asyncio
    async def test_get_admin_profile_setup_not_complete(self, mock_db, mock_settings_service):
        """Test get_admin_profile() returns None when setup incomplete."""
        mock_settings_service.get = AsyncMock(side_effect=["local", ""])

        profile = await get_admin_profile(mock_db)

        assert profile is None

    @pytest.mark.asyncio
    async def test_update_admin_profile_updates_email(self, mock_db, mock_settings_service):
        """Test update_admin_profile() updates email."""
        mock_settings_service.set = AsyncMock()

        await update_admin_profile(mock_db, email="newemail@example.com")

        mock_settings_service.set.assert_called_once_with(
            mock_db, "admin_email", "newemail@example.com"
        )

    @pytest.mark.asyncio
    async def test_update_admin_profile_updates_full_name(self, mock_db, mock_settings_service):
        """Test update_admin_profile() updates full name."""
        mock_settings_service.set = AsyncMock()

        await update_admin_profile(mock_db, full_name="John Doe")

        mock_settings_service.set.assert_called_once_with(mock_db, "admin_full_name", "John Doe")

    @pytest.mark.asyncio
    async def test_update_admin_profile_updates_both(self, mock_db, mock_settings_service):
        """Test update_admin_profile() updates both fields."""
        mock_settings_service.set = AsyncMock()

        await update_admin_profile(mock_db, email="new@example.com", full_name="New Name")

        assert mock_settings_service.set.call_count == 2

    @pytest.mark.asyncio
    async def test_update_admin_password(self, mock_db, mock_settings_service):
        """Test update_admin_password() updates password hash."""
        mock_settings_service.set = AsyncMock()
        new_hash = "$argon2id$v=19$m=102400,t=2,p=8$..."

        await update_admin_password(mock_db, new_hash)

        mock_settings_service.set.assert_called_once_with(mock_db, "admin_password_hash", new_hash)


class TestAuthentication:
    """Test suite for admin authentication."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_settings_service(self):
        """Mock SettingsService."""
        with patch("app.services.auth.SettingsService") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_authenticate_admin_success(self, mock_db, mock_settings_service):
        """Test authenticate_admin() succeeds with correct credentials."""
        password = "SecurePassword123!"
        password_hash = hash_password(password)

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_email": "admin@example.com",
                "admin_password_hash": password_hash,
                "admin_auth_method": "local",
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)
        mock_settings_service.set = AsyncMock()

        profile = await authenticate_admin(mock_db, "admin", password)

        assert profile is not None
        assert profile["username"] == "admin"

    @pytest.mark.asyncio
    async def test_authenticate_admin_wrong_username(self, mock_db, mock_settings_service):
        """Test authenticate_admin() fails with wrong username."""
        password = "SecurePassword123!"
        password_hash = hash_password(password)

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_password_hash": password_hash,
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)

        profile = await authenticate_admin(mock_db, "wrong_user", password)

        assert profile is None

    @pytest.mark.asyncio
    async def test_authenticate_admin_wrong_password(self, mock_db, mock_settings_service):
        """Test authenticate_admin() fails with wrong password."""
        password_hash = hash_password("CorrectPassword")

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_password_hash": password_hash,
                "admin_auth_method": "local",
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)

        profile = await authenticate_admin(mock_db, "admin", "WrongPassword")

        assert profile is None

    @pytest.mark.asyncio
    async def test_authenticate_admin_no_password_hash(self, mock_db, mock_settings_service):
        """Test authenticate_admin() fails when no password hash set."""

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_password_hash": "",  # No password set
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)

        profile = await authenticate_admin(mock_db, "admin", "AnyPassword")

        assert profile is None

    @pytest.mark.asyncio
    async def test_authenticate_admin_oidc_user_rejects_password(
        self, mock_db, mock_settings_service
    ):
        """Test authenticate_admin() rejects password login for OIDC users."""
        password_hash = hash_password("SomePassword")

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_password_hash": password_hash,
                "admin_auth_method": "oidc",  # OIDC user
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)

        profile = await authenticate_admin(mock_db, "admin", "SomePassword")

        assert profile is None

    @pytest.mark.asyncio
    async def test_authenticate_admin_updates_last_login(self, mock_db, mock_settings_service):
        """Test authenticate_admin() updates last_login timestamp."""
        password = "SecurePassword123!"
        password_hash = hash_password(password)

        async def mock_get(db, key, default=""):
            data = {
                "auth_mode": "local",
                "admin_username": "admin",
                "admin_password_hash": password_hash,
                "admin_auth_method": "local",
            }
            return data.get(key, default)

        mock_settings_service.get = AsyncMock(side_effect=mock_get)
        mock_settings_service.set = AsyncMock()

        await authenticate_admin(mock_db, "admin", password)

        # Check last_login was updated
        set_calls = mock_settings_service.set.call_args_list
        last_login_call = [call for call in set_calls if call[0][1] == "admin_last_login"]
        assert len(last_login_call) == 1


class TestAuthMode:
    """Test suite for auth mode management."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_settings_service(self):
        """Mock SettingsService."""
        with patch("app.services.auth.SettingsService") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_get_auth_mode_none(self, mock_db, mock_settings_service):
        """Test get_auth_mode() returns 'none'."""
        mock_settings_service.get = AsyncMock(return_value="none")

        mode = await get_auth_mode(mock_db)

        assert mode == "none"

    @pytest.mark.asyncio
    async def test_get_auth_mode_local(self, mock_db, mock_settings_service):
        """Test get_auth_mode() returns 'local'."""
        mock_settings_service.get = AsyncMock(return_value="local")

        mode = await get_auth_mode(mock_db)

        assert mode == "local"

    @pytest.mark.asyncio
    async def test_get_auth_mode_oidc(self, mock_db, mock_settings_service):
        """Test get_auth_mode() returns 'oidc'."""
        mock_settings_service.get = AsyncMock(return_value="oidc")

        mode = await get_auth_mode(mock_db)

        assert mode == "oidc"

    @pytest.mark.asyncio
    async def test_get_auth_mode_case_insensitive(self, mock_db, mock_settings_service):
        """Test get_auth_mode() converts to lowercase."""
        mock_settings_service.get = AsyncMock(return_value="LOCAL")

        mode = await get_auth_mode(mock_db)

        assert mode == "local"

    @pytest.mark.asyncio
    async def test_get_auth_mode_default_none(self, mock_db, mock_settings_service):
        """Test get_auth_mode() defaults to 'none'."""
        mock_settings_service.get = AsyncMock(return_value=None)

        mode = await get_auth_mode(mock_db)

        assert mode == "none"
