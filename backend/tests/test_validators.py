"""Tests for validation utilities."""

import pytest
from app.utils.validators import (
    validate_container_name,
    validate_service_name,
    validate_compose_file_path,
    validate_docker_compose_command,
    ValidationError,
)


class TestContainerNameValidation:
    """Tests for container name validation."""

    def test_valid_container_names(self):
        """Test valid container names are accepted."""
        valid_names = [
            "test-container",
            "my_service",
            "app123",
            "frontend-prod",
            "api.service",
        ]
        for name in valid_names:
            result = validate_container_name(name)
            assert result == name

    def test_invalid_container_names(self):
        """Test invalid container names are rejected."""
        invalid_names = [
            "",  # Empty
            "a" * 300,  # Too long
            "test container",  # Space
            "test;rm -rf /",  # Command injection attempt
            "test&&whoami",  # Command chaining
            "test|cat /etc/passwd",  # Pipe
            "test`whoami`",  # Command substitution
            "test$(whoami)",  # Command substitution
            "../../../etc/passwd",  # Path traversal
        ]
        for name in invalid_names:
            with pytest.raises(ValidationError):
                validate_container_name(name)


class TestServiceNameValidation:
    """Tests for service name validation."""

    def test_valid_service_names(self):
        """Test valid service names are accepted."""
        valid_names = [
            "web-service",
            "api_backend",
            "database1",
        ]
        for name in valid_names:
            result = validate_service_name(name)
            assert result == name

    def test_invalid_service_names(self):
        """Test invalid service names are rejected."""
        with pytest.raises(ValidationError):
            validate_service_name("test;whoami")


class TestComposeFilePathValidation:
    """Tests for compose file path validation."""

    def test_valid_compose_paths(self):
        """Test valid compose file paths are accepted."""
        valid_paths = [
            "/compose/app.yml",
            "/compose/subdir/docker-compose.yml",
            "/compose/project/compose.yaml",
        ]
        for path in valid_paths:
            result = validate_compose_file_path(
                path, allowed_base="/compose", strict=False
            )
            assert str(result).startswith("/compose/")

    def test_path_traversal_attempts(self):
        """Test path traversal attempts are rejected."""
        traversal_attempts = [
            "/compose/../../../etc/passwd",
            "/compose/../../root/.ssh/id_rsa",
            "/../etc/passwd",
            "/compose/subdir/../../etc/hosts",
        ]
        for path in traversal_attempts:
            with pytest.raises(ValidationError):
                validate_compose_file_path(path, allowed_base="/compose", strict=False)

    def test_absolute_path_outside_base(self):
        """Test absolute paths outside allowed base are rejected."""
        with pytest.raises(ValidationError):
            validate_compose_file_path("/etc/passwd", allowed_base="/compose")

    def test_symlink_escape(self):
        """Test symlink escapes are rejected (if they resolve outside base)."""
        # This would need actual symlinks to test properly
        # For now, just verify that non-existent files raise errors with strict=True
        with pytest.raises(ValidationError):
            validate_compose_file_path(
                "/compose/nonexistent.yml", allowed_base="/compose", strict=True
            )


class TestDockerComposeCommandValidation:
    """Tests for docker compose command validation."""

    def test_valid_docker_compose_commands(self):
        """Test valid docker compose commands are accepted."""
        valid_commands = [
            "docker compose",
            "docker-compose",
            "/usr/bin/docker compose",
            "/usr/local/bin/docker-compose",
        ]
        for cmd in valid_commands:
            result = validate_docker_compose_command(cmd)
            assert isinstance(result, list)
            assert len(result) > 0

    def test_command_injection_attempts(self):
        """Test command injection attempts are rejected."""
        injection_attempts = [
            "docker compose; rm -rf /",
            "docker compose && whoami",
            "docker compose | cat /etc/passwd",
            "docker compose `whoami`",
            "docker compose $(cat /etc/passwd)",
        ]
        for cmd in injection_attempts:
            with pytest.raises(ValidationError):
                validate_docker_compose_command(cmd)

    def test_invalid_commands(self):
        """Test invalid commands are rejected."""
        invalid_commands = [
            "",  # Empty
            "   ",  # Only whitespace
            "not-docker-compose",  # Doesn't contain docker
            "docker exec",  # Wrong docker command
        ]
        for cmd in invalid_commands:
            with pytest.raises(ValidationError):
                validate_docker_compose_command(cmd)
