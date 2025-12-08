"""Tests for security utilities (app/utils/security.py).

Tests input sanitization and validation to prevent security vulnerabilities:
- Log injection prevention via sanitize_log_message()
- Path traversal detection in sanitize_path()
- Sensitive data masking for logs
- Container/image name validation
- Filename safety checks
"""

import pytest
import tempfile
from pathlib import Path

from app.utils.security import (
    sanitize_log_message,
    mask_sensitive,
    sanitize_path,
    is_safe_filename,
    validate_container_name,
    validate_image_name,
)


class TestSanitizeLogMessage:
    """Test suite for log injection prevention."""

    def test_removes_newlines(self):
        """Test sanitize_log_message() removes newline characters."""
        message = "Container\\nmalicious\\nlog"
        sanitized = sanitize_log_message(message)

        assert "\\n" not in sanitized
        assert sanitized == "Containermaliciouslog"

    def test_removes_carriage_returns(self):
        """Test sanitize_log_message() removes carriage returns."""
        message = "User: admin\\r\\nPassword: secret"
        sanitized = sanitize_log_message(message)

        assert "\\r" not in sanitized
        assert "\\n" not in sanitized
        assert sanitized == "User: adminPassword: secret"

    def test_removes_tabs(self):
        """Test sanitize_log_message() removes tab characters."""
        message = "field1\\tfield2\\tfield3"
        sanitized = sanitize_log_message(message)

        assert "\\t" not in sanitized
        assert sanitized == "field1field2field3"

    def test_removes_control_characters(self):
        """Test sanitize_log_message() removes control characters."""
        # ASCII control characters (0x00-0x1f)
        message = "text\\x00null\\x01control\\x1fmore"
        sanitized = sanitize_log_message(message)

        # Should only contain printable characters
        assert "\\x00" not in sanitized
        assert "\\x01" not in sanitized
        assert "\\x1f" not in sanitized

    def test_preserves_normal_text(self):
        """Test sanitize_log_message() preserves normal text."""
        message = "Normal log message with spaces and punctuation!"
        sanitized = sanitize_log_message(message)

        assert sanitized == message

    def test_handles_none_input(self):
        """Test sanitize_log_message() handles None input."""
        assert sanitize_log_message(None) == ""

    def test_handles_empty_string(self):
        """Test sanitize_log_message() handles empty string."""
        assert sanitize_log_message("") == ""

    def test_handles_numeric_input(self):
        """Test sanitize_log_message() converts numbers to strings."""
        assert sanitize_log_message(123) == "123"
        assert sanitize_log_message(45.67) == "45.67"

    def test_handles_bytes_input(self):
        """Test sanitize_log_message() handles bytes input."""
        message = b"byte string"
        sanitized = sanitize_log_message(message)

        assert isinstance(sanitized, str)
        assert sanitized == "b'byte string'"

    def test_prevents_log_injection_attacks(self):
        """Test sanitize_log_message() prevents log injection."""
        # Attacker tries to inject fake log entries
        malicious = "Valid log\\n[ERROR] Fake error message\\n[CRITICAL] System compromised"
        sanitized = sanitize_log_message(malicious)

        # All newlines removed - appears as single line
        assert "\\n" not in sanitized
        assert sanitized.count("[ERROR]") == 1
        assert sanitized.count("[CRITICAL]") == 1

    def test_removes_ansi_escape_codes(self):
        """Test sanitize_log_message() removes ANSI escape codes."""
        # ANSI escape codes use control characters
        message = "\\x1b[31mRed text\\x1b[0m"
        sanitized = sanitize_log_message(message)

        assert "\\x1b" not in sanitized

    def test_long_messages(self):
        """Test sanitize_log_message() handles long messages."""
        long_message = "x" * 10000 + "\\n" + "y" * 10000
        sanitized = sanitize_log_message(long_message)

        assert "\\n" not in sanitized
        assert len(sanitized) == 20000


class TestMaskSensitive:
    """Test suite for sensitive data masking."""

    def test_masks_api_key_shows_last_4(self):
        """Test mask_sensitive() shows only last 4 characters."""
        api_key = "sk_live_1234567890abcdef"
        masked = mask_sensitive(api_key)

        assert masked == "***cdef"

    def test_masks_with_custom_visible_chars(self):
        """Test mask_sensitive() with custom visible character count."""
        value = "password123"
        masked = mask_sensitive(value, visible_chars=3)

        assert masked == "***123"

    def test_masks_short_values_completely(self):
        """Test mask_sensitive() masks short values completely."""
        short_values = ["abc", "12", "x", ""]

        for value in short_values:
            masked = mask_sensitive(value, visible_chars=4)
            assert masked == "***"

    def test_masks_none_value(self):
        """Test mask_sensitive() handles None."""
        assert mask_sensitive(None) == "***"

    def test_masks_empty_string(self):
        """Test mask_sensitive() handles empty string."""
        assert mask_sensitive("") == "***"

    def test_masks_with_custom_mask_character(self):
        """Test mask_sensitive() with custom mask character."""
        value = "secret123456"
        masked = mask_sensitive(value, mask_char="X")

        assert masked == "XXX3456"

    def test_never_shows_beginning_of_secret(self):
        """Test mask_sensitive() never reveals start of secret."""
        secrets = [
            "ghp_1234567890abcdefghij",
            "dckr_pat_abcdefghij",
            "key_with_prefix_12345",
        ]

        for secret in secrets:
            masked = mask_sensitive(secret)
            # Should not contain first 10 characters
            assert secret[:10] not in masked

    def test_realistic_sensitive_data(self):
        """Test mask_sensitive() with realistic sensitive data."""
        test_cases = {
            "dockerhub_token": "dckr_pat_1234567890abcdefghij",
            "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "jwt_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
            "api_key": "sk_live_51Hx1234567890",
        }

        for name, secret in test_cases.items():
            masked = mask_sensitive(secret)
            assert len(masked) == 7  # *** + 4 chars
            assert masked.startswith("***")


