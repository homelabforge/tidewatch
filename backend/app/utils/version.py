"""Version comparison and app version utilities."""

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

# Cached app version (read once at import time)
_app_version: str | None = None


def get_app_version() -> str:
    """Get TideWatch version from pyproject.toml (single source of truth).

    Searches multiple candidate paths to work in both development
    and Docker container environments. Result is cached after first call.

    Returns:
        Version string, or "0.0.0-dev" if pyproject.toml cannot be found/parsed.
    """
    global _app_version  # noqa: PLW0603
    if _app_version is not None:
        return _app_version

    candidates = [
        Path("/app/pyproject.toml"),  # Docker production image
        Path(__file__).resolve().parent.parent.parent / "pyproject.toml",  # backend/pyproject.toml
        Path("pyproject.toml"),  # CWD fallback
    ]

    for pyproject_path in candidates:
        try:
            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                version = data["project"]["version"]
                _app_version = version
                return version
        except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as e:
            logger.debug(f"Could not read version from {pyproject_path}: {e}")
            continue

    logger.warning("pyproject.toml not found in any candidate path")
    _app_version = "0.0.0-dev"
    return "0.0.0-dev"


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a version string into (major, minor, patch) tuple.

    Args:
        version: Version string (e.g., "1.2.3", "v2.0.0", "3.14-alpine")

    Returns:
        Tuple of (major, minor, patch) as integers

    Raises:
        ValueError: If version string cannot be parsed
    """
    # Remove common prefixes and suffixes
    version = version.lstrip("v")

    # Split on common delimiters and take first part
    # e.g., "3.14-alpine" -> "3.14"
    version = version.split("-")[0].split("_")[0]

    # Parse version parts
    parts = version.split(".")
    if len(parts) < 1:
        raise ValueError(f"Invalid version format: {version}")

    # Extract major, minor, patch (default to 0 if not present)
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0

    return (major, minor, patch)


def get_version_change_type(from_version: str, to_version: str) -> str | None:
    """Determine the type of version change (major, minor, or patch).

    Args:
        from_version: Current version string
        to_version: New version string

    Returns:
        "major", "minor", "patch", or None if versions cannot be compared
    """
    try:
        from_parts = parse_version(from_version)
        to_parts = parse_version(to_version)

        # Major version change
        if to_parts[0] > from_parts[0]:
            return "major"

        # Minor version change
        if to_parts[1] > from_parts[1]:
            return "minor"

        # Patch version change
        if to_parts[2] > from_parts[2]:
            return "patch"

        # No change or downgrade
        return None

    except (ValueError, IndexError) as e:
        logger.debug(f"Could not parse versions '{from_version}' -> '{to_version}': {e}")
        return None


def is_major_update(from_version: str, to_version: str) -> bool:
    """Check if update is a major version change.

    Args:
        from_version: Current version string
        to_version: New version string

    Returns:
        True if major version increases, False otherwise
    """
    return get_version_change_type(from_version, to_version) == "major"


def is_minor_or_patch_update(from_version: str, to_version: str) -> bool:
    """Check if update is a minor or patch version change.

    Args:
        from_version: Current version string
        to_version: New version string

    Returns:
        True if minor or patch version increases, False otherwise
    """
    change_type = get_version_change_type(from_version, to_version)
    return change_type in ["minor", "patch"]


def is_patch_update(from_version: str, to_version: str) -> bool:
    """Check if update is a patch version change only.

    Args:
        from_version: Current version string
        to_version: New version string

    Returns:
        True if only patch version increases, False otherwise
    """
    return get_version_change_type(from_version, to_version) == "patch"
