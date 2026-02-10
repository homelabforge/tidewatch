"""Parse-only manifest file readers for dependency detection.

These functions ONLY read and parse local manifest files. They make NO network
calls (no npm registry, no PyPI, no GitHub API). This is critical for use in
HTTP server detection where speed and reliability matter.

For version update checking, use the full DependencyScanner service instead.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


@dataclass
class ParsedDependency:
    """A dependency parsed from a manifest file (local only, no network data)."""

    name: str
    version: str | None
    dep_type: str  # "production", "development", "optional", "peer"
    source_file: str  # relative path to the manifest file


def parse_package_json(path: Path) -> list[ParsedDependency]:
    """Parse dependencies from a package.json file.

    Reads dependencies, devDependencies, optionalDependencies, and peerDependencies.

    Args:
        path: Path to package.json

    Returns:
        List of parsed dependencies with name, version, and type
    """
    deps: list[ParsedDependency] = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.debug(
            f"Could not parse {sanitize_log_message(str(path))}: {sanitize_log_message(str(e))}"
        )
        return deps

    section_map = {
        "dependencies": "production",
        "devDependencies": "development",
        "optionalDependencies": "optional",
        "peerDependencies": "peer",
    }

    source = str(path)
    for section, dep_type in section_map.items():
        for name, version_spec in data.get(section, {}).items():
            version = _extract_npm_version(version_spec)
            deps.append(
                ParsedDependency(name=name, version=version, dep_type=dep_type, source_file=source)
            )

    return deps


def parse_pyproject_toml(path: Path) -> list[ParsedDependency]:
    """Parse dependencies from a pyproject.toml file.

    Handles both PEP 621 ([project.dependencies]) and Poetry
    ([tool.poetry.dependencies]) formats.

    Args:
        path: Path to pyproject.toml

    Returns:
        List of parsed dependencies with name, version, and type
    """
    deps: list[ParsedDependency] = []
    try:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, Exception) as e:
        logger.debug(
            f"Could not parse {sanitize_log_message(str(path))}: {sanitize_log_message(str(e))}"
        )
        return deps

    source = str(path)

    # PEP 621: [project.dependencies] (array of strings like "granian>=2.6.0")
    project = data.get("project", {})
    for dep_str in project.get("dependencies", []):
        name, version = _parse_pep621_dep(dep_str)
        if name:
            deps.append(
                ParsedDependency(
                    name=name, version=version, dep_type="production", source_file=source
                )
            )

    # PEP 621: [project.optional-dependencies.dev]
    optional_deps = project.get("optional-dependencies", {})
    for dep_str in optional_deps.get("dev", []):
        name, version = _parse_pep621_dep(dep_str)
        if name:
            deps.append(
                ParsedDependency(
                    name=name, version=version, dep_type="development", source_file=source
                )
            )

    # Poetry: [tool.poetry.dependencies]
    poetry = data.get("tool", {}).get("poetry", {})
    for name, version_spec in poetry.get("dependencies", {}).items():
        if name.lower() == "python":
            continue
        version = _extract_poetry_version(version_spec)
        deps.append(
            ParsedDependency(name=name, version=version, dep_type="production", source_file=source)
        )

    # Poetry: [tool.poetry.group.dev.dependencies]
    dev_group = poetry.get("group", {}).get("dev", {})
    for name, version_spec in dev_group.get("dependencies", {}).items():
        version = _extract_poetry_version(version_spec)
        deps.append(
            ParsedDependency(name=name, version=version, dep_type="development", source_file=source)
        )

    return deps


def parse_requirements_txt(path: Path) -> list[ParsedDependency]:
    """Parse dependencies from a requirements.txt file.

    Handles formats: package==1.2.3, package>=1.2.3, package~=1.2.0,
    package[extra]==1.2.3, and skips comments/blank lines.

    Args:
        path: Path to requirements.txt

    Returns:
        List of parsed dependencies with name, version, and type
    """
    deps: list[ParsedDependency] = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.debug(
            f"Could not read {sanitize_log_message(str(path))}: {sanitize_log_message(str(e))}"
        )
        return deps

    source = str(path)
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue

        match = re.match(r"^([a-zA-Z0-9_.-]+)(?:\[.*?\])?\s*([><=~!]+)\s*([^\s,;#]+)", stripped)
        if match:
            name = match.group(1)
            version = match.group(3)
            deps.append(
                ParsedDependency(
                    name=name, version=version, dep_type="production", source_file=source
                )
            )
        else:
            # Package without version spec (e.g., just "requests")
            name_match = re.match(r"^([a-zA-Z0-9_.-]+)", stripped)
            if name_match:
                deps.append(
                    ParsedDependency(
                        name=name_match.group(1),
                        version=None,
                        dep_type="production",
                        source_file=source,
                    )
                )

    return deps


def _extract_npm_version(version_spec: object) -> str | None:
    """Extract version number from npm version specifier.

    Examples:
        "^4.21.0" -> "4.21.0"
        "~1.2.3" -> "1.2.3"
        ">=2.0.0" -> "2.0.0"
        "workspace:*" -> None
        "*" -> None
    """
    if not isinstance(version_spec, str):
        return None
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_spec)
    return match.group(1) if match else None


def _parse_pep621_dep(dep_str: object) -> tuple[str | None, str | None]:
    """Parse a PEP 621 dependency string like 'granian>=2.6.0' or 'requests[security]'.

    Returns:
        Tuple of (package_name, version) or (None, None) if unparseable
    """
    if not isinstance(dep_str, str):
        return None, None

    match = re.match(r"^([a-zA-Z0-9_.-]+)(?:\[.*?\])?\s*(?:[><=~!]+)\s*([^\s,;]+)", dep_str)
    if match:
        return match.group(1), match.group(2)

    # Package without version constraint
    name_match = re.match(r"^([a-zA-Z0-9_.-]+)", dep_str)
    if name_match:
        return name_match.group(1), None

    return None, None


def _extract_poetry_version(version_spec: str | dict) -> str | None:
    """Extract version from Poetry version specifier.

    Poetry can use either string ("^2.6.0") or dict ({"version": "^2.6.0", "optional": true}).
    """
    if isinstance(version_spec, dict):
        version_spec = version_spec.get("version", "")
    if not isinstance(version_spec, str):
        return None
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_spec)
    return match.group(1) if match else None