class TestSanitizePath:
    """Test suite for path traversal prevention."""

    def test_allows_valid_path_within_base(self):
        """Test sanitize_path() allows valid paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            user_path = "data/compose.yml"
            result = sanitize_path(user_path, base)

            assert result.is_relative_to(base)
            assert result.name == "compose.yml"

    def test_blocks_parent_directory_traversal(self):
        """Test sanitize_path() blocks ../ attacks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            with pytest.raises(ValueError) as exc_info:
                sanitize_path("../../etc/passwd", base)

            assert "Path traversal detected" in str(exc_info.value)

    def test_blocks_absolute_path_outside_base(self):
        """Test sanitize_path() blocks absolute paths outside base."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            with pytest.raises(ValueError) as exc_info:
                sanitize_path("/etc/passwd", base)

            assert "Path traversal detected" in str(exc_info.value)

    def test_blocks_symlink_escape(self):
        """Test sanitize_path() blocks symlink escapes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            # Create symlink pointing outside base
            link_path = base / "evil_link"
            link_path.symlink_to("/etc")

            with pytest.raises(ValueError) as exc_info:
                sanitize_path("evil_link", base, allow_symlinks=False)

            assert "Symbolic links not allowed" in str(exc_info.value)

    def test_allows_symlink_when_enabled(self):
        """Test sanitize_path() allows symlinks when configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            # Create symlink within base
            target = base / "target.txt"
            target.write_text("content")
            link = base / "link.txt"
            link.symlink_to(target)

            result = sanitize_path("link.txt", base, allow_symlinks=True)

            assert result.exists()

    def test_resolves_relative_paths(self):
        """Test sanitize_path() resolves ./ and ../ correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)
            (base / "subdir").mkdir()

            # This should be allowed (stays within base)
            result = sanitize_path("./subdir/../subdir/file.txt", base)

            assert result.is_relative_to(base)

    def test_raises_on_nonexistent_base(self):
        """Test sanitize_path() raises if base directory doesn't exist."""
        with pytest.raises(FileNotFoundError):
            sanitize_path("file.txt", "/nonexistent/base/directory")

    def test_handles_path_object_input(self):
        """Test sanitize_path() accepts Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            user_path = Path("data/file.txt")
            result = sanitize_path(user_path, base)

            assert isinstance(result, Path)
            assert result.is_relative_to(base)

    def test_blocks_null_byte_injection(self):
        """Test sanitize_path() handles null byte injection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            # Null byte can truncate path in some systems
            with pytest.raises((ValueError, OSError)):
                sanitize_path("safe.txt\\x00../../etc/passwd", base)


class TestIsSafeFilename:
    """Test suite for filename validation."""

    def test_allows_normal_filename(self):
        """Test is_safe_filename() allows normal filenames."""
        assert is_safe_filename("document.pdf") is True
        assert is_safe_filename("image_2024.png") is True
        assert is_safe_filename("my-file.txt") is True

    def test_blocks_path_separators(self):
        """Test is_safe_filename() blocks path separators."""
        assert is_safe_filename("../../../etc/passwd") is False
        assert is_safe_filename("subdir/file.txt") is False
        assert is_safe_filename("dir\\\\file.txt") is False

    def test_blocks_null_bytes(self):
        """Test is_safe_filename() blocks null bytes."""
        assert is_safe_filename("file\\x00.txt") is False

    def test_blocks_control_characters(self):
        """Test is_safe_filename() blocks control characters."""
        assert is_safe_filename("file\\n.txt") is False
        assert is_safe_filename("file\\r.txt") is False
        assert is_safe_filename("file\\t.txt") is False

    def test_allows_hidden_files_by_default(self):
        """Test is_safe_filename() allows hidden files."""
        assert is_safe_filename(".htaccess") is True
        assert is_safe_filename(".env") is True

    def test_blocks_hidden_files_when_configured(self):
        """Test is_safe_filename() blocks hidden files when configured."""
        assert is_safe_filename(".htaccess", allow_dots=False) is False
        assert is_safe_filename(".env", allow_dots=False) is False

    def test_blocks_special_directory_names(self):
        """Test is_safe_filename() blocks . and ..."""
        assert is_safe_filename(".") is False
        assert is_safe_filename("..") is False

    def test_blocks_empty_filename(self):
        """Test is_safe_filename() blocks empty filename."""
        assert is_safe_filename("") is False
        assert is_safe_filename(None) is False


