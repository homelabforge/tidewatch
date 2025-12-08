"""Encryption utilities for sensitive data storage.

Provides symmetric encryption for sensitive database fields such as:
- API keys (Docker Hub, GitHub, VulnForge, etc.)
- Authentication tokens (OIDC, notification services)
- Passwords (SMTP, database credentials)
- Webhook URLs (may contain secrets)

Uses Fernet (symmetric encryption) from the cryptography library:
- AES 128-bit encryption in CBC mode
- HMAC for authentication
- URL-safe base64 encoding
- Built-in key rotation support
"""

import os
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class EncryptionService:
    """Service for encrypting and decrypting sensitive data.

    Uses Fernet symmetric encryption with a key from environment variable.
    The encryption key must be generated once and stored securely.

    Key Generation:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    Environment Variable:
        TIDEWATCH_ENCRYPTION_KEY: Base64-encoded Fernet key (44 characters)

    Security Notes:
        - Encryption key must be kept secret
        - Key should be stored in environment variables, not in code
        - Key rotation requires re-encryption of all data
        - Uses authenticated encryption (prevents tampering)

    Example:
        >>> service = EncryptionService()
        >>> encrypted = service.encrypt("secret_api_key")
        >>> decrypted = service.decrypt(encrypted)
        >>> assert decrypted == "secret_api_key"
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize encryption service.

        Args:
            encryption_key: Base64-encoded Fernet key (default: from env var)

        Raises:
            ValueError: If encryption key is not configured or invalid
        """
        # Get encryption key from parameter or environment variable
        key_str = encryption_key or os.getenv("TIDEWATCH_ENCRYPTION_KEY")

        if not key_str:
            raise ValueError(
                "Encryption key not configured. Set TIDEWATCH_ENCRYPTION_KEY environment variable. "
                "Generate a key with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )

        # Validate key format and create Fernet cipher
        try:
            # Fernet expects bytes, convert from string
            key_bytes = key_str.encode('utf-8')
            self.cipher = Fernet(key_bytes)
            logger.debug("Encryption service initialized successfully")
        except Exception as e:
            raise ValueError(
                f"Invalid encryption key format: {e}. "
                "Key must be a valid base64-encoded Fernet key (44 characters). "
                "Generate with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: String to encrypt (API key, password, token, etc.)

        Returns:
            Base64-encoded encrypted string

        Raises:
            ValueError: If plaintext is None
            Exception: If encryption fails

        Example:
            >>> service = EncryptionService()
            >>> encrypted = service.encrypt("my_secret_api_key")
            >>> print(len(encrypted))  # Encrypted string is longer
            140
        """
        if plaintext is None:
            raise ValueError("Cannot encrypt None value")

        # Allow empty strings (some settings might be intentionally empty)
        if plaintext == "":
            return ""

        try:
            # Fernet.encrypt() expects bytes, returns bytes
            encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))
            # Convert to string for database storage
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If ciphertext is None or empty
            InvalidToken: If ciphertext was tampered with or wrong key used
            Exception: If decryption fails

        Example:
            >>> service = EncryptionService()
            >>> encrypted = service.encrypt("secret")
            >>> decrypted = service.decrypt(encrypted)
            >>> assert decrypted == "secret"
        """
        if ciphertext is None:
            raise ValueError("Cannot decrypt None value")

        # Handle empty strings
        if ciphertext == "":
            return ""

        try:
            # Fernet.decrypt() expects bytes, returns bytes
            decrypted_bytes = self.cipher.decrypt(ciphertext.encode('utf-8'))
            # Convert to string
            return decrypted_bytes.decode('utf-8')
        except InvalidToken:
            logger.error("Decryption failed: Invalid token (wrong key or tampered data)")
            raise ValueError(
                "Failed to decrypt data. This could mean:\n"
                "1. Encryption key has changed\n"
                "2. Data was tampered with\n"
                "3. Data was encrypted with a different key\n"
                "You may need to re-enter this value in Settings."
            )
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def is_encrypted(self, value: str) -> bool:
        """Check if a value appears to be encrypted.

        This is a heuristic check based on Fernet's format.
        Fernet tokens start with "gAAAAA" after base64 encoding.

        Args:
            value: String to check

        Returns:
            True if value appears to be encrypted, False otherwise

        Note:
            This is not 100% reliable but good enough for detecting
            whether a setting needs encryption or is already encrypted.

        Example:
            >>> service = EncryptionService()
            >>> encrypted = service.encrypt("secret")
            >>> service.is_encrypted(encrypted)
            True
            >>> service.is_encrypted("plaintext")
            False
        """
        if not value or len(value) < 7:
            return False

        # Fernet tokens are base64-encoded and start with specific bytes
        # After base64 encoding, they typically start with "gAAAAA"
        # This is because Fernet format is: version (1 byte = 0x80) + timestamp (8 bytes)
        # 0x80 in base64 is 'g'
        return value.startswith('gAAAAA')


# Global encryption service instance (lazy initialization)
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Get or create the global encryption service instance.

    Returns:
        Singleton EncryptionService instance

    Raises:
        ValueError: If encryption key is not configured

    Example:
        >>> service = get_encryption_service()
        >>> encrypted = service.encrypt("secret")
    """
    global _encryption_service

    if _encryption_service is None:
        _encryption_service = EncryptionService()

    return _encryption_service


def encrypt_value(plaintext: str) -> str:
    """Convenience function to encrypt a value using the global service.

    Args:
        plaintext: String to encrypt

    Returns:
        Encrypted string

    Example:
        >>> encrypted = encrypt_value("my_api_key")
    """
    service = get_encryption_service()
    return service.encrypt(plaintext)


def decrypt_value(ciphertext: str) -> str:
    """Convenience function to decrypt a value using the global service.

    Args:
        ciphertext: Encrypted string

    Returns:
        Decrypted plaintext

    Example:
        >>> decrypted = decrypt_value(encrypted_data)
    """
    service = get_encryption_service()
    return service.decrypt(ciphertext)


def is_encryption_configured() -> bool:
    """Check if encryption is configured (key present in environment).

    Returns:
        True if TIDEWATCH_ENCRYPTION_KEY is set, False otherwise

    Example:
        >>> if is_encryption_configured():
        ...     service = get_encryption_service()
    """
    return bool(os.getenv("TIDEWATCH_ENCRYPTION_KEY"))
