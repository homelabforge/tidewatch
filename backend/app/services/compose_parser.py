"""Docker Compose file parser for discovering containers."""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from ruamel.yaml import YAML, YAMLError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.services.docker_access import make_docker_client, resolve_docker_url
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

# Recursive compose file discovery constants
_MAX_DEPTH = 3  # max subdirectory levels below compose_directory
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".tox"}
_COMPOSE_EXTENSIONS = {".yml", ".yaml"}
_MAX_FILE_WARNINGS = 10  # cap per-file parse failure warnings


@dataclass
class SyncResult:
    """Result of a container sync operation."""

    added: int = 0
    updated: int = 0
    unchanged: int = 0
    total: int = 0
    warnings: list[str] = field(default_factory=list)


# Initialize ruamel.yaml with formatting preservation
yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096  # Prevent line wrapping
yaml.indent(mapping=2, sequence=2, offset=0)


def validate_container_name(name: str) -> bool:
    """Validate container name matches Docker naming constraints.

    Docker container names must:
    - Start with alphanumeric character
    - Contain only alphanumeric, underscore, period, or hyphen
    - Be 255 characters or less

    Args:
        name: Container name to validate

    Returns:
        True if valid, False otherwise
    """
    if not name or len(name) > 255:
        return False
    # Docker naming pattern: [a-zA-Z0-9][a-zA-Z0-9_.-]*
    pattern = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
    return bool(re.match(pattern, name))


def validate_compose_file_path(file_path: str, allowed_base_dir: str | None = None) -> bool:
    """Validate compose file path to prevent path traversal attacks.

    Args:
        file_path: Path to validate
        allowed_base_dir: Optional base directory to restrict access to

    Returns:
        True if path is safe, False otherwise
    """
    if not file_path:
        return False

    # Check for dangerous patterns before resolving
    dangerous_patterns = ["..", "//", "\\", "\x00"]
    if any(pattern in file_path for pattern in dangerous_patterns):
        logger.warning(f"Dangerous patterns detected in path: {file_path}")
        return False

    try:
        # Resolve to absolute path using strict=True to ensure file exists
        resolved_path = Path(file_path).resolve(strict=True)

        # Check if file exists and is a regular file
        if not resolved_path.exists() or not resolved_path.is_file():
            logger.warning(f"Path does not exist or is not a file: {file_path}")
            return False

        # Check file extension
        if resolved_path.suffix.lower() not in [".yml", ".yaml"]:
            logger.warning(f"Invalid file extension: {resolved_path.suffix}")
            return False

        # If base directory specified, ensure file is within it
        if allowed_base_dir:
            allowed_base = Path(allowed_base_dir).resolve()
            try:
                # Check if resolved path is relative to allowed base
                resolved_path.relative_to(allowed_base)
            except ValueError:
                logger.warning(
                    f"Path traversal attempt detected: {file_path} "
                    f"is outside allowed directory {allowed_base_dir}"
                )
                return False

        return True

    except (OSError, RuntimeError) as e:
        logger.warning(f"Error validating path {file_path}: {e}")
        return False


def validate_tag_format(tag: str) -> bool:
    """Validate Docker tag format to prevent injection attacks.

    Docker tags must:
    - Be 128 characters or less
    - Contain only alphanumeric, period, underscore, or hyphen
    - Not start with period or hyphen

    Args:
        tag: Docker tag to validate

    Returns:
        True if valid, False otherwise
    """
    if not tag or len(tag) > 128:
        return False

    # Docker tag pattern: [a-zA-Z0-9_][a-zA-Z0-9_.-]*
    # Also allow sha256: prefix for digests
    if tag.startswith("sha256:"):
        # Validate sha256 digest format
        digest = tag[7:]
        return bool(re.match(r"^[a-fA-F0-9]{64}$", digest))

    # Regular tag validation
    pattern = r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$"
    return bool(re.match(pattern, tag))


