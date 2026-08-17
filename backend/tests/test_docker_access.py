"""Tests for Docker access centralization.

Tests:
- Docker URL resolution (DB vs env)
- URL normalization
- Subprocess env injection
- Container monitor ConnectionError handling
- Scheduler ConnectionError handling
- Scanner ConnectionError handling
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.models.container import Container
from app.services.docker_access import (
    _normalize_url,
    docker_subprocess_env,
    resolve_docker_url,
    resolve_docker_url_sync,
)


class TestResolveDockerUrl:
    """Test Docker URL resolution helpers."""

    @pytest.mark.asyncio
    async def test_resolve_from_db_setting(self):
        """DB docker_socket setting takes precedence over env."""
        mock_db = AsyncMock()
        with patch("app.services.settings_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value="tcp://proxy:2375")
            result = await resolve_docker_url(mock_db)
        assert result == "tcp://proxy:2375"

    @pytest.mark.asyncio
    async def test_resolve_env_fallback_when_db_empty(self):
        """Falls back to DOCKER_HOST when DB setting is empty."""
        mock_db = AsyncMock()
        with (
            patch("app.services.settings_service.SettingsService") as mock_settings,
            patch.dict(os.environ, {"DOCKER_HOST": "tcp://env-host:2375"}),
        ):
            mock_settings.get = AsyncMock(return_value=None)
            result = await resolve_docker_url(mock_db)
        assert result == "tcp://env-host:2375"

    @pytest.mark.asyncio
    async def test_resolve_env_fallback_when_no_db(self):
        """Falls back to DOCKER_HOST when no db provided."""
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://env-host:2375"}):
            result = await resolve_docker_url(None)
        assert result == "tcp://env-host:2375"

    @pytest.mark.asyncio
    async def test_resolve_defaults_to_unix_socket(self):
        """Defaults to unix socket when nothing configured."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove DOCKER_HOST if present
            env = os.environ.copy()
            env.pop("DOCKER_HOST", None)
            with patch.dict(os.environ, env, clear=True):
                result = await resolve_docker_url(None)
        assert result == "unix:///var/run/docker.sock"

    def test_sync_reads_env(self):
        """Sync variant reads DOCKER_HOST env."""
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://sync:2375"}):
            result = resolve_docker_url_sync()
        assert result == "tcp://sync:2375"


class TestNormalizeUrl:
    """Test URL normalization."""

    def test_tcp_url_unchanged(self):
        assert _normalize_url("tcp://host:2375") == "tcp://host:2375"

    def test_unix_url_unchanged(self):
        assert _normalize_url("unix:///var/run/docker.sock") == "unix:///var/run/docker.sock"

    def test_bare_path_gets_unix_prefix(self):
        assert _normalize_url("/var/run/docker.sock") == "unix:///var/run/docker.sock"


class TestDockerSubprocessEnv:
    """Test subprocess env builder."""

    def test_sets_docker_host(self):
        env = docker_subprocess_env("tcp://proxy:2375")
        assert env["DOCKER_HOST"] == "tcp://proxy:2375"

    def test_no_base_url_inherits_env(self):
        env = docker_subprocess_env(None)
        # Should have same keys as os.environ (at minimum)
        assert "PATH" in env

    def test_does_not_mutate_os_environ(self):
        original = os.environ.get("DOCKER_HOST")
        docker_subprocess_env("tcp://test:1234")
        assert os.environ.get("DOCKER_HOST") == original


