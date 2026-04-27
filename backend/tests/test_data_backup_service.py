"""Unit tests for the size cap and skip-prefix logic in data_backup_service.

These tests cover the pure helpers and ``_should_skip_mount`` only — the
``_measure_mount_size`` and ``_filter_oversized_mounts`` paths require a
live Docker daemon and are exercised by the integration suite.
"""

from unittest.mock import patch

import pytest

from app.services import data_backup_service as dbs


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
