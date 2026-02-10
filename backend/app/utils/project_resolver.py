"""Shared utility for resolving project root directories from compose files.

Extracted from DependencyScanner._find_project_root() for reuse across services.
"""

import logging
import re
from pathlib import Path

from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


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
