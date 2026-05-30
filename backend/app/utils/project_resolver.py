"""Shared utility for resolving project root directories.

Two resolvers live here:

- ``resolve_project_root(container)`` — preferred. Reads ``Container.project_root``
  first, then falls back to ``Path(compose_file).parent``. This is the contract
  used by ``dockerfile_parser``, ``http_server_scanner``, and the dependency
  scanner so that compose-independent My Project rows resolve correctly.

- ``find_project_root(compose_file, service_name, projects_directory)`` — legacy
  signature retained for callers that only have a compose path + service name
  (e.g., callers that build a fresh resolver before any Container row exists).
"""

import logging
import re
from pathlib import Path
from typing import Any

from app.utils.security import sanitize_log_message, sanitize_path

logger = logging.getLogger(__name__)


def resolve_project_root(container: Any, projects_directory: Path | None = None) -> Path | None:
    """Resolve a project root for a Container row.

    Priority:
        1. ``container.project_root`` if set (the Phase 0 anchor).
        2. ``Path(container.compose_file).parent`` if ``compose_file`` is truthy.
        3. None.

    Args:
        container: SQLAlchemy ``Container`` instance (or any object exposing
            ``project_root`` and ``compose_file`` attributes).
        projects_directory: When provided, the resolved root must be contained
            (symlink-free) under it, else None is returned. Omit for legacy
            ``/compose/...`` roots that legitimately live outside it.

    Returns:
        Path to the project root, or None when neither anchor is usable (or the
        root escapes ``projects_directory`` when that containment is requested).
    """
    root: Path | None = None

    project_root = getattr(container, "project_root", None)
    if project_root:
        try:
            root = Path(project_root)
        except (TypeError, ValueError) as e:
            logger.warning(
                "Invalid project_root %s: %s",
                sanitize_log_message(str(project_root)),
                sanitize_log_message(str(e)),
            )

    if root is None:
        compose_file = getattr(container, "compose_file", None)
        if compose_file:
            try:
                root = Path(compose_file).parent
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Invalid compose_file %s: %s",
                    sanitize_log_message(str(compose_file)),
                    sanitize_log_message(str(e)),
                )

    if root is None:
        return None

    if projects_directory is not None:
        try:
            sanitize_path(str(root), str(projects_directory), allow_symlinks=False)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "project_root %s escapes projects_directory %s: %s",
                sanitize_log_message(str(root)),
                sanitize_log_message(str(projects_directory)),
                sanitize_log_message(str(e)),
            )
            return None

    return root


def find_project_root(
    compose_file: str,
    service_name: str,
    projects_directory: Path,
) -> Path | None:
    """Find the project root directory from a compose file path.

    Uses multiple fallback patterns to locate the project source code:
    1. Compose file stem (e.g., /compose/mygarage.yaml -> /projects/mygarage)
    2. Full service name (e.g., /projects/mygarage-dev)
    3. Clean service name with suffix stripped (e.g., /projects/mygarage)

    Args:
        compose_file: Path to the compose file (e.g., /compose/mygarage.yaml)
        service_name: Service name in the compose file (e.g., mygarage-dev)
        projects_directory: Base directory containing project source code

    Returns:
        Path to project root or None if not found
    """
    try:
        compose_path = Path(compose_file)
        project_name = compose_path.stem

        # Remove common suffixes like -dev, -prod, _dev, _prod from service_name
        clean_service_name = re.sub(r"[-_](dev|prod|test|staging)$", "", service_name)

        possible_paths = [
            projects_directory / project_name,
            projects_directory / service_name,
            projects_directory / clean_service_name,
        ]

        for path in possible_paths:
            if path.exists() and path.is_dir():
                logger.info(f"Found project root: {sanitize_log_message(str(path))}")
                return path

        logger.warning(
            f"No project root found. Tried: {sanitize_log_message(str([str(p) for p in possible_paths]))}"
        )
        return None
    except (OSError, PermissionError) as e:
        logger.error(f"File system error finding project root: {sanitize_log_message(str(e))}")
        return None
    except ValueError as e:
        logger.error(f"Invalid path finding project root: {sanitize_log_message(str(e))}")
        return None
