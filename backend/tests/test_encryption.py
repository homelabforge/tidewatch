"""Tests for encryption service (app/utils/encryption.py).

Tests AES-128 Fernet encryption/decryption for sensitive data:
- API keys, tokens, passwords, webhook URLs
- Encryption/decryption roundtrips
- Invalid token detection (tampering)
- Empty string handling
- Key validation
- is_encrypted() detection logic
"""

import pytest
from cryptography.fernet import Fernet

from app.utils.encryption import (
    EncryptionService,
    get_encryption_service,
    encrypt_value,
    decrypt_value,
    is_encryption_configured,
)


class TestEncryptionService:
    """Test suite for EncryptionService class."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        return Fernet.generate_key().decode()

    @pytest.fixture
    def service(self, encryption_key):
        """Create EncryptionService instance with test key."""
        return EncryptionService(encryption_key=encryption_key)

    def test_initialization_with_valid_key(self, encryption_key):
        """Test EncryptionService initializes with valid key."""
        service = EncryptionService(encryption_key=encryption_key)
        assert service.cipher is not None

    def test_initialization_without_key_raises_error(self, monkeypatch):
        """Test EncryptionService raises ValueError without key."""
        monkeypatch.delenv("TIDEWATCH_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError) as exc_info:
            EncryptionService()

        assert "Encryption key not configured" in str(exc_info.value)
        assert "TIDEWATCH_ENCRYPTION_KEY" in str(exc_info.value)

    def test_initialization_with_invalid_key_format(self):
        """Test EncryptionService raises ValueError with invalid key format."""
        with pytest.raises(ValueError) as exc_info:
            EncryptionService(encryption_key="invalid_key")

        assert "Invalid encryption key format" in str(exc_info.value)

    def test_initialization_from_environment_variable(
        self, encryption_key, monkeypatch
    ):
        """Test EncryptionService loads key from environment."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)
        service = EncryptionService()
        assert service.cipher is not None

    def test_encrypt_decrypt_roundtrip(self, service):
        """Test encryption/decryption returns original value."""
        plaintext = "my_secret_api_key_12345"

        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_encrypt_various_data_types(self, service):
        """Test encryption works with various string types."""
        test_cases = [
            "simple_password",
            "password_with_$pecial_chars!@#",
            "very_long_" + "x" * 1000,
            "unicode_emoji_🔐🔑",
            "newline\\ncharacter",
            "tab\\tcharacter",
            "single_char_a",
        ]

        for plaintext in test_cases:
            encrypted = service.encrypt(plaintext)
            decrypted = service.decrypt(encrypted)
            assert decrypted == plaintext, f"Failed for: {plaintext[:50]}"

    def test_encrypt_empty_string_returns_empty(self, service):
        """Test encrypting empty string returns empty string."""
        assert service.encrypt("") == ""

    def test_decrypt_empty_string_returns_empty(self, service):
        """Test decrypting empty string returns empty string."""
        assert service.decrypt("") == ""

    def test_encrypt_none_raises_error(self, service):
        """Test encrypting None raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            service.encrypt(None)

        assert "Cannot encrypt None value" in str(exc_info.value)

    def test_decrypt_none_raises_error(self, service):
        """Test decrypting None raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            service.decrypt(None)

        assert "Cannot decrypt None value" in str(exc_info.value)

    def test_decrypt_invalid_token_raises_error(self, service):
        """Test decrypting tampered data raises ValueError."""
        encrypted = service.encrypt("secret")

        # Tamper with encrypted data
        tampered = encrypted[:-5] + "XXXXX"

        with pytest.raises(ValueError) as exc_info:
            service.decrypt(tampered)

        assert "Failed to decrypt data" in str(exc_info.value)
        assert "encryption key has changed" in str(exc_info.value).lower()

    def test_decrypt_with_wrong_key_raises_error(self, encryption_key):
        """Test decrypting with different key raises ValueError."""
        service1 = EncryptionService(encryption_key=encryption_key)
        encrypted = service1.encrypt("secret")

        # Create service with different key
        different_key = Fernet.generate_key().decode()
        service2 = EncryptionService(encryption_key=different_key)

        with pytest.raises(ValueError) as exc_info:
            service2.decrypt(encrypted)

        assert "Failed to decrypt data" in str(exc_info.value)

    def test_decrypt_random_string_raises_error(self, service):
        """Test decrypting random string (not encrypted) raises ValueError."""
        with pytest.raises(ValueError):
            service.decrypt("this_is_not_encrypted_data")

    def test_is_encrypted_detects_encrypted_data(self, service):
        """Test is_encrypted() correctly identifies encrypted data."""
        plaintext = "secret_api_key"
        encrypted = service.encrypt(plaintext)

        assert service.is_encrypted(encrypted) is True
        assert service.is_encrypted(plaintext) is False

    def test_is_encrypted_with_fernet_signature(self, service):
        """Test is_encrypted() recognizes Fernet signature."""
        # Fernet tokens start with 'gAAAAA' after base64 encoding
        assert service.is_encrypted("gAAAAABfake_encrypted_token") is True
        assert service.is_encrypted("normal_string") is False

    def test_is_encrypted_edge_cases(self, service):
        """Test is_encrypted() handles edge cases."""
        assert service.is_encrypted("") is False
        assert service.is_encrypted("short") is False
        assert service.is_encrypted("gAAAA") is False  # Too short
        assert service.is_encrypted("gAAAAAB") is True  # Minimum valid

    def test_encrypted_data_is_different_each_time(self, service):
        """Test encrypting same plaintext produces different ciphertext."""
        plaintext = "secret"

        encrypted1 = service.encrypt(plaintext)
        encrypted2 = service.encrypt(plaintext)

        # Different ciphertexts (due to IV/timestamp)
        assert encrypted1 != encrypted2

        # But both decrypt to same plaintext
        assert service.decrypt(encrypted1) == plaintext
        assert service.decrypt(encrypted2) == plaintext

    def test_encrypted_data_length_increases(self, service):
        """Test encrypted data is longer than plaintext."""
        plaintext = "short"
        encrypted = service.encrypt(plaintext)

        # Fernet adds overhead (version, timestamp, IV, padding, HMAC)
        assert len(encrypted) > len(plaintext)

    def test_sensitive_data_roundtrip_examples(self, service):
        """Test encryption of realistic sensitive data examples."""
        test_cases = {
            "dockerhub_token": "dckr_pat_1234567890abcdefghij",
            "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "smtp_password": "P@ssw0rd!ComplexPassword123",
            "webhook_url": "https://hooks.slack.com/services/T00/B00/XXXXXXXXXXXX",
            "gotify_token": "AnwDM91c5Xx_Nxx",
            "vulnforge_api_key": "vf_12345678901234567890",
        }

        for key, plaintext in test_cases.items():
            encrypted = service.encrypt(plaintext)
            decrypted = service.decrypt(encrypted)
            assert decrypted == plaintext, f"Failed for {key}"
            assert service.is_encrypted(encrypted), f"Detection failed for {key}"