class TestValidateContainerName:
    """Test suite for Docker container name validation."""

    def test_allows_valid_container_names(self):
        """Test validate_container_name() allows valid names."""
        valid_names = [
            "my-container",
            "container_1",
            "app-prod-v2",
            "nginx",
            "postgres-14",
        ]

        for name in valid_names:
            assert validate_container_name(name) == name

    def test_blocks_path_traversal_in_container_name(self):
        """Test validate_container_name() blocks path traversal."""
        with pytest.raises(ValueError):
            validate_container_name("../../etc")

    def test_blocks_invalid_characters(self):
        """Test validate_container_name() blocks invalid characters."""
        invalid_names = [
            "container;rm -rf /",
            "container && whoami",
            "container | cat /etc/passwd",
            "container`whoami`",
            "container$(whoami)",
        ]

        for name in invalid_names:
            with pytest.raises(ValueError):
                validate_container_name(name)

    def test_blocks_empty_name(self):
        """Test validate_container_name() blocks empty name."""
        with pytest.raises(ValueError) as exc_info:
            validate_container_name("")

        assert "cannot be empty" in str(exc_info.value)

    def test_requires_alphanumeric_start(self):
        """Test validate_container_name() requires alphanumeric first char."""
        # Docker names must start with [a-zA-Z0-9]
        with pytest.raises(ValueError):
            validate_container_name("-invalid-start")

        with pytest.raises(ValueError):
            validate_container_name("_invalid-start")

    def test_allows_alphanumeric_and_special_chars(self):
        """Test validate_container_name() allows alphanumeric, _, ., -."""
        assert validate_container_name("valid_name-123.test") == "valid_name-123.test"


class TestValidateImageName:
    """Test suite for Docker image name validation."""

    def test_allows_simple_image_names(self):
        """Test validate_image_name() allows simple names."""
        valid_images = [
            "nginx:latest",
            "postgres:14",
            "redis:alpine",
        ]

        for image in valid_images:
            assert validate_image_name(image) == image

    def test_allows_registry_prefixed_images(self):
        """Test validate_image_name() allows registry prefixes."""
        valid_images = [
            "ghcr.io/user/repo:v1.0.0",
            "docker.io/library/nginx:latest",
            "registry.example.com:5000/app:latest",
        ]

        for image in valid_images:
            assert validate_image_name(image) == image

    def test_allows_digest_references(self):
        """Test validate_image_name() allows @digest references."""
        image = "nginx@sha256:1234567890abcdef"
        assert validate_image_name(image) == image

    def test_blocks_path_traversal_in_image_name(self):
        """Test validate_image_name() blocks path traversal."""
        with pytest.raises(ValueError):
            validate_image_name("../../etc/passwd")

    def test_blocks_absolute_paths(self):
        """Test validate_image_name() blocks absolute paths."""
        with pytest.raises(ValueError):
            validate_image_name("/etc/passwd")

    def test_blocks_control_characters(self):
        """Test validate_image_name() blocks control characters."""
        with pytest.raises(ValueError):
            validate_image_name("nginx\\n:latest")

    def test_blocks_empty_name(self):
        """Test validate_image_name() blocks empty name."""
        with pytest.raises(ValueError):
            validate_image_name("")

    def test_blocks_invalid_format(self):
        """Test validate_image_name() blocks invalid formats."""
        invalid_images = [
            "nginx;rm -rf /",
            "nginx && whoami",
            "nginx | cat /etc/passwd",
        ]

        for image in invalid_images:
            with pytest.raises(ValueError):
                validate_image_name(image)


class TestSecurityIntegration:
    """Integration tests for security utilities working together."""

    def test_path_and_filename_validation_combined(self):
        """Test combining path and filename validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            base.mkdir(exist_ok=True)

            # Validate filename first
            filename = "config.yml"
            assert is_safe_filename(filename) is True

            # Then validate path
            full_path = sanitize_path(f"configs/{filename}", base)
            assert full_path.name == filename

    def test_log_sanitization_with_masked_data(self):
        """Test logging with both sanitization and masking."""
        api_key = "sk_live_1234567890abcdef"
        message = f"API key: {mask_sensitive(api_key)}"

        # Attacker tries to inject newlines
        malicious_message = message + "\\n[ERROR] Fake error"
        sanitized = sanitize_log_message(malicious_message)

        # No newlines, and API key is masked
        assert "\\n" not in sanitized
        assert "***cdef" in sanitized
        assert "sk_live_" not in sanitized

    def test_container_name_in_log_message(self):
        """Test validating container name before logging."""
        container_name = "my-app-v1"

        # Validate container name
        validated_name = validate_container_name(container_name)

        # Sanitize for logging
        log_message = f"Container {validated_name} started"
        sanitized = sanitize_log_message(log_message)

        assert sanitized == log_message
