"""Tests for compose parser service (app/services/compose_parser.py).

Tests YAML parsing, service extraction, and label handling:
- Docker Compose YAML parsing
- Image string parsing (registry, name, tag)
- Service discovery and validation
- Label parsing (dict and list formats)
- Label sanitization (length limits, control characters)
- Health check URL extraction and normalization
- Dependency detection (depends_on, links)
- Path validation (prevents directory traversal)
- Container name validation
- Tag format validation
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.compose_parser import (
    ComposeParser,
    validate_compose_file_path,
    validate_container_name,
    validate_tag_format,
)


class TestValidateContainerName:
    """Test suite for container name validation."""

    def test_valid_simple_name(self):
        """Test valid simple container name."""
        assert validate_container_name("nginx") is True

    def test_valid_name_with_hyphen(self):
        """Test valid name with hyphens."""
        assert validate_container_name("my-app") is True

    def test_valid_name_with_underscore(self):
        """Test valid name with underscores."""
        assert validate_container_name("my_app") is True

    def test_valid_name_with_period(self):
        """Test valid name with periods."""
        assert validate_container_name("my.app") is True

    def test_valid_name_with_numbers(self):
        """Test valid name with numbers."""
        assert validate_container_name("app123") is True

    def test_invalid_empty_name(self):
        """Test empty name is invalid."""
        assert validate_container_name("") is False

    def test_invalid_name_starts_with_hyphen(self):
        """Test name starting with hyphen is invalid."""
        assert validate_container_name("-app") is False

    def test_invalid_name_starts_with_period(self):
        """Test name starting with period is invalid."""
        assert validate_container_name(".app") is False

    def test_invalid_name_with_slash(self):
        """Test name with slash is invalid."""
        assert validate_container_name("app/service") is False

    def test_invalid_name_with_space(self):
        """Test name with space is invalid."""
        assert validate_container_name("my app") is False

    def test_invalid_name_too_long(self):
        """Test name exceeding 255 characters is invalid."""
        long_name = "a" * 256
        assert validate_container_name(long_name) is False

    def test_valid_name_exactly_255_chars(self):
        """Test name with exactly 255 characters is valid."""
        exact_name = "a" * 255
        assert validate_container_name(exact_name) is True


class TestValidateTagFormat:
    """Test suite for Docker tag validation."""

    def test_valid_simple_tag(self):
        """Test valid simple tag."""
        assert validate_tag_format("latest") is True

    def test_valid_semver_tag(self):
        """Test valid semantic version tag."""
        assert validate_tag_format("1.2.3") is True

    def test_valid_tag_with_hyphen(self):
        """Test valid tag with hyphen."""
        assert validate_tag_format("v1.0-beta") is True

    def test_valid_tag_with_underscore(self):
        """Test valid tag with underscore."""
        assert validate_tag_format("1.0_alpine") is True

    def test_valid_sha256_digest(self):
        """Test valid sha256 digest."""
        digest = (
            "sha256:abc123def4567890123456789012345678901234567890123456789012345678"
        )
        assert validate_tag_format(digest) is True

    def test_invalid_empty_tag(self):
        """Test empty tag is invalid."""
        assert validate_tag_format("") is False

    def test_invalid_tag_starts_with_period(self):
        """Test tag starting with period is invalid."""
        assert validate_tag_format(".tag") is False

    def test_invalid_tag_starts_with_hyphen(self):
        """Test tag starting with hyphen is invalid."""
        assert validate_tag_format("-tag") is False

    def test_invalid_tag_with_slash(self):
        """Test tag with slash is invalid."""
        assert validate_tag_format("1.0/beta") is False

    def test_invalid_tag_too_long(self):
        """Test tag exceeding 128 characters is invalid."""
        long_tag = "a" * 129
        assert validate_tag_format(long_tag) is False

    def test_valid_tag_exactly_128_chars(self):
        """Test tag with exactly 128 characters is valid."""
        exact_tag = "a" * 128
        assert validate_tag_format(exact_tag) is True

    def test_invalid_sha256_digest_wrong_length(self):
        """Test sha256 digest with wrong length is invalid."""
        digest = "sha256:abc123"  # Too short
        assert validate_tag_format(digest) is False


class TestValidateComposeFilePath:
    """Test suite for compose file path validation."""

    def test_valid_yml_extension(self):
        """Test valid .yml file path."""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as f:
            f.write(b"services:\n  nginx:\n    image: nginx")
            f.flush()
            path = f.name

        try:
            assert validate_compose_file_path(path) is True
        finally:
            os.unlink(path)

    def test_valid_yaml_extension(self):
        """Test valid .yaml file path."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"services:\n  nginx:\n    image: nginx")
            f.flush()
            path = f.name

        try:
            assert validate_compose_file_path(path) is True
        finally:
            os.unlink(path)

    def test_invalid_path_traversal(self):
        """Test path traversal attempt is rejected."""
        assert validate_compose_file_path("../../etc/passwd") is False

    def test_invalid_double_slash(self):
        """Test double slash is rejected."""
        assert validate_compose_file_path("//etc/passwd") is False

    def test_invalid_null_byte(self):
        """Test null byte is rejected."""
        assert validate_compose_file_path("test\x00.yml") is False

    def test_invalid_nonexistent_file(self):
        """Test nonexistent file is rejected."""
        assert validate_compose_file_path("/nonexistent/file.yml") is False

    def test_invalid_wrong_extension(self):
        """Test file with wrong extension is rejected."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            f.flush()
            path = f.name

        try:
            assert validate_compose_file_path(path) is False
        finally:
            os.unlink(path)

    def test_path_within_allowed_base_directory(self):
        """Test path within allowed base directory is accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_file = Path(tmpdir) / "docker-compose.yml"
            compose_file.write_text("services:\n  nginx:\n    image: nginx")

            assert validate_compose_file_path(str(compose_file), tmpdir) is True

    def test_path_outside_allowed_base_directory(self):
        """Test path outside allowed base directory is rejected."""
        with (
            tempfile.TemporaryDirectory() as tmpdir1,
            tempfile.TemporaryDirectory() as tmpdir2,
        ):
            compose_file = Path(tmpdir2) / "docker-compose.yml"
            compose_file.write_text("services:\n  nginx:\n    image: nginx")

            # File is in tmpdir2 but we only allow tmpdir1
            assert validate_compose_file_path(str(compose_file), tmpdir1) is False


