"""Tests for Docker access centralization and proxy self-update.

Tests:
- Docker URL resolution (DB vs env)
- URL normalization
- Proxy detection (_is_docker_api_dependency)
- Proxy loss detection (_is_proxy_loss)
- Image ID capture
- Container monitor ConnectionError handling
- Scheduler ConnectionError handling
- Subprocess env injection
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
from app.services.update_engine import UpdateEngine


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


class TestIsDockerApiDependency:
    """Test proxy detection logic."""

    def test_tcp_matching_container_name(self):
        assert UpdateEngine._is_docker_api_dependency(
            "socket-proxy-rw", "socket-proxy-rw", "tcp://socket-proxy-rw:2375"
        )

    def test_tcp_matching_service_name(self):
        assert UpdateEngine._is_docker_api_dependency(
            "proxies-socket-proxy-rw-1", "socket-proxy-rw", "tcp://socket-proxy-rw:2375"
        )

    def test_tcp_no_match(self):
        assert not UpdateEngine._is_docker_api_dependency(
            "sonarr", "sonarr", "tcp://socket-proxy-rw:2375"
        )

    def test_unix_socket_always_false(self):
        """Local socket mode has no proxy to protect."""
        assert not UpdateEngine._is_docker_api_dependency(
            "socket-proxy-rw", "socket-proxy-rw", "unix:///var/run/docker.sock"
        )

    def test_invalid_url_returns_false(self):
        assert not UpdateEngine._is_docker_api_dependency("test", "test", "not-a-url")


class TestIsProxyLoss:
    """Test proxy-loss stderr pattern detection."""

    def test_connection_refused(self):
        assert UpdateEngine._is_proxy_loss("Error: connection refused")

    def test_name_resolution(self):
        assert UpdateEngine._is_proxy_loss("Name or service not known")

    def test_broken_pipe(self):
        assert UpdateEngine._is_proxy_loss("write: broken pipe")

    def test_connection_reset(self):
        assert UpdateEngine._is_proxy_loss("Connection reset by peer")

    def test_eof(self):
        assert UpdateEngine._is_proxy_loss("unexpected EOF")

    def test_normal_error_not_proxy_loss(self):
        """Permission denied is not a proxy loss."""
        assert not UpdateEngine._is_proxy_loss("permission denied")

    def test_image_not_found_not_proxy_loss(self):
        assert not UpdateEngine._is_proxy_loss("Error: image not found")

    def test_empty_stderr(self):
        assert not UpdateEngine._is_proxy_loss("")


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


class TestGetLocalImageId:
    """Test image ID capture before proxy update."""

    @pytest.mark.asyncio
    async def test_captures_image_id(self):
        """Should return the image ID from the local daemon."""
        mock_client = MagicMock()
        mock_img = MagicMock()
        mock_img.id = "sha256:abc123"
        mock_client.images.get.return_value = mock_img

        with patch(
            "app.services.update_engine.make_docker_client",
            return_value=mock_client,
        ):
            result = await UpdateEngine._get_local_image_id(
                "lscr.io/linuxserver/socket-proxy", "3.2.14", "tcp://proxy:2375"
            )

        assert result == "sha256:abc123"
        mock_client.images.get.assert_called_once_with("lscr.io/linuxserver/socket-proxy:3.2.14")

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        """Should return None if image lookup fails."""
        with patch(
            "app.services.update_engine.make_docker_client",
            side_effect=Exception("connection failed"),
        ):
            result = await UpdateEngine._get_local_image_id("test", "latest", "tcp://proxy:2375")

        assert result is None


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


class TestVerifyProxyUpdate:
    """Test _verify_proxy_update verification logic."""

    def _make_container(self):
        """Create a minimal Container model for verification tests."""
        return Container(
            id=1,
            name="socket-proxy-rw",
            image="lscr.io/linuxserver/socket-proxy",
            current_tag="3.2.14",
            registry="lscr.io",
            compose_file="/compose/proxies.yml",
            service_name="socket-proxy-rw",
        )

    def _mock_docker_container(self, image_id, status="running", repo_tags=None):
        """Create a mock Docker container with image info."""
        mock_container = MagicMock()
        mock_container.status = status
        mock_container.reload = MagicMock()
        mock_image = MagicMock()
        mock_image.id = image_id
        mock_image.attrs = {"RepoTags": repo_tags or []}
        mock_container.image = mock_image
        return mock_container

    @pytest.mark.asyncio
    async def test_verify_proxy_update_success(self):
        """Proxy responds, image ID matches → success."""
        container = self._make_container()
        mock_docker_container = self._mock_docker_container("sha256:abc123")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_docker_container

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200

        with (
            patch("app.services.update_engine.httpx.AsyncClient") as mock_httpx,
            patch(
                "app.services.update_engine.make_docker_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_engine.UpdateEngine._resolve_container_runtime_name",
                return_value="socket-proxy-rw",
            ),
            patch("app.services.container_monitor.container_monitor") as mock_monitor,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_monitor.reconnect = MagicMock()
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_http_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_async_client

            result = await UpdateEngine._verify_proxy_update(
                container, "sha256:abc123", "3.2.14", "tcp://socket-proxy-rw:2375", timeout=5
            )

        assert result["success"] is True
        assert result["image_id"] == "sha256:abc123"
        assert result["running"] is True

    @pytest.mark.asyncio
    async def test_verify_proxy_update_wrong_image(self):
        """Proxy responds but image ID doesn't match → failure."""
        container = self._make_container()
        mock_docker_container = self._mock_docker_container("sha256:wrong")
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_docker_container

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200

        with (
            patch("app.services.update_engine.httpx.AsyncClient") as mock_httpx,
            patch(
                "app.services.update_engine.make_docker_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_engine.UpdateEngine._resolve_container_runtime_name",
                return_value="socket-proxy-rw",
            ),
            patch("app.services.container_monitor.container_monitor") as mock_monitor,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_monitor.reconnect = MagicMock()
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_http_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_async_client

            result = await UpdateEngine._verify_proxy_update(
                container, "sha256:expected", "3.2.14", "tcp://socket-proxy-rw:2375", timeout=5
            )

        assert result["success"] is False
        assert "mismatch" in result["error"].lower()
        assert result["running"] is True

    @pytest.mark.asyncio
    async def test_verify_proxy_update_timeout(self):
        """Proxy never responds within timeout → failure."""
        container = self._make_container()

        with (
            patch("app.services.update_engine.httpx.AsyncClient") as mock_httpx,
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            # Simulate time always past timeout
            mock_loop.return_value.time.side_effect = [0, 0, 100, 100]
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(side_effect=ConnectionError("refused"))
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_async_client

            result = await UpdateEngine._verify_proxy_update(
                container, "sha256:abc", "3.2.14", "tcp://socket-proxy-rw:2375", timeout=1
            )

        assert result["success"] is False
        assert "did not respond" in result["error"].lower()
        assert result["running"] is False

    @pytest.mark.asyncio
    async def test_verify_proxy_update_no_expected_id_match(self):
        """No expected_image_id, but RepoTags match → success."""
        container = self._make_container()
        mock_docker_container = self._mock_docker_container(
            "sha256:abc123",
            repo_tags=["lscr.io/linuxserver/socket-proxy:3.2.14"],
        )
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_docker_container

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200

        with (
            patch("app.services.update_engine.httpx.AsyncClient") as mock_httpx,
            patch(
                "app.services.update_engine.make_docker_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_engine.UpdateEngine._resolve_container_runtime_name",
                return_value="socket-proxy-rw",
            ),
            patch("app.services.container_monitor.container_monitor") as mock_monitor,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_monitor.reconnect = MagicMock()
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_http_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_async_client

            result = await UpdateEngine._verify_proxy_update(
                container, None, "3.2.14", "tcp://socket-proxy-rw:2375", timeout=5
            )

        assert result["success"] is True
        assert result["image_id"] == "sha256:abc123"
        assert "warning" not in result

    @pytest.mark.asyncio
    async def test_verify_proxy_update_no_expected_id_mismatch(self):
        """No expected_image_id and RepoTags don't match → permissive success with warning."""
        container = self._make_container()
        mock_docker_container = self._mock_docker_container(
            "sha256:abc123",
            repo_tags=["lscr.io/linuxserver/socket-proxy:3.2.13"],  # Old tag
        )
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_docker_container

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200

        with (
            patch("app.services.update_engine.httpx.AsyncClient") as mock_httpx,
            patch(
                "app.services.update_engine.make_docker_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_engine.UpdateEngine._resolve_container_runtime_name",
                return_value="socket-proxy-rw",
            ),
            patch("app.services.container_monitor.container_monitor") as mock_monitor,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_monitor.reconnect = MagicMock()
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_http_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_async_client

            result = await UpdateEngine._verify_proxy_update(
                container, None, "3.2.14", "tcp://socket-proxy-rw:2375", timeout=5
            )

        # Permissive: container is running, accept with warning
        assert result["success"] is True
        assert result["image_id"] == "sha256:abc123"
        assert "warning" in result


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