class ComposeParser:
    """Parse docker-compose.yml files to discover containers."""

    @staticmethod
    async def resolve_project_compose_files(db: AsyncSession, container: Container) -> list[str]:
        """Resolve the ordered list of compose files for a container's project.

        Uses ``COMPOSE_FILE`` from the project ``.env`` as the canonical source
        of both membership and order.  This is required for multi-file compose
        projects where Docker Compose needs all files to validate cross-file
        dependencies (e.g. ``depends_on`` referencing services in other files).

        Args:
            db: Database session
            container: Container whose project files to resolve

        Returns:
            Ordered list of validated compose file paths

        Raises:
            ValidationError: If any listed file fails validation or if
                the container's compose_file is not in the COMPOSE_FILE list
        """
        from app.utils.validators import (
            ValidationError,
        )
        from app.utils.validators import (
            validate_compose_file_path as validate_path_utils,
        )

        # Single-file fallback when no project is set
        if not container.compose_project:
            return [container.compose_file]

        # Resolve compose root from settings (not hardcoded)
        compose_dir = await SettingsService.get(db, "compose_directory") or "/compose"
        compose_dir_path = Path(compose_dir)

        # Read .env for COMPOSE_FILE
        env_file = compose_dir_path / ".env"
        compose_file_value: str | None = None
        if env_file.exists():
            try:
                for line in env_file.read_text().splitlines():
                    stripped = line.strip()
                    if stripped.startswith("COMPOSE_FILE="):
                        compose_file_value = stripped.split("=", 1)[1].strip()
                        break
            except OSError as e:
                logger.warning("Failed to read %s: %s", env_file, e)

        # If no COMPOSE_FILE defined, fall back to single-file
        if not compose_file_value:
            return [container.compose_file]

        # Parse colon-separated file list and resolve relative paths
        raw_files = [f.strip() for f in compose_file_value.split(":") if f.strip()]
        resolved_files: list[str] = []
        for raw in raw_files:
            raw_path = Path(raw)
            if raw_path.is_absolute():
                resolved_files.append(str(raw_path))
            else:
                resolved_files.append(str(compose_dir_path / raw_path))

        # Validate every file (strict=True — files must exist in-container)
        invalid_files: list[str] = []
        for file_path in resolved_files:
            try:
                validate_path_utils(file_path, allowed_base=compose_dir, strict=True)
            except ValidationError:
                invalid_files.append(file_path)

        if invalid_files:
            raise ValidationError(
                f"COMPOSE_FILE references invalid/missing files: {invalid_files}. "
                f"All files listed in COMPOSE_FILE must exist and be valid compose files."
            )

        # Verify the container's own compose_file is in the list
        container_file = str(Path(container.compose_file).resolve())
        resolved_abs = [str(Path(f).resolve()) for f in resolved_files]
        if container_file not in resolved_abs:
            raise ValidationError(
                f"Configuration drift: container '{container.name}' references "
                f"compose file '{container.compose_file}' which is not in "
                f"COMPOSE_FILE ({compose_file_value}). "
                f"Update COMPOSE_FILE in {env_file} to include this file."
            )

        return resolved_files

    @staticmethod
    async def discover_containers(db: AsyncSession) -> tuple[list[Container], list[str]]:
        """Discover all containers from compose files.

        Walks the compose directory recursively (up to ``_MAX_DEPTH`` subdirectory
        levels), skipping well-known noise directories.  Returns both the
        discovered containers and a list of user-facing warnings for any issues
        encountered during discovery.

        Args:
            db: Database session

        Returns:
            Tuple of (containers, warnings)
        """
        warnings: list[str] = []

        compose_dir = await SettingsService.get(db, "compose_directory")
        if not compose_dir:
            logger.warning("Compose directory not configured")
            warnings.append("Compose directory not configured. Set it in Settings > Docker.")
            return [], warnings

        # Validate compose directory path to prevent path traversal attacks.
        # Reject any path containing dangerous patterns before resolving.
        dangerous_patterns = ["..", "//", "\\", "\x00"]
        if any(pattern in compose_dir for pattern in dangerous_patterns):
            logger.warning(
                f"Compose directory contains dangerous patterns: "
                f"{sanitize_log_message(compose_dir)}"
            )
            warnings.append("Compose directory path is invalid.")
            return [], warnings

        try:
            validated_dir = Path(compose_dir).resolve()

            if not validated_dir.exists():
                logger.warning(f"Compose directory not found: {validated_dir}")
                warnings.append(f"Compose directory '{compose_dir}' does not exist.")
                return [], warnings

            if not validated_dir.is_dir():
                logger.warning(f"Compose directory is not a directory: {validated_dir}")
                warnings.append(f"Compose directory '{compose_dir}' is not a directory.")
                return [], warnings

        except (OSError, RuntimeError) as e:
            logger.error(f"Invalid compose directory path: {sanitize_log_message(str(e))}")
            warnings.append("Compose directory path is invalid.")
            return [], warnings

        # Bounded recursive walk — prunes skipped dirs before descent
        compose_files: list[Path] = []
        for dirpath, dirnames, filenames in validated_dir.walk():
            depth = len(dirpath.relative_to(validated_dir).parts)
            # Collect compose files at this level (depth 0 through _MAX_DEPTH inclusive)
            if depth <= _MAX_DEPTH:
                for fname in filenames:
                    if Path(fname).suffix.lower() in _COMPOSE_EXTENSIONS:
                        compose_files.append(dirpath / fname)
            # Stop descending if we're at max depth (children would exceed it)
            if depth >= _MAX_DEPTH:
                dirnames.clear()
            else:
                # Prune noise dirs in-place so walk() never enters them
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        logger.info(
            f"Found {len(compose_files)} compose files in {compose_dir} "
            f"(recursive, max depth {_MAX_DEPTH})"
        )

        if not compose_files:
            warnings.append(
                f"No compose files (.yml/.yaml) found in '{compose_dir}' "
                f"(searched up to {_MAX_DEPTH} subdirectory levels)."
            )
            return [], warnings

        containers: list[Container] = []
        file_errors = 0

        for compose_file in compose_files:
            try:
                file_containers = await ComposeParser._parse_compose_file(str(compose_file), db)
                containers.extend(file_containers)
            except YAMLError as e:
                logger.error(f"YAML parsing error in {compose_file}: {e}")
                file_errors += 1
                if file_errors <= _MAX_FILE_WARNINGS:
                    warnings.append(f"Failed to parse {compose_file.name}: YAML error")
            except (OSError, PermissionError) as e:
                logger.error(f"File access error for {compose_file}: {e}")
                file_errors += 1
                if file_errors <= _MAX_FILE_WARNINGS:
                    warnings.append(f"Failed to parse {compose_file.name}: file access error")
            except OperationalError as e:
                logger.error(f"Database error parsing {compose_file}: {e}")
                file_errors += 1
                if file_errors <= _MAX_FILE_WARNINGS:
                    warnings.append(f"Failed to parse {compose_file.name}: database error")
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid compose data in {compose_file}: {e}")
                file_errors += 1
                if file_errors <= _MAX_FILE_WARNINGS:
                    warnings.append(f"Failed to parse {compose_file.name}: invalid data")

        # Append overflow summary if warnings were capped
        if file_errors > _MAX_FILE_WARNINGS:
            overflow = file_errors - _MAX_FILE_WARNINGS
            warnings.append(f"...and {overflow} more compose files failed to parse.")

        # Disambiguate duplicate display names (conflict-only prefixing)
        containers = ComposeParser._disambiguate_names(containers)

        logger.info(f"Discovered {len(containers)} containers total")
        return containers, warnings

    @staticmethod
    def _disambiguate_names(containers: list[Container]) -> list[Container]:
        """Prefix duplicate display names with compose file context.

        Solo names stay bare. Duplicates get prefixed with the compose file's
        parent directory name. If that still collides, the file stem is used.
        Final fallback: parent-stem-service (guaranteed unique since compose_file is unique).
        """
        name_counts = Counter(c.name for c in containers)
        duplicated = {name for name, count in name_counts.items() if count > 1}

        if not duplicated:
            return containers

        for container in containers:
            if container.name not in duplicated:
                continue

            svc = container.service_name
            parent = Path(container.compose_file).parent.name
            stem = Path(container.compose_file).stem

            if parent and parent != ".":
                container.name = f"{parent}-{svc}"
            elif stem and stem not in ("compose", "docker-compose"):
                container.name = f"{stem}-{svc}"
            else:
                container.name = svc  # fallback unchanged

        # Check if prefixing created new collisions
        name_counts2 = Counter(c.name for c in containers)
        still_duped = {name for name, count in name_counts2.items() if count > 1}

        if still_duped:
            for container in containers:
                if container.name not in still_duped:
                    continue
                parent = Path(container.compose_file).parent.name
                stem = Path(container.compose_file).stem
                svc = container.service_name
                container.name = f"{parent}-{stem}-{svc}"

        logger.info(
            "Disambiguated %d duplicate name(s): %s",
            len(duplicated),
            ", ".join(sorted(duplicated)),
        )
        return containers

    @staticmethod
    async def _parse_compose_file(file_path: str, db: AsyncSession) -> list[Container]:
        """Parse a single compose file.

        Args:
            file_path: Path to compose file
            db: Database session

        Returns:
            List of Container objects from this file
        """
        containers = []

        with open(file_path) as f:
            compose_data = yaml.load(f)

        if not compose_data or "services" not in compose_data:
            logger.warning(f"No services found in {file_path}")
            return []

        services = compose_data.get("services", {})

        for service_name, service_config in services.items():
            if not isinstance(service_config, dict):
                continue

            # Validate container name to prevent command injection
            if not validate_container_name(service_name):
                logger.warning(f"Invalid container name '{service_name}', skipping for security")
                continue

            image = service_config.get("image")
            if not image:
                logger.debug(f"Service {service_name} has no image, skipping")
                continue

            # Parse image into registry, name, and tag
            parsed = ComposeParser._parse_image_string(image)
            if not parsed:
                logger.warning(f"Could not parse image: {image}")
                continue

            registry, image_name, tag = parsed

            # Get labels for policy configuration
            labels = service_config.get("labels", {})
            if isinstance(labels, list):
                # Convert list format to dict
                labels = ComposeParser._labels_list_to_dict(labels)

            # Sanitize and validate labels
            labels = ComposeParser._sanitize_labels(labels)

            # Extract TideWatch-specific labels
            policy_label = labels.get("tidewatch.policy")
            # Backward compat: map old policy values to new
            old_policy_map = {
                "patch-only": "auto",
                "minor-and-patch": "auto",
                "security": "auto",
                "manual": "monitor",
            }
            policy = old_policy_map.get(policy_label, policy_label) if policy_label else "monitor"
            scope_label = labels.get("tidewatch.scope")
            scope = scope_label or "patch"
            vulnforge_label = labels.get("tidewatch.vulnforge")
            vulnforge_enabled = (
                vulnforge_label.lower() == "true" if isinstance(vulnforge_label, str) else True
            )
            prereleases_label = labels.get("tidewatch.include_prereleases")
            include_prereleases = (
                prereleases_label.lower() == "true" if isinstance(prereleases_label, str) else False
            )
            enabled = labels.get("tidewatch.enabled", "true").lower() == "true"

            if not enabled:
                logger.debug(f"Container {service_name} is disabled via label")
                continue

            # Determine health check URL & method
            health_check_url = labels.get("tidewatch.health_check_url") or labels.get(
                "tidewatch.healthcheck"
            )
            if not health_check_url:
                health_check_url = ComposeParser._extract_healthcheck_url(
                    service_config.get("healthcheck"), service_name
                )
            health_check_method = ComposeParser._normalize_health_check_method(
                labels.get("tidewatch.health_check_method")
                or labels.get("tidewatch.healthcheck_method")
            )

            # Use container_name directive if present (globally unique in Docker)
            display_name = service_config.get("container_name") or service_name

            # Create container object
            container = Container(
                name=display_name,
                image=image_name,
                current_tag=tag,
                registry=registry,
                compose_file=file_path,
                service_name=service_name,
                policy=policy,
                scope=scope,
                include_prereleases=include_prereleases,
                vulnforge_enabled=vulnforge_enabled,
                update_available=False,
                latest_tag=None,
                labels=labels,  # Store all labels for auto-fill features
                health_check_url=health_check_url,
                health_check_method=health_check_method,
            )

            containers.append(container)
            container.__dict__["_policy_from_compose"] = policy_label is not None
            container.__dict__["_scope_from_compose"] = scope_label is not None
            container.__dict__["_prereleases_from_compose"] = prereleases_label is not None
            container.__dict__["_vulnforge_from_compose"] = vulnforge_label is not None
            container.__dict__["_health_method_from_compose"] = (
                labels.get("tidewatch.health_check_method") is not None
                or labels.get("tidewatch.healthcheck_method") is not None
            )
            logger.info(
                f"Discovered container: {service_name} ({image_name}:{tag}) "
                f"[policy={policy}, scope={scope}]"
            )

        return containers

    @staticmethod
    def _parse_image_string(image: str) -> tuple[str, str, str] | None:
        """Parse Docker image string into registry, name, and tag.

        Args:
            image: Image string (e.g., "ghcr.io/user/app:v1.2.3")

        Returns:
            Tuple of (registry, image_name, tag) or None if invalid
        """
        # Default values
        tag = "latest"
        registry = "docker.io"

        # Check for digest first (before splitting on :)
        # This handles formats like nginx@sha256:abc...
        if "@sha256:" in image:
            image, digest = image.split("@sha256:", 1)
            tag = f"sha256:{digest}"
        # Split off tag if present (but only if no digest)
        elif ":" in image:
            image, tag = image.rsplit(":", 1)

        # Determine registry
        parts = image.split("/")

        if len(parts) == 1:
            # Just image name (e.g., "nginx")
            image_name = parts[0]
        elif len(parts) == 2:
            # Could be "user/image" or "registry.com/image"
            if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
                # It's a registry
                registry = parts[0]
                image_name = parts[1]
            else:
                # It's docker.io/user/image
                image_name = "/".join(parts)
        else:
            # Full path with registry
            registry = parts[0]
            image_name = "/".join(parts[1:])

        # Normalize registries
        if registry == "docker.io":
            registry = "dockerhub"
        elif registry == "ghcr.io" or registry.endswith(".ghcr.io"):
            registry = "ghcr"
        elif registry == "lscr.io" or registry.endswith(".lscr.io"):
            registry = "lscr"
        elif registry == "gcr.io" or registry.endswith(".gcr.io"):
            registry = "gcr"
        elif registry == "quay.io" or registry.endswith(".quay.io"):
            registry = "quay"

        return (registry, image_name, tag)

    @staticmethod
    def _labels_list_to_dict(labels: list[str]) -> dict[str, str]:
        """Convert labels from list format to dict.

        Args:
            labels: List of "key=value" strings

        Returns:
            Dict of {key: value}
        """
        result = {}
        for label in labels:
            if "=" in label:
                key, value = label.split("=", 1)
                result[key] = value
        return result

    @staticmethod
    def _sanitize_labels(labels: dict[str, Any]) -> dict[str, str]:
        """Sanitize and validate Docker labels.

        - Ensure all values are strings
        - Limit label key/value lengths to prevent memory issues
        - Filter out potentially dangerous characters in keys
        - Limit total number of labels

        Args:
            labels: Raw label dictionary

        Returns:
            Sanitized label dictionary
        """
        if not isinstance(labels, dict):
            logger.warning(f"Invalid labels type: {type(labels)}, expected dict")
            return {}

        sanitized = {}
        max_labels = 100  # Prevent DoS via too many labels
        max_key_length = 255  # Docker limit for label keys
        max_value_length = 4096  # Reasonable limit for label values

        # Sort keys to ensure consistent processing
        for key in sorted(labels.keys())[:max_labels]:
            # Validate key format (alphanumeric, dots, hyphens, underscores)
            if not isinstance(key, str):
                logger.warning(f"Skipping non-string label key: {type(key)}")
                continue

            # Save original key before any modifications
            original_key = key

            # Enforce key length limit
            if len(key) > max_key_length:
                logger.warning(f"Label key too long ({len(key)} chars), truncating: {key[:50]}...")
                key = key[:max_key_length]

            # Docker labels allow: [a-zA-Z0-9._-]
            # We'll be more permissive but log suspicious patterns
            if any(char in key for char in ["\n", "\r", "\0", "\x00"]):
                logger.warning(f"Skipping label with control characters in key: {key[:50]}")
                continue

            # Convert value to string and enforce length limit (use original key)
            value = str(labels[original_key])
            if len(value) > max_value_length:
                logger.warning(
                    f"Label value too long ({len(value)} chars), truncating for key: {key}"
                )
                value = value[:max_value_length]

            # Filter control characters from value
            if any(char in value for char in ["\0", "\x00"]):
                logger.warning(f"Filtering null bytes from label value for key: {key}")
                value = value.replace("\0", "").replace("\x00", "")

            sanitized[key] = value

        if len(labels) > max_labels:
            logger.warning(f"Too many labels ({len(labels)}), only processing first {max_labels}")

        return sanitized

    @staticmethod
    def _extract_healthcheck_url(health_config, service_name: str) -> str | None:
        """Extract an HTTP health check URL from compose healthcheck config."""
        if not health_config:
            return None

        test_section = health_config
        if isinstance(health_config, dict):
            test_section = health_config.get("test")

        if isinstance(test_section, list):
            candidates = [item for item in test_section if isinstance(item, str)]
        elif isinstance(test_section, str):
            candidates = [test_section]
        else:
            candidates = []

        # More specific pattern to prevent ReDoS: limit length and use possessive quantifiers
        # Matches http(s)://domain/path but limits total length to 2048 chars
        url_pattern = re.compile(r"https?://[^\s'\"\\]{1,2000}")

        for candidate in candidates:
            # Limit input length to prevent ReDoS attacks
            if len(candidate) > 4096:
                logger.warning(f"Healthcheck candidate too long ({len(candidate)} chars), skipping")
                continue

            match = url_pattern.search(candidate)
            if match:
                return ComposeParser._normalize_healthcheck_url(match.group(0), service_name)

        return None

    @staticmethod
    def _normalize_healthcheck_url(url: str, service_name: str) -> str:
        """Rewrite localhost-style URLs to target the container service name."""
        try:
            parsed = urlparse(url)
            if parsed.scheme and parsed.hostname in {"localhost", "127.0.0.1"}:
                netloc = service_name
                if parsed.port:
                    netloc = f"{service_name}:{parsed.port}"
                rebuilt = parsed._replace(netloc=netloc)
                return urlunparse(rebuilt)
        except Exception as e:
            logger.debug("Failed to normalize healthcheck URL %s: %s", url, str(e))
        return url

    @staticmethod
    def _normalize_health_check_method(value: str | None) -> str:
        """Validate requested health check method."""
        if not value:
            return "auto"

        method = value.strip().lower()
        if method in {"auto", "http", "docker"}:
            return method

        logger.warning(f"Unknown tidewatch health check method '{value}', defaulting to auto")
        return "auto"

    @staticmethod
    async def sync_containers(db: AsyncSession) -> SyncResult:
        """Sync discovered containers with database.

        This will:
        - Add new containers
        - Update existing containers if changed
        - Mark missing containers (optional)

        Args:
            db: Database session

        Returns:
            SyncResult with counts and any discovery warnings
        """
        discovered, warnings = await ComposeParser.discover_containers(db)

        sync = SyncResult(total=len(discovered), warnings=warnings)

        for container in discovered:
            # Lookup by composite identity (service_name, compose_file)
            result = await db.execute(
                select(Container).where(
                    Container.service_name == container.service_name,
                    Container.compose_file == container.compose_file,
                )
            )
            existing = result.scalar_one_or_none()

            if not existing:
                # Add new container
                db.add(container)
                sync.added += 1
                logger.info(f"Added new container: {container.name}")
            else:
                # Update if changed
                changed = False

                # Display name may change due to conflict resolution
                if existing.name != container.name:
                    old_name = existing.name
                    existing.name = container.name
                    changed = True
                    await ComposeParser._cascade_name_change(db, existing.id, container.name)
                    logger.info(f"Renamed container display name: {old_name} -> {container.name}")

                if existing.image != container.image:
                    existing.image = container.image
                    changed = True

                if existing.current_tag != container.current_tag:
                    existing.current_tag = container.current_tag
                    changed = True

                if existing.registry != container.registry:
                    existing.registry = container.registry
                    changed = True

                if existing.compose_file != container.compose_file:
                    existing.compose_file = container.compose_file
                    changed = True

                # Always update labels from compose file
                if existing.labels != container.labels:
                    existing.labels = container.labels
                    changed = True

                if (
                    getattr(container, "_policy_from_compose", False)
                    and existing.policy != container.policy
                ):
                    existing.policy = container.policy
                    changed = True

                if (
                    getattr(container, "_scope_from_compose", False)
                    and existing.scope != container.scope
                ):
                    existing.scope = container.scope
                    changed = True

                if (
                    getattr(container, "_prereleases_from_compose", False)
                    and existing.include_prereleases != container.include_prereleases
                ):
                    existing.include_prereleases = container.include_prereleases
                    changed = True

                if (
                    getattr(container, "_vulnforge_from_compose", False)
                    and existing.vulnforge_enabled != container.vulnforge_enabled
                ):
                    existing.vulnforge_enabled = container.vulnforge_enabled
                    changed = True

                if (
                    container.health_check_url is not None
                    and existing.health_check_url != container.health_check_url
                ):
                    existing.health_check_url = container.health_check_url
                    changed = True

                if (
                    getattr(container, "_health_method_from_compose", False)
                    and existing.health_check_method != container.health_check_method
                ):
                    existing.health_check_method = container.health_check_method
                    changed = True

                if changed:
                    sync.updated += 1
                    logger.info(f"Updated container: {container.name}")
                else:
                    sync.unchanged += 1

        await db.commit()
        logger.info(
            f"Container sync complete: {sync.added} added, "
            f"{sync.updated} updated, {sync.unchanged} unchanged"
        )

        # Remove stale updates for rediscovered containers
        await ComposeParser._cleanup_stale_updates(db, discovered)

        # Check for stale containers after sync
        await ComposeParser._detect_stale_containers(db, discovered)

        # Sync Docker restart policies from runtime (after all other commits)
        await ComposeParser._sync_restart_policies(db, discovered)

        # Sync Docker Compose project names from container labels
        await ComposeParser._sync_compose_projects(db)

        await db.commit()

        return sync

    @staticmethod
    async def _cascade_name_change(db: AsyncSession, container_id: int, new_name: str) -> None:
        """Cascade a display-name change to all denormalized container_name columns.

        Uses stable container_id for safe, unambiguous updates.
        """
        from sqlalchemy import update as sa_update

        from app.models.check_job import CheckJob
        from app.models.history import UpdateHistory
        from app.models.pending_scan_job import PendingScanJob
        from app.models.restart_log import ContainerRestartLog
        from app.models.restart_state import ContainerRestartState
        from app.models.update import Update

        # ID-keyed updates
        await db.execute(
            sa_update(Update)
            .where(Update.container_id == container_id)
            .values(container_name=new_name)
        )
        await db.execute(
            sa_update(UpdateHistory)
            .where(UpdateHistory.container_id == container_id)
            .values(container_name=new_name)
        )
        await db.execute(
            sa_update(ContainerRestartState)
            .where(ContainerRestartState.container_id == container_id)
            .values(container_name=new_name)
        )
        await db.execute(
            sa_update(ContainerRestartLog)
            .where(ContainerRestartLog.container_id == container_id)
            .values(container_name=new_name)
        )
        # PendingScanJob: join through updates.id
        await db.execute(
            sa_update(PendingScanJob)
            .where(
                PendingScanJob.update_id.in_(
                    select(Update.id).where(Update.container_id == container_id)
                )
            )
            .values(container_name=new_name)
        )
        # CheckJob: has current_container_id
        await db.execute(
            sa_update(CheckJob)
            .where(CheckJob.current_container_id == container_id)
            .values(current_container_name=new_name)
        )

    @staticmethod
    async def _sync_restart_policies(db: AsyncSession, discovered: list[Container]) -> None:
        """Sync Docker restart policies from runtime to database.

        Args:
            db: Database session
            discovered: List of containers discovered from compose files
        """
        from app.services.docker_stats import DockerStatsService

        # Get all containers from database
        result = await db.execute(select(Container))
        all_containers = result.scalars().all()

        for container in all_containers:
            # Get restart policy from Docker runtime
            restart_policy = await DockerStatsService.get_restart_policy(container.runtime_name)

            # Update if different
            if container.restart_policy != restart_policy:
                container.restart_policy = restart_policy
                logger.debug(f"Updated restart policy for {container.name}: {restart_policy}")

    @staticmethod
    async def _sync_compose_projects(db: AsyncSession) -> None:
        """Sync compose_project and docker_name from Docker runtime labels.

        Uses label-based filtering (not name lookup) to correctly resolve
        containers even when multiple services share the same name.
        Always re-resolves so docker_name stays fresh after container recreations.

        Args:
            db: Database session
        """
        try:
            docker_url = await resolve_docker_url(db)
            client = make_docker_client(docker_url)
        except Exception as e:
            logger.warning(f"Could not connect to Docker for compose project sync: {e}")
            return

        try:
            result = await db.execute(select(Container))
            all_containers = result.scalars().all()

            for container in all_containers:
                try:
                    ComposeParser._resolve_runtime_info(client, container)
                except Exception as e:
                    logger.debug(f"Could not resolve runtime info for {container.name}: {e}")
        finally:
            client.close()

    @staticmethod
    def _resolve_runtime_info(client: Any, container: Container) -> None:
        """Resolve compose_project and docker_name from Docker runtime labels.

        Two-pass label filter: project-qualified first, service-only fallback.
        Only accepts unambiguous (single) matches on service-only pass.
        """
        from docker.errors import DockerException as _DockerException

        svc_label = f"com.docker.compose.service={container.service_name}"

        # Build filter sets: precise first, broad second
        filter_sets: list[dict[str, list[str]]] = []

        if container.compose_project:
            proj_label = f"com.docker.compose.project={container.compose_project}"
            filter_sets.append({"label": [svc_label, proj_label]})
        else:
            # Infer project from compose file parent dir (Docker Compose default)
            inferred = Path(container.compose_file).parent.name
            if inferred and inferred != ".":
                proj_label = f"com.docker.compose.project={inferred}"
                filter_sets.append({"label": [svc_label, proj_label]})

        # Broad fallback: service-only
        filter_sets.append({"label": [svc_label]})

        for i, filters in enumerate(filter_sets):
            try:
                matches = client.containers.list(all=True, filters=filters)
            except _DockerException:
                continue

            if len(matches) == 1:
                match = matches[0]
                docker_name = match.name.lstrip("/")
                if container.docker_name != docker_name:
                    container.docker_name = docker_name
                    logger.debug(f"Set docker_name={docker_name} for {container.name}")

                project = match.labels.get("com.docker.compose.project")
                if project and container.compose_project != project:
                    container.compose_project = project
                    logger.info(f"Set compose_project={project} for {container.name}")
                return

            if len(matches) > 1 and i == 0:
                # Project-qualified returned multiple — take first
                match = matches[0]
                container.docker_name = match.name.lstrip("/")
                project = match.labels.get("com.docker.compose.project")
                if project and not container.compose_project:
                    container.compose_project = project
                return

            # Service-only with multiple matches — ambiguous, skip
            if len(matches) > 1:
                logger.debug(
                    "Ambiguous service lookup for %s: %d matches, skipping docker_name",
                    container.name,
                    len(matches),
                )

    @staticmethod
    async def _cleanup_stale_updates(db: AsyncSession, discovered: list[Container]) -> None:
        """Remove stale updates for containers that have been rediscovered.

        Args:
            db: Database session
            discovered: List of containers found in compose files
        """
        from app.models.update import Update

        # Build set of discovered container names
        discovered_names = {c.name for c in discovered}

        # Find and delete stale updates for rediscovered containers
        result = await db.execute(
            select(Update).where(
                Update.reason_type == "stale",
                Update.status.in_(["pending", "approved"]),
            )
        )
        stale_updates = result.scalars().all()

        for update in stale_updates:
            if update.container_name in discovered_names:
                await db.delete(update)
                logger.info(
                    f"Removed stale update for rediscovered container: {update.container_name}"
                )

        await db.commit()

    @staticmethod
    async def _detect_stale_containers(db: AsyncSession, discovered: list[Container]) -> None:
        """Detect containers in database that are no longer in compose files.

        Creates Update records with reason_type="stale" for containers that
        haven't been found in compose files and exceed the threshold.

        Args:
            db: Database session
            discovered: List of containers discovered from compose files
        """
        from datetime import datetime, timedelta

        from app.models.update import Update

        # Check if stale detection is enabled
        enabled = await SettingsService.get_bool(db, "stale_detection_enabled", default=True)
        if not enabled:
            logger.debug("Stale detection is disabled")
            return

        threshold_days = await SettingsService.get_int(
            db, "stale_detection_threshold_days", default=30
        )
        exclude_dev = await SettingsService.get_bool(
            db, "stale_detection_exclude_dev", default=True
        )

        # Get all containers from database
        result = await db.execute(select(Container))
        all_containers = result.scalars().all()

        # Build set of discovered identities for quick lookup
        discovered_ids = {(c.service_name, c.compose_file) for c in discovered}

        # Current time for comparisons
        now = datetime.now(UTC)
        threshold = timedelta(days=threshold_days)

        for container in all_containers:
            # Skip if container is in compose files
            if (container.service_name, container.compose_file) in discovered_ids:
                continue

            # Exclude dev containers if configured
            if exclude_dev and container.name.endswith("-dev"):
                logger.debug(f"Skipping dev container: {container.name}")
                continue

            # Calculate how long it's been missing
            created_at = container.created_at
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            time_since_creation = now - created_at

            # Check if threshold exceeded
            if time_since_creation < threshold:
                logger.debug(
                    f"Container {container.name} not yet stale "
                    f"({time_since_creation.days}/{threshold_days} days)"
                )
                continue

            # Check if already has an active stale notification
            existing_update = await db.execute(
                select(Update).where(
                    Update.container_id == container.id,
                    Update.reason_type == "stale",
                    Update.status.in_(["pending", "approved"]),
                )
            )
            if existing_update.scalar_one_or_none():
                logger.debug(f"Container {container.name} already has stale notification")
                continue

            # Check if snoozed
            snoozed_update = await db.execute(
                select(Update).where(
                    Update.container_id == container.id,
                    Update.reason_type == "stale",
                    Update.snoozed_until > now,
                )
            )
            if snoozed_update.scalar_one_or_none():
                logger.debug(f"Stale notification for {container.name} is snoozed")
                continue

            # Create stale container notification
            stale_update = Update(
                container_id=container.id,
                container_name=container.name,
                from_tag=container.current_tag,
                to_tag=container.current_tag,  # No actual update
                registry=container.registry,
                reason_type="stale",
                reason_summary=f"Container not found in compose files for {time_since_creation.days} days",
                recommendation="Review and remove if no longer needed",
                status="pending",
                current_vulns=0,
                new_vulns=0,
                vuln_delta=0,
            )
            db.add(stale_update)
            logger.info(
                f"Created stale container notification for: {container.name} "
                f"(missing for {time_since_creation.days} days)"
            )

        await db.commit()

    @staticmethod
    async def update_compose_file(
        file_path: str,
        service_name: str,
        new_tag: str,
        db: AsyncSession | None = None,
    ) -> bool:
        """Update a compose file with a new image tag.

        This method preserves all formatting, comments, anchors (x-common), and structure.

        Args:
            file_path: Path to compose file
            service_name: Service name to update
            new_tag: New tag to set
            db: Optional database session for fetching allowed directory

        Returns:
            True if successful
        """
        try:
            # Validate service name to prevent injection
            if not validate_container_name(service_name):
                logger.error(f"Invalid service name format: {service_name}")
                return False

            # Validate tag format to prevent injection
            if not validate_tag_format(new_tag):
                logger.error(f"Invalid tag format: {new_tag}")
                return False

            # Get allowed compose directory if db session available
            allowed_dir = None
            if db:
                try:
                    allowed_dir = await SettingsService.get(db, "compose_directory")
                except OperationalError as e:
                    logger.warning(f"Database error fetching compose directory from settings: {e}")
                except (ValueError, KeyError, AttributeError) as e:
                    logger.warning(f"Invalid settings data fetching compose directory: {e}")

            # Validate file path to prevent path traversal
            if not validate_compose_file_path(file_path, allowed_dir):
                logger.error(f"Invalid or unsafe file path: {file_path}")
                return False

            # Load with ruamel.yaml to preserve formatting
            with open(file_path) as f:
                compose_data = yaml.load(f)

            if "services" not in compose_data:
                logger.error(f"No services in {file_path}")
                return False

            if service_name not in compose_data["services"]:
                logger.error(f"Service {service_name} not found in {file_path}")
                return False

            service = compose_data["services"][service_name]
            old_image = service.get("image", "")

            # Update tag in image string
            if ":" in old_image:
                base_image = old_image.rsplit(":", 1)[0]
            else:
                base_image = old_image

            new_image = f"{base_image}:{new_tag}"
            service["image"] = new_image

            # Write back to file with ruamel.yaml (preserves everything)
            with open(file_path, "w") as f:
                yaml.dump(compose_data, f)

            logger.info(f"Updated {service_name} in {file_path}: {old_image} -> {new_image}")
            return True

        except YAMLError as e:
            logger.error(f"YAML parsing/dumping error updating compose file: {e}")
            return False
        except (OSError, PermissionError) as e:
            logger.error(f"File access error updating compose file {file_path}: {e}")
            return False
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid compose data updating file: {e}")
            return False

    @staticmethod
    def extract_health_check_url(compose_file: str, service_name: str) -> str | None:
        """Extract health check URL from compose file by parsing healthcheck + traefik labels.

        Args:
            compose_file: Path to compose file
            service_name: Name of the service

        Returns:
            Detected health check URL or None
        """
        try:
            # Validate service name
            if not validate_container_name(service_name):
                logger.error(f"Invalid service name format: {service_name}")
                return None

            # Validate file path (without allowed_dir since we don't have db context here)
            if not validate_compose_file_path(compose_file):
                logger.error(f"Invalid compose file path: {compose_file}")
                return None

            with open(compose_file) as f:
                compose_data = yaml.load(f)

            if not compose_data or "services" not in compose_data:
                return None

            service_config = compose_data["services"].get(service_name)
            if not service_config or not isinstance(service_config, dict):
                return None

            # Get health check path from healthcheck.test
            healthcheck = service_config.get("healthcheck", {})
            health_path = None

            if isinstance(healthcheck, dict):
                test = healthcheck.get("test")
                if test:
                    # Parse healthcheck test command (e.g., ["CMD", "curl", "-f", "http://localhost:8788/health"])
                    if isinstance(test, list):
                        test_str = " ".join(test)
                    else:
                        test_str = str(test)

                    # Limit input length to prevent ReDoS
                    if len(test_str) > 4096:
                        logger.warning(
                            f"Healthcheck test string too long ({len(test_str)} chars), truncating"
                        )
                        test_str = test_str[:4096]

                    # Extract URL path from curl command with length limits
                    url_match = re.search(r"https?://[^/\s]{1,253}(/[^\s]{0,1000})", test_str)
                    if url_match:
                        health_path = url_match.group(1)
                    else:
                        # Try to extract just the path with bounded repetition
                        path_match = re.search(r"(/[\w/-]{1,500})", test_str)
                        if path_match:
                            health_path = path_match.group(1)

            # Get traefik host from labels
            labels = service_config.get("labels", {})
            if isinstance(labels, list):
                labels = ComposeParser._labels_list_to_dict(labels)

            # Sanitize labels
            labels = ComposeParser._sanitize_labels(labels)

            traefik_host = None
            for label_key, label_value in labels.items():
                # Look for traefik.http.routers.*.rule with Host() directive
                if "traefik.http.routers" in label_key and ".rule" in label_key:
                    host_match = re.search(r"Host\(`([^`]+)`\)", str(label_value))
                    if host_match:
                        traefik_host = host_match.group(1)
                        break

            # Combine host and path
            if traefik_host and health_path:
                return f"https://{traefik_host}{health_path}"
            elif health_path:
                return f"http://localhost{health_path}"

            return None

        except YAMLError as e:
            logger.error(f"YAML parsing error extracting health check URL from {compose_file}: {e}")
            return None
        except (OSError, PermissionError) as e:
            logger.error(f"File access error extracting health check URL from {compose_file}: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(
                f"Invalid compose data extracting health check URL from {compose_file}: {e}"
            )
            return None

    @staticmethod
    def extract_release_source(image: str) -> str | None:
        """Extract GitHub repository from image registry.

        Args:
            image: Docker image string (e.g., ghcr.io/owner/repo:tag, linuxserver/plex)

        Returns:
            GitHub repository (owner/repo) or None
        """
        try:
            # Remove tag if present
            if ":" in image:
                image = image.split(":")[0]

            # Remove registry prefix if present
            if image.startswith("docker.io/"):
                image = image.replace("docker.io/", "")

            # Handle ghcr.io images (GitHub Container Registry)
            if image.startswith("ghcr.io/"):
                # ghcr.io/owner/repo -> owner/repo
                repo_path = image.replace("ghcr.io/", "")
                return repo_path

            # Handle LinuxServer.io images
            if image.startswith("lscr.io/linuxserver/") or image.startswith("linuxserver/"):
                # Extract app name
                app_name = image.split("/")[-1]
                # LinuxServer.io pattern: linuxserver/docker-{app}
                return f"linuxserver/docker-{app_name}"

            # Handle ghcr.io/linuxserver images
            if image.startswith("ghcr.io/linuxserver/"):
                app_name = image.replace("ghcr.io/linuxserver/", "")
                return f"linuxserver/docker-{app_name}"

            # Handle common Docker Hub official images with known GitHub repos
            docker_hub_mappings = {
                # Official images
                "postgres": "postgres/postgres",
                "redis": "redis/redis",
                "nginx": "nginx/nginx",
                "mariadb": "MariaDB/server",
                "mysql": "mysql/mysql-server",
                "mongo": "mongodb/mongo",
                "elasticsearch": "elastic/elasticsearch",
                # Traefik / Reverse proxies
                "traefik": "traefik/traefik",
                "traefik/traefik": "traefik/traefik",
                "caddy": "caddyserver/caddy",
                # Grafana stack
                "grafana/grafana": "grafana/grafana",
                "grafana/loki": "grafana/loki",
                "grafana/promtail": "grafana/promtail",
                "grafana/alloy": "grafana/alloy",
                "grafana/tempo": "grafana/tempo",
                "grafana/mimir": "grafana/mimir",
                # Prometheus stack
                "prom/prometheus": "prometheus/prometheus",
                "prom/node-exporter": "prometheus/node_exporter",
                "prom/alertmanager": "prometheus/alertmanager",
                "prom/pushgateway": "prometheus/pushgateway",
                # VictoriaMetrics
                "victoriametrics/victoria-metrics": "VictoriaMetrics/VictoriaMetrics",
                "victoriametrics/vmagent": "VictoriaMetrics/VictoriaMetrics",
                "victoriametrics/vmalert": "VictoriaMetrics/VictoriaMetrics",
                "victoriametrics/vmauth": "VictoriaMetrics/VictoriaMetrics",
                # Authentication
                "goauthentik/server": "goauthentik/authentik",
                "goauthentik/proxy": "goauthentik/authentik",
                "authelia/authelia": "authelia/authelia",
                # DNS / Ad blocking
                "adguard/adguardhome": "AdguardTeam/AdGuardHome",
                "pihole/pihole": "pi-hole/docker-pi-hole",
                # Home automation
                "homeassistant/home-assistant": "home-assistant/core",
                # Media
                "chromadb/chroma": "chroma-core/chroma",
                "qdrant/qdrant": "qdrant/qdrant",
                "milvusdb/milvus": "milvus-io/milvus",
                # AI/ML
                "ollama/ollama": "ollama/ollama",
                # Backup
                "kopia/kopia": "kopia/kopia",
                "restic/restic": "restic/restic",
                # Arr stack (handled by linuxserver usually, but just in case)
                "hotio/sonarr": "Sonarr/Sonarr",
                "hotio/radarr": "Radarr/Radarr",
                "hotio/lidarr": "Lidarr/Lidarr",
                "hotio/prowlarr": "Prowlarr/Prowlarr",
                # Security
                "crowdsecurity/crowdsec": "crowdsecurity/crowdsec",
                # Misc
                "portainer/portainer-ce": "portainer/portainer",
                "containrrr/watchtower": "containrrr/watchtower",
                "dpage/pgadmin4": "pgadmin-org/pgadmin4",
                "louislam/uptime-kuma": "louislam/uptime-kuma",
                "nicolargo/glances": "nicolargo/glances",
                "netdata/netdata": "netdata/netdata",
                "ghcr.io/open-webui/open-webui": "open-webui/open-webui",
            }

            # Check if image matches known mapping
            if image in docker_hub_mappings:
                return docker_hub_mappings[image]

            # For other Docker Hub images with owner/repo format, assume GitHub has same path
            if "/" in image and not image.startswith(("lscr.io/", "ghcr.io/")):
                # Format: owner/repo (e.g., grafana/grafana)
                return image

            # Unable to detect
            return None

        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.error(f"Invalid image format extracting release source from '{image}': {e}")
            return None