class TestGlobalEncryptionFunctions:
    """Test suite for global encryption helper functions."""

    @pytest.fixture(autouse=True)
    def reset_global_service(self):
        """Reset global encryption service before each test."""
        import app.utils.encryption

        app.utils.encryption._encryption_service = None
        yield
        app.utils.encryption._encryption_service = None

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        return Fernet.generate_key().decode()

    def test_is_encryption_configured_with_env_var(self, encryption_key, monkeypatch):
        """Test is_encryption_configured() returns True when env var set."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)
        assert is_encryption_configured() is True

    def test_is_encryption_configured_without_env_var(self, monkeypatch):
        """Test is_encryption_configured() returns False without env var."""
        monkeypatch.delenv("TIDEWATCH_ENCRYPTION_KEY", raising=False)
        assert is_encryption_configured() is False

    def test_get_encryption_service_singleton(self, encryption_key, monkeypatch):
        """Test get_encryption_service() returns same instance."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)

        service1 = get_encryption_service()
        service2 = get_encryption_service()

        assert service1 is service2

    def test_get_encryption_service_raises_without_key(self, monkeypatch):
        """Test get_encryption_service() raises ValueError without key."""
        monkeypatch.delenv("TIDEWATCH_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError) as exc_info:
            get_encryption_service()

        assert "Encryption key not configured" in str(exc_info.value)

    def test_encrypt_value_convenience_function(self, encryption_key, monkeypatch):
        """Test encrypt_value() convenience function."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)

        plaintext = "test_secret"
        encrypted = encrypt_value(plaintext)

        assert encrypted != plaintext
        assert len(encrypted) > len(plaintext)

    def test_decrypt_value_convenience_function(self, encryption_key, monkeypatch):
        """Test decrypt_value() convenience function."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)

        plaintext = "test_secret"
        encrypted = encrypt_value(plaintext)
        decrypted = decrypt_value(encrypted)

        assert decrypted == plaintext

    def test_encrypt_decrypt_value_roundtrip(self, encryption_key, monkeypatch):
        """Test full roundtrip with convenience functions."""
        monkeypatch.setenv("TIDEWATCH_ENCRYPTION_KEY", encryption_key)

        test_secrets = [
            "api_key_12345",
            "webhook_url_https://example.com/hook",
            "password_with_$pecial!",
        ]

        for secret in test_secrets:
            encrypted = encrypt_value(secret)
            decrypted = decrypt_value(encrypted)
            assert decrypted == secret


class TestEncryptionSecurityProperties:
    """Test suite for security properties of encryption."""

    @pytest.fixture
    def service(self):
        """Create EncryptionService with generated key."""
        key = Fernet.generate_key().decode()
        return EncryptionService(encryption_key=key)

    def test_encrypted_data_contains_no_plaintext_fragments(self, service):
        """Test encrypted data doesn't contain plaintext fragments."""
        plaintext = "my_secret_password_12345"
        encrypted = service.encrypt(plaintext)

        # Check no obvious fragments appear in encrypted data
        assert "secret" not in encrypted.lower()
        assert "password" not in encrypted.lower()
        assert "12345" not in encrypted

    def test_encryption_uses_authenticated_encryption(self, service):
        """Test Fernet uses authenticated encryption (tamper detection)."""
        encrypted = service.encrypt("secret")

        # Modify a single character
        tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")

        # Should detect tampering
        with pytest.raises(ValueError):
            service.decrypt(tampered)

    def test_encryption_includes_timestamp(self, service):
        """Test Fernet includes timestamp in encrypted data."""
        import time

        plaintext = "secret"

        # Encrypt at different times
        encrypted1 = service.encrypt(plaintext)
        time.sleep(0.1)
        encrypted2 = service.encrypt(plaintext)

        # Different due to timestamp
        assert encrypted1 != encrypted2

    def test_encryption_key_validation_prevents_weak_keys(self):
        """Test service rejects keys that are too short."""
        weak_keys = [
            "short",
            "1234567890",
            "not_base64_encoded_properly",
        ]

        for weak_key in weak_keys:
            with pytest.raises(ValueError):
                EncryptionService(encryption_key=weak_key)

    def test_encryption_output_is_base64_safe(self, service):
        """Test encrypted output is URL-safe base64."""
        plaintext = "secret_with_special_chars!@#$%"
        encrypted = service.encrypt(plaintext)

        # Should only contain base64 URL-safe characters
        import re

        assert re.match(r"^[A-Za-z0-9_-]+$", encrypted.replace("=", ""))
