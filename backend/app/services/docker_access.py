"""Centralized Docker endpoint resolution and client creation.

All Docker access (SDK clients and subprocess calls) should use these helpers
to ensure consistent endpoint resolution. The source of truth for the Docker
endpoint is the ``docker_socket`` DB setting; callers without DB access fall
back to the ``DOCKER_HOST`` environment variable.
"""

import logging
import os

import docker

logger = logging.getLogger(__name__)


async def resolve_docker_url(db=None) -> str:
    """Resolve the active Docker endpoint.

    Args:
        db: Optional AsyncSession. When provided, reads the ``docker_socket``
            setting from the database (the runtime source of truth).

    Returns:
        Normalized Docker endpoint URL (``tcp://…`` or ``unix://…``).
    """
    if db is not None:
        from app.services.settings_service import SettingsService

        url = await SettingsService.get(db, "docker_socket")
        if url:
            return _normalize_url(url)
    return _normalize_url(os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"))


def resolve_docker_url_sync() -> str:
    """Resolve the Docker endpoint synchronously.

    For init-time callers (singletons) that lack DB access. Uses
    ``DOCKER_HOST`` env, which matches the DB default at startup.
    """
    return _normalize_url(os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"))


def _normalize_url(url: str) -> str:
    """Ensure *url* has a ``tcp://`` or ``unix://`` prefix."""
    if url.startswith(("tcp://", "unix://")):
        return url
    return f"unix://{url}"


def make_docker_client(base_url: str, timeout: int = 30) -> docker.DockerClient:
    """Create a new :class:`docker.DockerClient`.

    No caching — each caller manages its own client lifecycle.
    """
    return docker.DockerClient(base_url=base_url, timeout=timeout)


def docker_subprocess_env(base_url: str | None = None) -> dict[str, str]:
    """Build a subprocess environment dict with ``DOCKER_HOST`` set.

    Args:
        base_url: Docker endpoint URL. If *None*, inherits the current
            process environment as-is.

    Returns:
        A copy of ``os.environ`` with ``DOCKER_HOST`` set when *base_url*
        is provided.
    """
    env = os.environ.copy()
    if base_url:
        env["DOCKER_HOST"] = base_url
    return env
