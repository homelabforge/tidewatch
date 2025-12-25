"""Parsers for updating dependency manifest files.

Supports multiple package managers and manifest formats:
- package.json (npm)
- requirements.txt (Python pip)
- pyproject.toml (Python Poetry/modern)
- composer.json (PHP)
- Cargo.toml (Rust)
- go.mod (Go)
"""

import json
import re
from pathlib import Path
from typing import Tuple
import logging
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


class ManifestUpdateError(Exception):
    """Base exception for manifest update errors."""

    pass


def update_package_json(
    file_path: Path,
    package_name: str,
    new_version: str,
    dependency_type: str = "dependencies",
) -> Tuple[bool, str]:
    """
    Update package version in package.json.

    Args:
        file_path: Path to package.json
        package_name: Package name to update
        new_version: New version (can include semver prefix like ^, ~)
        dependency_type: Section to update (dependencies, devDependencies, etc.)

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if dependency exists in specified section
        if dependency_type not in data:
            logger.warning(
                f"Section {sanitize_log_message(str(dependency_type))} not found in {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        if package_name not in data[dependency_type]:
            logger.warning(
                f"Package {sanitize_log_message(str(package_name))} not found in {sanitize_log_message(str(dependency_type))} section"
            )
            return False, ""

        # Update version, preserving semver prefix (^, ~, etc.)
        old_version = data[dependency_type][package_name]

        # Extract prefix from old version (^, ~, >=, etc.)
        prefix = ""
        if old_version and old_version[0] in "^~>=<":
            for char in old_version:
                if char in "^~>=<":
                    prefix += char
                else:
                    break

        # Apply prefix to new version if it doesn't already have one
        if prefix and not any(
            new_version.startswith(p) for p in ["^", "~", ">=", "<=", ">", "<"]
        ):
            new_version = prefix + new_version

        data[dependency_type][package_name] = new_version

        # Serialize back to JSON with proper formatting
        updated_content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        logger.info(
            f"Updated {sanitize_log_message(str(package_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in package.json"
        )
        return True, updated_content

    except json.JSONDecodeError as e:
        logger.error(
            f"JSON decode error in {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""


def update_requirements_txt(
    file_path: Path, package_name: str, new_version: str
) -> Tuple[bool, str]:
    """
    Update package version in requirements.txt.

    Handles formats:
    - package==1.2.3
    - package>=1.2.3
    - package~=1.2.0
    - git+https://...

    Args:
        file_path: Path to requirements.txt
        package_name: Package name to update (case-insensitive)
        new_version: New version

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        for i, line in enumerate(lines):
            # Skip comments and empty lines
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Match package name with version specifier
            # Handles: package==1.2.3, package>=1.2.3, package~=1.2.0
            match = re.match(
                rf"^({re.escape(package_name)})\s*([=<>~!]+)\s*([^\s#]+)(.*)$",
                line,
                re.IGNORECASE,
            )

            if match:
                pkg_name = match.group(1)
                operator = match.group(2)
                old_version = match.group(3)
                comments = match.group(4)  # Preserve inline comments

                # Build new line preserving operator and comments
                new_line = f"{pkg_name}{operator}{new_version}{comments}\n"
                lines[i] = new_line
                updated = True

                logger.info(
                    f"Updated {sanitize_log_message(str(pkg_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in requirements.txt"
                )
                break

        if not updated:
            logger.warning(
                f"Package {sanitize_log_message(str(package_name))} not found in {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        return True, "".join(lines)

    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except UnicodeDecodeError as e:
        logger.error(
            f"Encoding error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""


def update_pyproject_toml(
    file_path: Path, package_name: str, new_version: str, section: str = "dependencies"
) -> Tuple[bool, str]:
    """
    Update package version in pyproject.toml.

    Handles both formats:
    - Key-value: package = "^1.2.3"
    - Array: "package>=1.2.3",

    Args:
        file_path: Path to pyproject.toml
        package_name: Package name to update
        new_version: New version
        section: Section to update (dependencies, development, optional)

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        # Read file as text (not using tomllib since we need to preserve formatting)
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        in_target_section = False
        section_patterns = []

        # Map section parameter to actual TOML section patterns
        if section == "dependencies":
            section_patterns = [
                r"^\[project\.dependencies\]",
                r"^dependencies\s*=\s*\[",
            ]
        elif section == "development":
            section_patterns = [
                r"^\[project\.optional-dependencies\.dev\]",
                r"^\[project\.optional-dependencies\]",  # Look for inline dev = [...]
                r"^\[tool\.poetry\.group\.dev\.dependencies\]",
            ]
        elif section == "optional":
            section_patterns = [r"^\[project\.optional-dependencies\]"]
        else:
            # Custom section name
            section_patterns = [rf"^\[.*{re.escape(section)}.*\]"]

        for i, line in enumerate(lines):
            # Check if we're entering a target section
            if any(re.match(pattern, line.strip()) for pattern in section_patterns):
                in_target_section = True
                continue
            # Check if we're leaving the section (new section starts)
            elif line.strip().startswith("["):
                in_target_section = False
                continue

            if in_target_section:
                # Format 1: Key-value style (Poetry): package = "^1.2.3"
                kv_match = re.match(
                    rf'^(\s*)({re.escape(package_name)})\s*=\s*["\']([^"\']+)["\'](.*)$',
                    line,
                )

                if kv_match:
                    indent = kv_match.group(1)
                    pkg_name = kv_match.group(2)
                    old_version = kv_match.group(3)
                    rest = kv_match.group(4)

                    # Preserve version prefix (^, ~, >=, etc.)
                    prefix = ""
                    if old_version and old_version[0] in "^~>=<":
                        for char in old_version:
                            if char in "^~>=<":
                                prefix += char
                            else:
                                break

                    # Build new line preserving formatting
                    new_line = f'{indent}{pkg_name} = "{prefix}{new_version}"{rest}\n'
                    lines[i] = new_line
                    updated = True

                    logger.info(
                        f"Updated {sanitize_log_message(str(pkg_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in pyproject.toml (key-value format)"
                    )
                    break

                # Format 2: Array style (PEP 621): "package>=1.2.3",
                array_match = re.match(
                    rf'^(\s*)["\']({re.escape(package_name)})([><=~!]+)([^"\']+)["\'](.*)$',
                    line,
                )

                if array_match:
                    indent = array_match.group(1)
                    pkg_name = array_match.group(2)
                    operator = array_match.group(3)
                    old_version = array_match.group(4)
                    rest = array_match.group(5)  # Includes trailing comma

                    # Build new line preserving formatting
                    new_line = f'{indent}"{pkg_name}{operator}{new_version}"{rest}\n'
                    lines[i] = new_line
                    updated = True

                    logger.info(
                        f"Updated {sanitize_log_message(str(pkg_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in pyproject.toml (array format)"
                    )
                    break

        if not updated:
            logger.warning(
                f"Package {sanitize_log_message(str(package_name))} not found in {sanitize_log_message(str(section))} section of {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        return True, "".join(lines)

    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except UnicodeDecodeError as e:
        logger.error(
            f"Encoding error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""


def update_composer_json(
    file_path: Path,
    package_name: str,
    new_version: str,
    dependency_type: str = "require",
) -> Tuple[bool, str]:
    """
    Update package version in composer.json (PHP).

    Args:
        file_path: Path to composer.json
        package_name: Package name to update
        new_version: New version
        dependency_type: Section to update (require, require-dev)

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if dependency_type not in data:
            logger.warning(
                f"Section {sanitize_log_message(str(dependency_type))} not found in {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        if package_name not in data[dependency_type]:
            logger.warning(
                f"Package {sanitize_log_message(str(package_name))} not found in {sanitize_log_message(str(dependency_type))} section"
            )
            return False, ""

        # Update version
        old_version = data[dependency_type][package_name]
        data[dependency_type][package_name] = new_version

        # Serialize back to JSON with proper formatting (4 spaces for PHP convention)
        updated_content = json.dumps(data, indent=4, ensure_ascii=False) + "\n"

        logger.info(
            f"Updated {sanitize_log_message(str(package_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in composer.json"
        )
        return True, updated_content

    except json.JSONDecodeError as e:
        logger.error(
            f"JSON decode error in {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""


def update_cargo_toml(
    file_path: Path, package_name: str, new_version: str, section: str = "dependencies"
) -> Tuple[bool, str]:
    """
    Update package version in Cargo.toml (Rust).

    Args:
        file_path: Path to Cargo.toml
        package_name: Package name to update
        new_version: New version
        section: Section to update (dependencies, dev-dependencies)

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        in_section = False

        for i, line in enumerate(lines):
            # Track if we're in the right section
            if re.match(rf"^\[{re.escape(section)}\]", line):
                in_section = True
                continue
            elif line.strip().startswith("["):
                in_section = False
                continue

            if in_section:
                # Match simple format: package = "1.2.3"
                simple_match = re.match(
                    rf'^({re.escape(package_name)})\s*=\s*["\']([^"\']+)["\'](.*)$',
                    line,
                )

                if simple_match:
                    pkg_name = simple_match.group(1)
                    old_version = simple_match.group(2)
                    rest = simple_match.group(3)

                    new_line = f'{pkg_name} = "{new_version}"{rest}\n'
                    lines[i] = new_line
                    updated = True

                    logger.info(
                        f"Updated {sanitize_log_message(str(pkg_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in Cargo.toml"
                    )
                    break

                # Match table format: package = { version = "1.2.3", features = [...] }
                table_match = re.match(
                    rf'^({re.escape(package_name)})\s*=\s*\{{\s*version\s*=\s*["\']([^"\']+)["\']',
                    line,
                )

                if table_match:
                    pkg_name = table_match.group(1)
                    old_version = table_match.group(2)

                    # Replace just the version part
                    new_line = re.sub(
                        r'(version\s*=\s*["\'])([^"\']+)(["\'])',
                        rf"\g<1>{new_version}\g<3>",
                        line,
                    )
                    lines[i] = new_line
                    updated = True

                    logger.info(
                        f"Updated {sanitize_log_message(str(pkg_name))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in Cargo.toml"
                    )
                    break

        if not updated:
            logger.warning(
                f"Package {sanitize_log_message(str(package_name))} not found in {sanitize_log_message(str(section))} section of {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        return True, "".join(lines)

    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except UnicodeDecodeError as e:
        logger.error(
            f"Encoding error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""


def update_go_mod(
    file_path: Path, module_name: str, new_version: str
) -> Tuple[bool, str]:
    """
    Update module version in go.mod.

    Args:
        file_path: Path to go.mod
        module_name: Module name to update
        new_version: New version (should start with v)

    Returns:
        Tuple of (success: bool, updated_content: str)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Ensure version starts with 'v'
        if not new_version.startswith("v"):
            new_version = f"v{new_version}"

        updated = False
        for i, line in enumerate(lines):
            # Match require statements: module v1.2.3
            match = re.match(
                rf"^\s*({re.escape(module_name)})\s+(v[\d.]+)(.*)$", line.strip()
            )

            if match:
                module = match.group(1)
                old_version = match.group(2)
                rest = match.group(3)

                # Preserve indentation
                indent = len(line) - len(line.lstrip())
                new_line = f"{' ' * indent}{module} {new_version}{rest}\n"
                lines[i] = new_line
                updated = True

                logger.info(
                    f"Updated {sanitize_log_message(str(module))} from {sanitize_log_message(str(old_version))} to {sanitize_log_message(str(new_version))} in go.mod"
                )
                break

        if not updated:
            logger.warning(
                f"Module {sanitize_log_message(str(module_name))} not found in {sanitize_log_message(str(file_path))}"
            )
            return False, ""

        return True, "".join(lines)

    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
    except UnicodeDecodeError as e:
        logger.error(
            f"Encoding error updating {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
        )
        return False, ""