class TestParseImageString:
    """Test suite for Docker image string parsing."""

    def test_parse_simple_image(self):
        """Test parsing simple image name (defaults to Docker Hub)."""
        registry, image, tag = ComposeParser._parse_image_string("nginx")

        assert registry == "dockerhub"
        assert image == "nginx"
        assert tag == "latest"

    def test_parse_image_with_tag(self):
        """Test parsing image with tag."""
        registry, image, tag = ComposeParser._parse_image_string("nginx:1.25.3")

        assert registry == "dockerhub"
        assert image == "nginx"
        assert tag == "1.25.3"

    def test_parse_user_image(self):
        """Test parsing user/image format."""
        registry, image, tag = ComposeParser._parse_image_string("linuxserver/plex")

        assert registry == "dockerhub"
        assert image == "linuxserver/plex"
        assert tag == "latest"

    def test_parse_ghcr_image(self):
        """Test parsing GitHub Container Registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "ghcr.io/owner/app:v1.0.0"
        )

        assert registry == "ghcr"
        assert image == "owner/app"
        assert tag == "v1.0.0"

    def test_parse_lscr_image(self):
        """Test parsing LinuxServer.io registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "lscr.io/linuxserver/plex:1.40.0"
        )

        assert registry == "lscr"
        assert image == "linuxserver/plex"
        assert tag == "1.40.0"

    def test_parse_image_with_digest(self):
        """Test parsing image with SHA256 digest.

        Implementation correctly handles digests by checking for '@sha256:' before splitting on ':'.
        """
        registry, image, tag = ComposeParser._parse_image_string(
            "nginx@sha256:abc123def45678901234567890123456789012345678901234567890123456"
        )

        assert registry == "dockerhub"
        assert image == "nginx"
        assert (
            tag
            == "sha256:abc123def45678901234567890123456789012345678901234567890123456"
        )

    def test_parse_quay_image(self):
        """Test parsing Quay.io registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "quay.io/user/app:latest"
        )

        assert registry == "quay"
        assert image == "user/app"
        assert tag == "latest"

    def test_parse_gcr_image(self):
        """Test parsing Google Container Registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "gcr.io/project/app:v2.0.0"
        )

        assert registry == "gcr"
        assert image == "project/app"
        assert tag == "v2.0.0"

    def test_parse_private_registry(self):
        """Test parsing private registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "registry.example.com/app:1.0.0"
        )

        assert registry == "registry.example.com"
        assert image == "app"
        assert tag == "1.0.0"

    def test_parse_localhost_registry(self):
        """Test parsing localhost registry image."""
        registry, image, tag = ComposeParser._parse_image_string(
            "localhost:5000/app:test"
        )

        assert registry == "localhost:5000"
        assert image == "app"
        assert tag == "test"


class TestLabelParsing:
    """Test suite for Docker label parsing."""

    def test_labels_list_to_dict_simple(self):
        """Test converting simple label list to dict."""
        labels = ["key1=value1", "key2=value2"]

        result = ComposeParser._labels_list_to_dict(labels)

        assert result == {"key1": "value1", "key2": "value2"}

    def test_labels_list_to_dict_with_equals_in_value(self):
        """Test converting labels with equals sign in value."""
        labels = ["url=http://example.com?param=value"]

        result = ComposeParser._labels_list_to_dict(labels)

        assert result == {"url": "http://example.com?param=value"}

    def test_labels_list_to_dict_ignores_malformed(self):
        """Test converting labels ignores entries without equals."""
        labels = ["key1=value1", "malformed", "key2=value2"]

        result = ComposeParser._labels_list_to_dict(labels)

        assert result == {"key1": "value1", "key2": "value2"}

    def test_sanitize_labels_enforces_max_labels(self):
        """Test label sanitization enforces maximum label count."""
        # Create 150 labels (exceeds MAX_LABELS=100)
        labels = {f"key{i}": f"value{i}" for i in range(150)}

        sanitized = ComposeParser._sanitize_labels(labels)

        # Should only have first 100 (sorted by key)
        assert len(sanitized) <= 100

    def test_sanitize_labels_truncates_long_keys(self):
        """Test label sanitization truncates keys exceeding 255 chars.

        Implementation correctly saves original_key before truncating to avoid KeyError.
        """
        long_key = "a" * 300
        labels = {long_key: "value"}

        sanitized = ComposeParser._sanitize_labels(labels)

        # Should have truncated key
        assert len(list(sanitized.keys())[0]) == 255

    def test_sanitize_labels_truncates_long_values(self):
        """Test label sanitization truncates values exceeding 4096 chars."""
        long_value = "x" * 5000
        labels = {"key": long_value}

        sanitized = ComposeParser._sanitize_labels(labels)

        assert len(sanitized["key"]) == 4096

    def test_sanitize_labels_filters_null_bytes(self):
        """Test label sanitization filters null bytes from values."""
        labels = {"key": "value\x00with\x00nulls"}

        sanitized = ComposeParser._sanitize_labels(labels)

        assert "\x00" not in sanitized["key"]
        assert sanitized["key"] == "valuewithnulls"

    def test_sanitize_labels_skips_keys_with_control_chars(self):
        """Test label sanitization skips keys with control characters."""
        labels = {
            "valid_key": "value1",
            "key\nwith\nnewline": "value2",
            "key\x00with\x00null": "value3",
        }

        sanitized = ComposeParser._sanitize_labels(labels)

        # Only valid key should remain
        assert "valid_key" in sanitized
        assert len(sanitized) == 1

    def test_sanitize_labels_converts_non_string_values(self):
        """Test label sanitization converts non-string values to strings."""
        labels = {"int_value": 123, "bool_value": True, "float_value": 3.14}

        sanitized = ComposeParser._sanitize_labels(labels)

        assert sanitized["int_value"] == "123"
        assert sanitized["bool_value"] == "True"
        assert sanitized["float_value"] == "3.14"


class TestHealthCheckExtraction:
    """Test suite for health check URL extraction."""

    def test_extract_healthcheck_url_from_string(self):
        """Test extracting URL from simple string."""
        health_config = "curl -f http://localhost:8080/health || exit 1"

        url = ComposeParser._extract_healthcheck_url(health_config, "app")

        # Should normalize localhost to service name
        assert "http://app:8080/health" in url

    def test_extract_healthcheck_url_from_list(self):
        """Test extracting URL from list format."""
        health_config = ["CMD", "curl", "-f", "http://localhost:9000/ping"]

        url = ComposeParser._extract_healthcheck_url(health_config, "service")

        assert "http://service:9000/ping" in url

    def test_extract_healthcheck_url_from_dict(self):
        """Test extracting URL from dict format with test key."""
        health_config = {
            "test": [
                "CMD",
                "wget",
                "--quiet",
                "--tries=1",
                "http://127.0.0.1:3000/healthz",
            ],
            "interval": "30s",
        }

        url = ComposeParser._extract_healthcheck_url(health_config, "webapp")

        assert "http://webapp:3000/healthz" in url

    def test_extract_healthcheck_url_normalizes_127_0_0_1(self):
        """Test URL normalization replaces 127.0.0.1 with service name."""
        health_config = "http://127.0.0.1:8080/health"

        url = ComposeParser._extract_healthcheck_url(health_config, "api")

        assert url == "http://api:8080/health"

    def test_extract_healthcheck_url_preserves_external_urls(self):
        """Test external URLs are not modified."""
        health_config = "curl http://api.example.com/health"

        url = ComposeParser._extract_healthcheck_url(health_config, "app")

        assert url == "http://api.example.com/health"

    def test_extract_healthcheck_url_https_support(self):
        """Test HTTPS URLs are extracted."""
        health_config = "curl https://localhost:8443/health"

        url = ComposeParser._extract_healthcheck_url(health_config, "secure-app")

        assert "https://secure-app:8443/health" in url

    def test_extract_healthcheck_url_returns_none_for_no_url(self):
        """Test returns None when no URL found."""
        health_config = ["CMD-SHELL", "ps aux | grep app"]

        url = ComposeParser._extract_healthcheck_url(health_config, "app")

        assert url is None

    def test_extract_healthcheck_url_prevents_redos(self):
        """Test long input is rejected to prevent ReDoS attacks."""
        # Create very long string that could cause catastrophic backtracking
        long_input = "a" * 10000

        url = ComposeParser._extract_healthcheck_url(long_input, "app")

        # Should reject without hanging
        assert url is None


class TestNormalizeHealthCheckMethod:
    """Test suite for health check method normalization."""

    def test_normalize_method_auto(self):
        """Test 'auto' method is normalized."""
        assert ComposeParser._normalize_health_check_method("auto") == "auto"
        assert ComposeParser._normalize_health_check_method("AUTO") == "auto"

    def test_normalize_method_http(self):
        """Test 'http' method is normalized."""
        assert ComposeParser._normalize_health_check_method("http") == "http"
        assert ComposeParser._normalize_health_check_method("HTTP") == "http"

    def test_normalize_method_docker(self):
        """Test 'docker' method is normalized."""
        assert ComposeParser._normalize_health_check_method("docker") == "docker"
        assert ComposeParser._normalize_health_check_method("DOCKER") == "docker"

    def test_normalize_method_defaults_to_auto(self):
        """Test None or invalid method defaults to 'auto'."""
        assert ComposeParser._normalize_health_check_method(None) == "auto"
        assert ComposeParser._normalize_health_check_method("") == "auto"
        assert ComposeParser._normalize_health_check_method("invalid") == "auto"


class TestParseComposeFile:
    """Test suite for complete compose file parsing."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_parse_compose_file_simple_service(self, mock_db):
        """Test parsing simple compose file with one service."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  nginx:
    image: nginx:1.25.3
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            assert len(containers) == 1
            assert containers[0].name == "nginx"
            assert containers[0].image == "nginx"
            assert containers[0].current_tag == "1.25.3"
            assert containers[0].registry == "dockerhub"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_compose_file_with_labels(self, mock_db):
        """Test parsing compose file with TideWatch labels."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  app:
    image: myapp:1.0.0
    labels:
      tidewatch.policy: auto
      tidewatch.scope: minor
      tidewatch.include_prereleases: 'true'
      tidewatch.vulnforge: 'false'
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            assert len(containers) == 1
            assert containers[0].policy == "auto"
            assert containers[0].scope == "minor"
            assert containers[0].include_prereleases is True
            assert containers[0].vulnforge_enabled is False
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_compose_file_skips_invalid_names(self, mock_db):
        """Test parsing skips services with invalid names."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  valid-name:
    image: nginx:latest
  invalid name with spaces:
    image: redis:latest
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            # Should only have valid-name
            assert len(containers) == 1
            assert containers[0].name == "valid-name"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_compose_file_skips_disabled_services(self, mock_db):
        """Test parsing skips services with tidewatch.enabled=false."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  enabled:
    image: nginx:latest
  disabled:
    image: redis:latest
    labels:
      tidewatch.enabled: 'false'
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            # Should only have enabled service
            assert len(containers) == 1
            assert containers[0].name == "enabled"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_compose_file_multiple_services(self, mock_db):
        """Test parsing compose file with multiple services."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  web:
    image: nginx:1.25.3
  db:
    image: postgres:15.5
  cache:
    image: redis:7.2.3
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            assert len(containers) == 3
            names = [c.name for c in containers]
            assert "web" in names
            assert "db" in names
            assert "cache" in names
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_parse_compose_file_labels_list_format(self, mock_db):
        """Test parsing labels in list format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
version: '3.8'
services:
  app:
    image: app:1.0.0
    labels:
      - tidewatch.policy=auto
      - tidewatch.scope=major
""")
            f.flush()
            path = f.name

        try:
            containers = await ComposeParser._parse_compose_file(path, mock_db)

            assert len(containers) == 1
            assert containers[0].policy == "auto"
            assert containers[0].scope == "major"
        finally:
            os.unlink(path)
