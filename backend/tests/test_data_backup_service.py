"""Unit tests for the size cap and skip-prefix logic in data_backup_service.

These tests cover the pure helpers and ``_should_skip_mount`` only — the
``_measure_mount_size`` and ``_filter_oversized_mounts`` paths require a
live Docker daemon and are exercised by the integration suite.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import data_backup_service as dbs


@pytest.fixture
def service():
    """A DataBackupService with a mocked Docker client (no live daemon)."""
    with (
        patch("app.services.data_backup_service.make_docker_client", return_value=MagicMock()),
        patch(
            "app.services.data_backup_service.resolve_docker_url_sync",
            return_value="unix:///var/run/docker.sock",
        ),
    ):
        return dbs.DataBackupService()


@pytest.fixture(autouse=True)
def _clear_skip_cache():
    """Each test sees a fresh skip-prefix cache."""
    dbs._reset_skip_prefixes_cache()
    yield
    dbs._reset_skip_prefixes_cache()


def test_user_data_prefixes_default(monkeypatch):
    monkeypatch.delenv("TIDEWATCH_BACKUP_SKIP_PREFIXES", raising=False)
    assert dbs._env_user_data_prefixes() == dbs._DEFAULT_USER_DATA_PREFIXES


def test_user_data_prefixes_env_override():
    with patch.dict(
        "os.environ",
        {"TIDEWATCH_BACKUP_SKIP_PREFIXES": "/srv/raid0/www:/opt/data"},
    ):
        assert dbs._env_user_data_prefixes() == ("/srv/raid0/www", "/opt/data")


def test_user_data_prefixes_env_blank_falls_back_to_default():
    with patch.dict("os.environ", {"TIDEWATCH_BACKUP_SKIP_PREFIXES": "   "}):
        assert dbs._env_user_data_prefixes() == dbs._DEFAULT_USER_DATA_PREFIXES


def test_max_mount_size_default(monkeypatch):
    monkeypatch.delenv("TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB", raising=False)
    expected = int(dbs._DEFAULT_MAX_MOUNT_SIZE_GB * 1024 * 1024 * 1024)
    assert dbs._env_max_mount_size_bytes() == expected


def test_max_mount_size_env_override():
    with patch.dict("os.environ", {"TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB": "2.5"}):
        assert dbs._env_max_mount_size_bytes() == int(2.5 * 1024**3)


def test_max_mount_size_invalid_env_falls_back_to_default(caplog):
    with patch.dict("os.environ", {"TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB": "huge"}):
        with caplog.at_level("WARNING"):
            value = dbs._env_max_mount_size_bytes()
        expected = int(dbs._DEFAULT_MAX_MOUNT_SIZE_GB * 1024 * 1024 * 1024)
        assert value == expected
        assert any(
            "Invalid TIDEWATCH_BACKUP_MAX_MOUNT_SIZE_GB" in r.message for r in caplog.records
        )


def _seed_cache(*prefixes: str) -> None:
    """Populate the skip-prefix cache directly so tests don't hit mount_resolver."""
    dbs._skip_prefixes_cache = tuple(prefixes)


def test_should_skip_mount_drops_user_data_prefix():
    """A bind mount under /mnt is treated as user data and skipped."""
    _seed_cache(*dbs._STATIC_SKIP_PREFIXES, *dbs._DEFAULT_USER_DATA_PREFIXES)
    svc = dbs.DataBackupService.__new__(dbs.DataBackupService)
    skip, reason = svc._should_skip_mount(
        {
            "Type": "bind",
            "Source": "/mnt/media/TV",
            "Destination": "/tv",
            "RW": True,
            "Mode": "rw",
        }
    )
    assert skip is True
    assert "/mnt" in reason


def test_should_skip_mount_drops_media_prefix():
    _seed_cache(*dbs._STATIC_SKIP_PREFIXES, *dbs._DEFAULT_USER_DATA_PREFIXES)
    svc = dbs.DataBackupService.__new__(dbs.DataBackupService)
    skip, _ = svc._should_skip_mount(
        {
            "Type": "bind",
            "Source": "/media/usb",
            "Destination": "/data",
            "RW": True,
            "Mode": "rw",
        }
    )
    assert skip is True


def test_should_skip_mount_keeps_app_config_dir():
    """A normal app config bind mount is NOT skipped."""
    _seed_cache(*dbs._STATIC_SKIP_PREFIXES, *dbs._DEFAULT_USER_DATA_PREFIXES)
    svc = dbs.DataBackupService.__new__(dbs.DataBackupService)
    skip, _ = svc._should_skip_mount(
        {
            "Type": "bind",
            "Source": "/srv/raid0/docker/config/sonarr",
            "Destination": "/config",
            "RW": True,
            "Mode": "rw",
        }
    )
    assert skip is False


def test_should_skip_mount_env_override_wins():
    _seed_cache(*dbs._STATIC_SKIP_PREFIXES, "/srv/raid0/www")
    svc = dbs.DataBackupService.__new__(dbs.DataBackupService)
    # /mnt is no longer in the skip list — should pass through
    skip, _ = svc._should_skip_mount(
        {
            "Type": "bind",
            "Source": "/mnt/media/TV",
            "Destination": "/tv",
            "RW": True,
            "Mode": "rw",
        }
    )
    assert skip is False
    # /srv/raid0/www is in the skip list — should be filtered
    skip, _ = svc._should_skip_mount(
        {
            "Type": "bind",
            "Source": "/srv/raid0/www/static",
            "Destination": "/www",
            "RW": True,
            "Mode": "rw",
        }
    )
    assert skip is True


