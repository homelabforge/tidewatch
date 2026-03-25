"""Tests for mount_resolver — auto-detection of host paths from container mounts."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.mount_resolver import (
    get_all_host_mount_sources,
    get_host_path,
    reset_cache,
    translate_container_to_host,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure mount resolver cache is fresh for every test."""
    reset_cache()
    yield
    reset_cache()


SAMPLE_MOUNTS = [
    {"Source": "/mnt/stacks", "Destination": "/compose"},
    {"Source": "/mnt/projects", "Destination": "/projects"},
    {"Source": "/opt/tidewatch/data", "Destination": "/data"},
]


def _mock_container(mounts: list[dict]) -> MagicMock:
    container = MagicMock()
    container.attrs = {"Mounts": mounts}
    return container


def _patch_inspect(mounts: list[dict]):
    """Patch Docker client to return a container with the given mounts."""
    mock_client = MagicMock()
    mock_client.containers.get.return_value = _mock_container(mounts)
    return patch(
        "app.services.mount_resolver.make_docker_client",
        return_value=mock_client,
    )


class TestGetHostPath:
    """Test host path resolution from mount inspection."""

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_resolves_compose_mount(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            assert get_host_path("/compose") == "/mnt/stacks"

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_resolves_projects_mount(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            assert get_host_path("/projects") == "/mnt/projects"

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_raises_for_unknown_mount(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            with pytest.raises(RuntimeError, match="No host mount found"):
                get_host_path("/nonexistent")

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_caches_after_first_call(self):
        with _patch_inspect(SAMPLE_MOUNTS) as mock_make:
            get_host_path("/compose")
            get_host_path("/projects")
            # Docker client created only once
            assert mock_make.call_count == 1

    @patch.dict("os.environ", {}, clear=False)
    def test_raises_without_hostname(self):
        # Remove HOSTNAME if present
        import os

        hostname = os.environ.pop("HOSTNAME", None)
        try:
            with pytest.raises(RuntimeError, match="HOSTNAME"):
                get_host_path("/compose")
        finally:
            if hostname is not None:
                os.environ["HOSTNAME"] = hostname

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_strips_trailing_slashes(self):
        mounts = [{"Source": "/mnt/stacks/", "Destination": "/compose/"}]
        with _patch_inspect(mounts):
            assert get_host_path("/compose") == "/mnt/stacks"


class TestTranslateContainerToHost:
    """Test full path translation."""

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_translates_full_path(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            result = translate_container_to_host("/compose/media/sonarr.yml", "/compose")
            assert result == "/mnt/stacks/media/sonarr.yml"

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_translates_nested_path(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            result = translate_container_to_host(
                "/compose/network/traefik/docker-compose.yml", "/compose"
            )
            assert result == "/mnt/stacks/network/traefik/docker-compose.yml"


class TestGetAllHostMountSources:
    """Test retrieving all host mount source paths."""

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_returns_sorted_sources(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            sources = get_all_host_mount_sources()
            assert sources == ("/mnt/projects", "/mnt/stacks", "/opt/tidewatch/data")

    @patch.dict("os.environ", {"HOSTNAME": "abc123"})
    def test_returns_tuple(self):
        with _patch_inspect(SAMPLE_MOUNTS):
            sources = get_all_host_mount_sources()
            assert isinstance(sources, tuple)