class TestContainerMonitorConnectionError:
    """Test that ContainerMonitor handles ConnectionError gracefully."""

    @pytest.mark.asyncio
    async def test_connection_error_returns_degraded(self):
        """ConnectionError should return degraded state, not crash."""
        from app.services.container_monitor import ContainerMonitorService

        monitor = ContainerMonitorService.__new__(ContainerMonitorService)
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = RequestsConnectionError("Connection refused")
        monitor.client = mock_client

        result = await monitor.get_container_state("test-container")

        assert result is not None
        assert result["running"] is False
        assert "Connection refused" in result["error"]
        # A degraded daemon is not evidence the container is gone; recreating
        # on a transient proxy blip would be destructive.
        assert result.get("missing", False) is False

    @pytest.mark.asyncio
    async def test_missing_container_is_flagged_missing(self):
        """A removed container must be distinguishable from a stopped one.

        Both are `running: False`, but only one can be fixed by `compose
        restart`. Collapsing them cost 23 hours of downtime on a deleted
        `glances`: NotFound was swallowed into a dict with no `exit_code`, the
        scheduler read `exit_code=None`, decided "no_exit_code -> do not
        retry", and logged that the container "exited with code None" 2,507
        times without ever reporting that it did not exist.
        """
        from docker.errors import NotFound

        from app.services.container_monitor import ContainerMonitorService

        monitor = ContainerMonitorService.__new__(ContainerMonitorService)
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = NotFound("no such container")
        monitor.client = mock_client

        result = await monitor.get_container_state("glances")

        assert result is not None
        assert result["missing"] is True
        assert result["running"] is False

    @pytest.mark.asyncio
    async def test_stopped_container_is_not_flagged_missing(self):
        """Contrast: a container that exists but exited is NOT missing."""
        from app.services.container_monitor import ContainerMonitorService

        monitor = ContainerMonitorService.__new__(ContainerMonitorService)
        container = MagicMock()
        container.attrs = {"State": {"Status": "exited", "Running": False, "ExitCode": 127}}
        container.reload = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.return_value = container
        monitor.client = mock_client

        result = await monitor.get_container_state("glances")

        assert result is not None
        assert result.get("missing", False) is False
        assert result["exit_code"] == 127

    @pytest.mark.asyncio
    async def test_missing_container_is_retryable(self):
        """The classifier, not its caller, owns this: a removed container has no
        exit code, and reading the absent code as None yields "no_exit_code ->
        do not retry", which strands it forever. It is recoverable via
        `compose up`, so it must classify as retryable."""
        from app.services.container_monitor import ContainerMonitorService

        assert await ContainerMonitorService.should_retry_restart(None, False, missing=True) == (
            True,
            "container_missing",
        )

    @pytest.mark.asyncio
    async def test_absent_exit_code_alone_is_still_not_retryable(self):
        """Contrast: no exit code and not missing stays non-retryable."""
        from app.services.container_monitor import ContainerMonitorService

        assert await ContainerMonitorService.should_retry_restart(None, False) == (
            False,
            "no_exit_code",
        )

    def test_reconnect_creates_new_client(self):
        """reconnect() should create a fresh Docker client."""
        from app.services.container_monitor import ContainerMonitorService

        monitor = ContainerMonitorService.__new__(ContainerMonitorService)
        old_client = MagicMock()
        monitor.client = old_client

        with patch("app.services.container_monitor.make_docker_client") as mock_make:
            mock_make.return_value = MagicMock()
            monitor.reconnect()

        old_client.close.assert_called_once()
        mock_make.assert_called_once()
        assert monitor.client is not old_client


class TestSchedulerExceptionHandling:
    """Test that scheduler methods handle Docker connection errors."""

    @pytest.mark.asyncio
    async def test_monitor_loop_catches_connection_error(self):
        """_monitor_loop should not crash on ConnectionError."""
        from app.services.restart_scheduler import RestartSchedulerService

        scheduler = RestartSchedulerService.__new__(RestartSchedulerService)

        mock_db = AsyncMock()
        mock_container = MagicMock(spec=Container)
        mock_container.auto_restart_enabled = True

        # Mock the session and query to return our container
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_container]
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Make _check_and_schedule_restart raise ConnectionError
        scheduler._check_and_schedule_restart = AsyncMock(
            side_effect=RequestsConnectionError("proxy down")
        )

        with patch("app.services.restart_scheduler.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await scheduler._monitor_loop()


class TestScannerConnectionError:
    """Test HttpServerScanner handles ConnectionError gracefully."""

    @pytest.mark.asyncio
    async def test_scanner_connection_error_returns_empty(self):
        """ConnectionError from docker_client.containers.get → returns [] without raising."""
        from app.services.http_server_scanner import HttpServerScanner

        scanner = HttpServerScanner.__new__(HttpServerScanner)
        scanner.timeout = MagicMock()
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = RequestsConnectionError("proxy down")
        scanner.docker_client = mock_client

        result = await scanner.scan_container_http_servers("test-container")

        assert result == []