class TestTarFilename:
    """Synthetic, collision-free tar names (H1+#7 A)."""

    def test_path_independent(self):
        assert dbs._tar_filename("volume", 0) == "vol_000.tar.gz"
        assert dbs._tar_filename("bind", 12) == "bind_012.tar.gz"

    def test_no_collision(self):
        # Two mounts that the old destination-derived name could collapse now differ.
        assert dbs._tar_filename("bind", 0) != dbs._tar_filename("bind", 1)
        assert dbs._tar_filename("volume", 5) != dbs._tar_filename("bind", 5)


class TestGetPgUser:
    """POSTGRES_USER allowlist (H1+#7 D)."""

    def test_accepts_valid(self, service):
        info = {"Config": {"Env": ["POSTGRES_USER=myapp_user"]}}
        assert service._get_pg_user(info) == "myapp_user"

    def test_rejects_injection(self, service):
        info = {"Config": {"Env": ["POSTGRES_USER=postgres; rm -rf /"]}}
        assert service._get_pg_user(info) == "postgres"

    def test_rejects_metachars(self, service):
        info = {"Config": {"Env": ["POSTGRES_USER=$(whoami)"]}}
        assert service._get_pg_user(info) == "postgres"

    def test_default_when_absent(self, service):
        assert service._get_pg_user({"Config": {"Env": []}}) == "postgres"


def _ok_helper():
    helper = MagicMock()
    helper.wait = MagicMock(return_value={"StatusCode": 0})
    helper.remove = MagicMock()
    helper.logs = MagicMock(return_value=b"")
    return helper


class TestBackupArgv:
    """Backup helpers pass argv lists; a malicious container_name can only land
    in a trailing argv element, never in the static script (H1+#7 B)."""

    async def test_named_volume_uses_argv(self, service):
        service.client.containers.run = MagicMock(return_value=_ok_helper())
        await service._backup_named_volume("vol1", "/data", "evil;rm -rf /", "bk-1", 60, 0)
        command = service.client.containers.run.call_args.kwargs["command"]
        assert isinstance(command, list)
        assert command[:2] == ["sh", "-c"]
        assert "evil" not in command[2]
        assert any("evil" in str(a) for a in command[3:])

    async def test_bind_uses_argv(self, service):
        service.client.containers.run = MagicMock(return_value=_ok_helper())
        await service._backup_bind_mount("/src", "/data", "evil;rm -rf /", "bk-1", 60, 0)
        command = service.client.containers.run.call_args.kwargs["command"]
        assert isinstance(command, list)
        assert command[:2] == ["sh", "-c"]
        assert "evil" not in command[2]
        assert any("evil" in str(a) for a in command[3:])

    async def test_backup_postgresql_uses_argv(self, service, tmp_path):
        container = MagicMock()
        container.exec_run = MagicMock(return_value=(0, (b"DUMP DATA", b"")))
        await service._backup_postgresql(container, tmp_path, "myuser", 60)
        assert container.exec_run.call_args.args[0] == ["pg_dumpall", "-U", "myuser"]


class TestRestoreArgv:
    """Restore helper passes a static script + the tar path as a trailing argv
    element (H1+#7 C)."""

    async def test_restore_mount_uses_argv(self, service):
        service.client.containers.run = MagicMock(return_value=_ok_helper())
        await service._restore_mount(
            "vol_000.tar.gz", "volume", "/src", "vol1", "evil;rm -rf /", "bk-1"
        )
        command = service.client.containers.run.call_args.kwargs["command"]
        assert isinstance(command, list)
        assert command[:2] == ["sh", "-c"]
        assert "evil" not in command[2]
        assert any("evil" in str(a) for a in command[3:])


class TestRestorePostgresql:
    """psql restore via argv + metadata pg_user re-validation (H1+#7 D/E)."""

    async def test_rejects_bad_pg_user_in_metadata(self, service, tmp_path):
        (tmp_path / "pg_dumpall.sql").write_text("SQL")
        (tmp_path / "metadata.json").write_text(
            json.dumps({"pg_user": "bad; rm -rf /", "pg_version": "16"})
        )
        service.client.containers.get = MagicMock()
        with patch.object(service, "_get_backup_dir", return_value=tmp_path):
            result = await service.restore_postgresql("pg", "bk-1")
        assert result is False
        service.client.containers.get.assert_not_called()

    async def test_uses_psql_argv(self, service, tmp_path):
        (tmp_path / "pg_dumpall.sql").write_text("SQL")
        (tmp_path / "metadata.json").write_text(
            json.dumps({"pg_user": "myuser", "pg_version": "16"})
        )
        container = MagicMock()
        container.put_archive = MagicMock()
        container.exec_run = MagicMock(return_value=(0, (b"", b"")))
        service.client.containers.get = MagicMock(return_value=container)
        with (
            patch.object(service, "_get_backup_dir", return_value=tmp_path),
            patch.object(service, "_get_pg_version", new=AsyncMock(return_value="16")),
        ):
            result = await service.restore_postgresql("pg", "bk-1")
        assert result is True
        psql_calls = [
            c for c in container.exec_run.call_args_list if c.args and c.args[0][0] == "psql"
        ]
        assert psql_calls, "psql was not invoked via argv"
        assert psql_calls[0].args[0] == ["psql", "-U", "myuser", "-f", "/tmp/pg_dumpall.sql"]
