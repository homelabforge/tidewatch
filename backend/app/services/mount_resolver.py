"""Auto-detect host paths from TideWatch's own container mount bindings.

At runtime TideWatch needs to translate container-internal paths (e.g.
``/compose/media/sonarr.yml``) to the corresponding host paths so that
``docker compose -f`` receives paths the daemon can resolve.  Rather than
hardcoding host paths, this module inspects TideWatch's own container via
the Docker API and reads the mount table.

Usage::

    from app.services.mount_resolver import get_host_path

    host_compose = get_host_path("/compose")
    # e.g. "/mnt/Apps_SSD_128GB/docker_stacks"
"""

import logging
import os
from pathlib import PurePosixPath

import docker
from docker.errors import APIError, DockerException, NotFound

from app.services.docker_access import make_docker_client, resolve_docker_url_sync

logger = logging.getLogger(__name__)

# Cached mapping: container mount destination -> host source path
_mount_map: dict[str, str] | None = None


def _inspect_own_mounts() -> dict[str, str]:
    """Inspect this container's mounts via the Docker API.

    Returns:
        Dict mapping container destination paths to host source paths.
        Example: ``{"/compose": "/srv/raid0/docker/compose", "/data": "./data"}``

    Raises:
        RuntimeError: If self-inspection fails (container ID not found,
            Docker API unreachable, or permission denied).
    """
    container_id = os.environ.get("HOSTNAME", "")
    if not container_id:
        raise RuntimeError(
            "Cannot detect container ID: HOSTNAME environment variable is not set. "
            "TideWatch must run inside a Docker container."
        )

    docker_url = resolve_docker_url_sync()
    client: docker.DockerClient | None = None
    try:
        client = make_docker_client(docker_url, timeout=10)
        container = client.containers.get(container_id)
        mounts: list[dict] = container.attrs.get("Mounts", [])

        mount_map: dict[str, str] = {}
        for m in mounts:
            destination = m.get("Destination", "")
            source = m.get("Source", "")
            if destination and source:
                # Normalise trailing slashes
                mount_map[destination.rstrip("/")] = source.rstrip("/")

        logger.info(
            "Resolved %d container mount(s): %s",
            len(mount_map),
            ", ".join(f"{d} -> {s}" for d, s in sorted(mount_map.items())),
        )
        return mount_map

    except NotFound:
        raise RuntimeError(
            f"Container '{container_id}' not found via Docker API. "
            "Ensure TideWatch can inspect its own container "
            "(socket-proxy must allow container inspect)."
        )
    except (APIError, DockerException) as exc:
        raise RuntimeError(
            f"Failed to inspect container '{container_id}': {exc}. Check Docker socket permissions."
        )
    finally:
        if client:
            client.close()


def _get_mount_map() -> dict[str, str]:
    """Return the cached mount map, populating it on first call."""
    global _mount_map
    if _mount_map is None:
        _mount_map = _inspect_own_mounts()
    return _mount_map


def get_host_path(container_mount_point: str) -> str:
    """Return the host-side path for a given container mount point.

    Args:
        container_mount_point: Absolute path inside the container,
            e.g. ``"/compose"`` or ``"/projects"``.

    Returns:
        The corresponding host path, e.g. ``"/srv/raid0/docker/compose"``.

    Raises:
        RuntimeError: If the mount point is not found or self-inspection fails.
    """
    key = container_mount_point.rstrip("/")
    mount_map = _get_mount_map()

    if key in mount_map:
        return mount_map[key]

    raise RuntimeError(
        f"No host mount found for container path '{key}'. "
        f"Known mounts: {list(mount_map.keys())}. "
        f"Ensure the volume is mounted in your docker-compose.yml."
    )


def get_all_host_mount_sources() -> tuple[str, ...]:
    """Return all host source paths from TideWatch's mounts.

    Useful for building skip-lists (e.g. paths to exclude from backup).
    """
    mount_map = _get_mount_map()
    return tuple(sorted(mount_map.values()))


def translate_container_to_host(container_path: str, mount_point: str) -> str:
    """Translate a full container path to its host equivalent.

    Args:
        container_path: Full path inside container, e.g.
            ``"/compose/media/sonarr.yml"``.
        mount_point: The mount point prefix, e.g. ``"/compose"``.

    Returns:
        Host path, e.g. ``"/mnt/stacks/media/sonarr.yml"``.
    """
    host_base = get_host_path(mount_point)
    rel = PurePosixPath(container_path).relative_to(mount_point)
    return str(PurePosixPath(host_base) / rel)


def reset_cache() -> None:
    """Clear the cached mount map.  Intended for testing."""
    global _mount_map
    _mount_map = None
