"""Docker Compose file parser for discovering containers."""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from ruamel.yaml import YAML, YAMLError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from app.models.container import Container
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_path, sanitize_log_message

logger = logging.getLogger(__name__)

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


def validate_compose_file_path(
    file_path: str, allowed_base_dir: Optional[str] = None
) -> bool:
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
    async def discover_containers(db: AsyncSession) -> List[Container]:
        """Discover all containers from compose files.

        Args:
            db: Database session

        Returns:
            List of Container objects discovered
        """
        compose_dir = await SettingsService.get(db, "compose_directory")
        if not compose_dir:
            logger.warning("Compose directory not configured")
            return []

        # Validate compose directory path to prevent path traversal
        # Allowed base directories: /compose (production), /tmp (tests), /srv/raid0/docker/compose (homelab)
        try:
            if compose_dir.startswith("/compose"):
                validated_dir = sanitize_path(
                    compose_dir, "/compose", allow_symlinks=False
                )
            elif compose_dir.startswith("/tmp"):
                validated_dir = sanitize_path(compose_dir, "/tmp", allow_symlinks=False)
            elif compose_dir.startswith("/srv/raid0/docker/compose"):
                validated_dir = sanitize_path(
                    compose_dir, "/srv/raid0/docker/compose", allow_symlinks=False
                )
            else:
                logger.warning(
                    f"Compose directory outside allowed paths: {sanitize_log_message(compose_dir)}"
                )
                return []

            if not validated_dir.exists():
                logger.warning(f"Compose directory not found: {validated_dir}")
                return []

        except (ValueError, FileNotFoundError) as e:
            logger.error(
                f"Invalid compose directory path: {sanitize_log_message(str(e))}"
            )
            return []

        containers = []
        compose_files = list(validated_dir.glob("*.yml")) + list(
            validated_dir.glob("*.yaml")
        )

        logger.info(f"Found {len(compose_files)} compose files in {compose_dir}")

        for compose_file in compose_files:
            try:
                file_containers = await ComposeParser._parse_compose_file(
                    str(compose_file), db
                )
                containers.extend(file_containers)
            except YAMLError as e:
                logger.error(f"YAML parsing error in {compose_file}: {e}")
            except (OSError, PermissionError) as e:
                logger.error(f"File access error for {compose_file}: {e}")
            except OperationalError as e:
                logger.error(f"Database error parsing {compose_file}: {e}")
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid compose data in {compose_file}: {e}")

        logger.info(f"Discovered {len(containers)} containers total")
        return containers

    @staticmethod
    async def _parse_compose_file(file_path: str, db: AsyncSession) -> List[Container]:
        """Parse a single compose file.

        Args:
            file_path: Path to compose file
            db: Database session

        Returns:
            List of Container objects from this file
        """
        containers = []

        with open(file_path, "r") as f:
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
                logger.warning(
                    f"Invalid container name '{service_name}', skipping for security"
                )
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
            policy = policy_label or "manual"
            scope_label = labels.get("tidewatch.scope")
            scope = scope_label or "patch"
            vulnforge_label = labels.get("tidewatch.vulnforge")
            vulnforge_enabled = (
                vulnforge_label.lower() == "true"
                if isinstance(vulnforge_label, str)
                else True
            )
            prereleases_label = labels.get("tidewatch.include_prereleases")
            include_prereleases = (
                prereleases_label.lower() == "true"
                if isinstance(prereleases_label, str)
                else False
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

            # Create container object
            container = Container(
                name=service_name,
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
            container.__dict__["_prereleases_from_compose"] = (
                prereleases_label is not None
            )
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
    def _parse_image_string(image: str) -> Optional[tuple[str, str, str]]:
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
    def _labels_list_to_dict(labels: List[str]) -> Dict[str, str]:
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
    def _sanitize_labels(labels: Dict[str, any]) -> Dict[str, str]:
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
        MAX_LABELS = 100  # Prevent DoS via too many labels
        MAX_KEY_LENGTH = 255  # Docker limit for label keys
        MAX_VALUE_LENGTH = 4096  # Reasonable limit for label values

        # Sort keys to ensure consistent processing
        for key in sorted(labels.keys())[:MAX_LABELS]:
            # Validate key format (alphanumeric, dots, hyphens, underscores)
            if not isinstance(key, str):
                logger.warning(f"Skipping non-string label key: {type(key)}")
                continue

            # Save original key before any modifications
            original_key = key

            # Enforce key length limit
            if len(key) > MAX_KEY_LENGTH:
                logger.warning(
                    f"Label key too long ({len(key)} chars), truncating: {key[:50]}..."
                )
                key = key[:MAX_KEY_LENGTH]

            # Docker labels allow: [a-zA-Z0-9._-]
            # We'll be more permissive but log suspicious patterns
            if any(char in key for char in ["\n", "\r", "\0", "\x00"]):
                logger.warning(
                    f"Skipping label with control characters in key: {key[:50]}"
                )
                continue

            # Convert value to string and enforce length limit (use original key)
            value = str(labels[original_key])
            if len(value) > MAX_VALUE_LENGTH:
                logger.warning(
                    f"Label value too long ({len(value)} chars), truncating for key: {key}"
                )
                value = value[:MAX_VALUE_LENGTH]

            # Filter control characters from value
            if any(char in value for char in ["\0", "\x00"]):
                logger.warning(f"Filtering null bytes from label value for key: {key}")
                value = value.replace("\0", "").replace("\x00", "")

            sanitized[key] = value

        if len(labels) > MAX_LABELS:
            logger.warning(
                f"Too many labels ({len(labels)}), only processing first {MAX_LABELS}"
            )

        return sanitized

    @staticmethod
    def _extract_healthcheck_url(health_config, service_name: str) -> Optional[str]:
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
                logger.warning(
                    f"Healthcheck candidate too long ({len(candidate)} chars), skipping"
                )
                continue

            match = url_pattern.search(candidate)
            if match:
                return ComposeParser._normalize_healthcheck_url(
                    match.group(0), service_name
                )

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
        except Exception:
            pass
        return url

    @staticmethod
    def _normalize_health_check_method(value: Optional[str]) -> str:
        """Validate requested health check method."""
        if not value:
            return "auto"

        method = value.strip().lower()
        if method in {"auto", "http", "docker"}:
            return method

        logger.warning(
            f"Unknown tidewatch health check method '{value}', defaulting to auto"
        )
        return "auto"

    @staticmethod
    async def sync_containers(db: AsyncSession) -> Dict[str, int]:
        """Sync discovered containers with database.

        This will:
        - Add new containers
        - Update existing containers if changed
        - Mark missing containers (optional)

        Args:
            db: Database session

        Returns:
            Stats dict with counts
        """
        discovered = await ComposeParser.discover_containers(db)

        stats = {
            "added": 0,
            "updated": 0,
            "unchanged": 0,
            "total": len(discovered),
        }

        for container in discovered:
            # Check if container exists
            result = await db.execute(
                select(Container).where(Container.name == container.name)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                # Add new container
                db.add(container)
                stats["added"] += 1
                logger.info(f"Added new container: {container.name}")
            else:
                # Update if changed
                changed = False

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
                    stats["updated"] += 1
                    logger.info(f"Updated container: {container.name}")
                else:
                    stats["unchanged"] += 1

        await db.commit()
        logger.info(
            f"Container sync complete: {stats['added']} added, "
            f"{stats['updated']} updated, {stats['unchanged']} unchanged"
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

        return stats

    @staticmethod
    async def _sync_restart_policies(
        db: AsyncSession, discovered: List[Container]
    ) -> None:
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
            restart_policy = await DockerStatsService.get_restart_policy(container.name)

            # Update if different
            if container.restart_policy != restart_policy:
                container.restart_policy = restart_policy
                logger.debug(
                    f"Updated restart policy for {container.name}: {restart_policy}"
                )

    @staticmethod
    async def _sync_compose_projects(db: AsyncSession) -> None:
        """Sync Docker Compose project names from container labels to database.

        Docker Compose automatically adds a 'com.docker.compose.project' label
        to each container. This method extracts that label and stores it in the
        database so TideWatch can use the correct -p flag when running commands.

        Args:
            db: Database session
        """
        try:
            import docker

            client = docker.from_env()
        except Exception as e:
            logger.warning(f"Could not connect to Docker for compose project sync: {e}")
            return

        # Get all containers from database
        result = await db.execute(select(Container))
        all_containers = result.scalars().all()

        for container in all_containers:
            # Skip if already has compose_project set
            if container.compose_project:
                continue

            try:
                docker_container = client.containers.get(container.name)
                compose_project = docker_container.labels.get(
                    "com.docker.compose.project"
                )

                if compose_project and container.compose_project != compose_project:
                    container.compose_project = compose_project
                    logger.info(
                        f"Set compose_project={compose_project} for {container.name}"
                    )
            except docker.errors.NotFound:
                logger.debug(
                    f"Container {container.name} not running, skipping project sync"
                )
            except Exception as e:
                logger.debug(f"Could not get compose project for {container.name}: {e}")

    @staticmethod
    async def _cleanup_stale_updates(
        db: AsyncSession, discovered: List[Container]
    ) -> None:
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
    async def _detect_stale_containers(
        db: AsyncSession, discovered: List[Container]
    ) -> None:
        """Detect containers in database that are no longer in compose files.

        Creates Update records with reason_type="stale" for containers that
        haven't been found in compose files and exceed the threshold.

        Args:
            db: Database session
            discovered: List of containers discovered from compose files
        """
        from app.models.update import Update
        from datetime import datetime, timedelta, timezone

        # Check if stale detection is enabled
        enabled = await SettingsService.get_bool(
            db, "stale_detection_enabled", default=True
        )
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

        # Build set of discovered container names for quick lookup
        discovered_names = {c.name for c in discovered}

        # Current time for comparisons
        now = datetime.now(timezone.utc)
        threshold = timedelta(days=threshold_days)

        for container in all_containers:
            # Skip if container is in compose files
            if container.name in discovered_names:
                continue

            # Exclude dev containers if configured
            if exclude_dev and container.name.endswith("-dev"):
                logger.debug(f"Skipping dev container: {container.name}")
                continue

            # Calculate how long it's been missing
            created_at = container.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

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
                logger.debug(
                    f"Container {container.name} already has stale notification"
                )
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
        db: Optional[AsyncSession] = None,
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
                    logger.warning(
                        f"Database error fetching compose directory from settings: {e}"
                    )
                except (ValueError, KeyError, AttributeError) as e:
                    logger.warning(
                        f"Invalid settings data fetching compose directory: {e}"
                    )

            # Validate file path to prevent path traversal
            if not validate_compose_file_path(file_path, allowed_dir):
                logger.error(f"Invalid or unsafe file path: {file_path}")
                return False

            # Load with ruamel.yaml to preserve formatting
            with open(file_path, "r") as f:
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

            logger.info(
                f"Updated {service_name} in {file_path}: {old_image} -> {new_image}"
            )
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
    def extract_health_check_url(compose_file: str, service_name: str) -> Optional[str]:
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

            with open(compose_file, "r") as f:
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
                    url_match = re.search(
                        r"https?://[^/\s]{1,253}(/[^\s]{0,1000})", test_str
                    )
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
            logger.error(
                f"YAML parsing error extracting health check URL from {compose_file}: {e}"
            )
            return None
        except (OSError, PermissionError) as e:
            logger.error(
                f"File access error extracting health check URL from {compose_file}: {e}"
            )
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(
                f"Invalid compose data extracting health check URL from {compose_file}: {e}"
            )
            return None

    @staticmethod
    def extract_release_source(image: str) -> Optional[str]:
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
            if image.startswith("lscr.io/linuxserver/") or image.startswith(
                "linuxserver/"
            ):
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
            logger.error(
                f"Invalid image format extracting release source from '{image}': {e}"
            )
            return None
