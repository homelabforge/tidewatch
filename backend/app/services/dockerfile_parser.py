"""Service for parsing Dockerfiles and tracking base image dependencies."""

import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.dockerfile_dependency import DockerfileDependency
from app.utils.security import sanitize_log_message, sanitize_path

logger = logging.getLogger(__name__)


class DockerfileParser:
    """Parser for analyzing Dockerfiles and extracting base image dependencies."""

    def __init__(self, projects_directory: str = "/projects"):
        # Validate projects directory path to prevent path traversal
        # Allowed base directories: /projects (production), /tmp (tests), /srv/raid0/docker/build (homelab)
        try:
            if projects_directory.startswith("/projects"):
                self.projects_directory = sanitize_path(
                    projects_directory, "/projects", allow_symlinks=False
                )
            elif projects_directory.startswith("/tmp"):
                self.projects_directory = sanitize_path(
                    projects_directory, "/tmp", allow_symlinks=False
                )
            elif projects_directory.startswith("/srv/raid0/docker/build"):
                self.projects_directory = sanitize_path(
                    projects_directory, "/srv/raid0/docker/build", allow_symlinks=False
                )
            else:
                logger.warning(
                    f"Projects directory outside allowed paths: {sanitize_log_message(projects_directory)}"
                )
                # Fall back to default
                self.projects_directory = Path("/projects").resolve()
        except (ValueError, FileNotFoundError) as e:
            logger.error(
                f"Invalid projects directory path: {sanitize_log_message(str(e))}"
            )
            # Fall back to default
            self.projects_directory = Path("/projects").resolve()

    async def scan_container_dockerfile(
        self,
        session: AsyncSession,
        container: Container,
        manual_dockerfile_path: str | None = None,
    ) -> list[DockerfileDependency]:
        """
        Scan a container's Dockerfile for base image dependencies.

        Args:
            session: Database session
            container: Container model instance
            manual_dockerfile_path: Optional manual path to Dockerfile

        Returns:
            List of discovered Dockerfile dependencies
        """
        try:
            # Find Dockerfile
            dockerfile_path = await self._find_dockerfile(
                container, manual_dockerfile_path
            )
            if not dockerfile_path:
                logger.warning(
                    f"Could not find Dockerfile for container {sanitize_log_message(str(container.name))}"
                )
                return []

            # Parse Dockerfile
            dependencies = await self._parse_dockerfile(dockerfile_path, container.id)

            # Check for updates on each dependency
            for dep in dependencies:
                await self._check_for_updates(dep)

            # Save dependencies to database
            await self._save_dependencies(session, container.id, dependencies)

            logger.info(
                f"Scanned Dockerfile for {sanitize_log_message(str(container.name))}: found {sanitize_log_message(str(len(dependencies)))} dependencies"
            )
            return dependencies

        except (OSError, PermissionError) as e:
            logger.error(
                f"File system error scanning Dockerfile for {sanitize_log_message(str(container.name))}: {sanitize_log_message(str(e))}"
            )
            return []
        except OperationalError as e:
            logger.error(
                f"Database error scanning Dockerfile for {sanitize_log_message(str(container.name))}: {sanitize_log_message(str(e))}"
            )
            return []
        except (ValueError, KeyError) as e:
            logger.error(
                f"Invalid data scanning Dockerfile for {sanitize_log_message(str(container.name))}: {sanitize_log_message(str(e))}"
            )
            return []

    async def _find_dockerfile(
        self, container: Container, manual_path: str | None
    ) -> Path | None:
        """
        Find the Dockerfile for a container.

        Search order:
        1. Manual path if provided
        2. Same directory as compose file
        3. Project root directory
        4. Common Dockerfile locations (docker/, build/, etc.)
        """
        if manual_path:
            # Validate manual_path to prevent path traversal
            try:
                dockerfile = sanitize_path(manual_path, "/", allow_symlinks=False)
                if dockerfile.exists():
                    return dockerfile
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    f"Invalid manual Dockerfile path: {sanitize_log_message(manual_path)} - {sanitize_log_message(str(e))}"
                )
                # Fall through to automatic search

        # Get project root from compose file
        compose_path = Path(container.compose_file)

        # Try common locations
        search_paths = [
            compose_path.parent / "Dockerfile",  # Same dir as compose
            compose_path.parent / "docker" / "Dockerfile",  # docker/ subdirectory
            compose_path.parent / "build" / "Dockerfile",  # build/ subdirectory
            compose_path.parent / ".." / "Dockerfile",  # Parent directory
        ]

        # If using projects directory, also search there
        if str(compose_path).startswith("/compose/"):
            project_name = compose_path.stem
            project_root = self.projects_directory / project_name
            search_paths.extend(
                [
                    project_root / "Dockerfile",
                    project_root / "docker" / "Dockerfile",
                    project_root / "build" / "Dockerfile",
                ]
            )

        for path in search_paths:
            if path.exists() and path.is_file():
                # Validate that the resolved path is safe (no traversal outside expected directories)
                try:
                    resolved = path.resolve()
                    # Ensure path is under a safe directory (/compose, /projects, or compose_path parent)
                    safe_parents = [
                        Path("/compose").resolve(),
                        self.projects_directory.resolve(),
                        compose_path.parent.resolve(),
                    ]
                    if any(
                        str(resolved).startswith(str(parent)) for parent in safe_parents
                    ):
                        return path
                    else:
                        logger.warning(
                            f"Dockerfile path outside safe directories, skipping: {sanitize_log_message(str(resolved))}"
                        )
                except (OSError, RuntimeError) as e:
                    logger.warning(
                        f"Could not validate Dockerfile path {sanitize_log_message(str(path))}: {sanitize_log_message(str(e))}"
                    )
                    continue

        return None

    async def _parse_dockerfile(
        self, dockerfile_path: Path, container_id: int
    ) -> list[DockerfileDependency]:
        """
        Parse Dockerfile and extract FROM statements.

        Returns:
            List of DockerfileDependency objects (not yet saved to DB)
        """
        dependencies = []

        try:
            with open(dockerfile_path) as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, start=1):
                # Remove comments and whitespace
                line = line.split("#")[0].strip()

                if not line:
                    continue

                # Match FROM statements (including multi-stage builds)
                # Examples:
                #   FROM node:22-alpine
                #   FROM node:22-alpine AS builder
                #   FROM python:3.14-slim
                match = re.match(
                    r"^FROM\s+([^\s]+)(?:\s+AS\s+([^\s]+))?", line, re.IGNORECASE
                )

                if match:
                    full_image = match.group(1)
                    stage_name = match.group(2)

                    # Skip scratch and platform-specific syntax
                    if full_image.lower() == "scratch":
                        continue

                    # Parse image reference
                    image_name, tag, registry = self._parse_image_reference(full_image)

                    # Determine dependency type
                    dependency_type = "build_image" if stage_name else "base_image"

                    dep = DockerfileDependency(
                        container_id=container_id,
                        dependency_type=dependency_type,
                        image_name=image_name,
                        current_tag=tag,
                        registry=registry,
                        full_image=full_image,
                        dockerfile_path=str(
                            dockerfile_path.relative_to(dockerfile_path.parent.parent)
                        ),
                        line_number=line_num,
                        stage_name=stage_name,
                        update_available=False,
                        severity="info",
                        last_checked=None,
                    )
                    dependencies.append(dep)

        except (OSError, PermissionError) as e:
            logger.error(
                f"File system error parsing Dockerfile {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
        except UnicodeDecodeError as e:
            logger.error(
                f"Encoding error parsing Dockerfile {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, AttributeError) as e:
            logger.error(
                f"Invalid Dockerfile content at {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )

        return dependencies

    def _parse_image_reference(self, full_image: str) -> tuple[str, str, str]:
        """
        Parse a Docker image reference into components.

        Examples:
            "node:22-alpine" -> ("node", "22-alpine", "docker.io")
            "python:3.14-slim" -> ("python", "3.14-slim", "docker.io")
            "ghcr.io/owner/image:tag" -> ("owner/image", "tag", "ghcr.io")

        Returns:
            Tuple of (image_name, tag, registry)
        """
        # Default values
        registry = "docker.io"
        tag = "latest"

        # Check if registry is specified (contains / before :)
        if "/" in full_image.split(":")[0]:
            parts = full_image.split("/", 1)
            if "." in parts[0] or parts[0] == "localhost":
                registry = parts[0]
                full_image = parts[1]

        # Split image and tag
        if ":" in full_image:
            image_name, tag = full_image.rsplit(":", 1)
        else:
            image_name = full_image
            tag = "latest"

        # Remove registry from image_name if it's still there
        if registry != "docker.io" and registry in image_name:
            image_name = image_name.replace(f"{registry}/", "")

        return image_name, tag, registry

    async def _check_for_updates(self, dependency: DockerfileDependency) -> None:
        """
        Check if a newer version of the base image is available.

        This uses the existing registry client to check for updates.
        """
        try:
            from app.services.registry_client import RegistryClientFactory

            # Mark as checked
            dependency.last_checked = datetime.now()

            # Get appropriate registry client
            factory = RegistryClientFactory()
            client = await factory.get_client(dependency.registry)
            async with client:
                # Query for latest tag
                # For base images, we use 'major' scope to catch all version updates
                # (e.g., node:22 -> node:25, python:3.14 -> python:3.15)
                latest_tag = await client.get_latest_tag(
                    image=dependency.image_name,
                    current_tag=dependency.current_tag,
                    scope="major",  # Check for major updates to catch all newer versions
                    include_prereleases=False,  # Don't include alpha/beta/rc for base images
                )

                if latest_tag and latest_tag != dependency.current_tag:
                    dependency.latest_tag = latest_tag
                    dependency.update_available = True
                    dependency.severity = self._calculate_severity(
                        dependency.current_tag, latest_tag
                    )
                    logger.info(
                        f"Update available for {dependency.full_image}: "
                        f"{dependency.current_tag} → {latest_tag}"
                    )
                else:
                    dependency.latest_tag = dependency.current_tag
                    dependency.update_available = False
                    dependency.severity = "info"

        except (ValueError, KeyError, AttributeError) as e:
            logger.error(
                f"Invalid data checking updates for {sanitize_log_message(str(dependency.full_image))}: {sanitize_log_message(str(e))}"
            )
            # Still mark as checked even if error occurred
            dependency.update_available = False
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(
                f"Missing module checking updates for {sanitize_log_message(str(dependency.full_image))}: {sanitize_log_message(str(e))}"
            )
            dependency.update_available = False

    async def _save_dependencies(
        self,
        session: AsyncSession,
        container_id: int,
        dependencies: list[DockerfileDependency],
    ) -> None:
        """
        Save Dockerfile dependencies to the database.

        Updates existing dependencies while preserving ignored status.
        Creates new dependencies if they don't exist.
        Removes dependencies that are no longer in the Dockerfile.
        """
        try:
            # Get existing dependencies for this container
            result = await session.execute(
                select(DockerfileDependency).where(
                    DockerfileDependency.container_id == container_id
                )
            )
            existing_deps = {
                (
                    dep.image_name,
                    dep.dockerfile_path,
                    dep.line_number,
                    dep.stage_name,
                ): dep
                for dep in result.scalars().all()
            }

            # Track which existing deps we've seen
            seen_keys = set()

            # Update or create each new dependency
            for new_dep in dependencies:
                key = (
                    new_dep.image_name,
                    new_dep.dockerfile_path,
                    new_dep.line_number,
                    new_dep.stage_name,
                )
                seen_keys.add(key)

                if key in existing_deps:
                    # Update existing dependency while preserving ignored status
                    existing = existing_deps[key]

                    # Update version and availability info
                    existing.current_tag = new_dep.current_tag
                    existing.latest_tag = new_dep.latest_tag
                    existing.update_available = new_dep.update_available
                    existing.severity = new_dep.severity
                    existing.last_checked = new_dep.last_checked
                    existing.registry = new_dep.registry
                    existing.full_image = new_dep.full_image
                    existing.dependency_type = new_dep.dependency_type

                    # PRESERVE ignored fields - only reset ignore if version has moved past ignored version
                    if existing.ignored and existing.ignored_version:
                        # If the latest version has changed beyond what was ignored, clear the ignore
                        if new_dep.latest_tag != existing.ignored_version:
                            logger.info(
                                f"Clearing ignore for {existing.image_name} - "
                                f"new version {new_dep.latest_tag} available (was ignoring {existing.ignored_version})"
                            )
                            existing.ignored = False
                            existing.ignored_version = None
                            existing.ignored_by = None
                            existing.ignored_at = None
                            existing.ignored_reason = None

                    logger.debug(
                        f"Updated existing dependency: {sanitize_log_message(str(existing.image_name))} at line {sanitize_log_message(str(existing.line_number))}"
                    )
                else:
                    # Add new dependency
                    session.add(new_dep)
                    logger.debug(
                        f"Created new dependency: {sanitize_log_message(str(new_dep.image_name))} at line {sanitize_log_message(str(new_dep.line_number))}"
                    )

            # Remove dependencies that are no longer in the Dockerfile
            for key, existing in existing_deps.items():
                if key not in seen_keys:
                    logger.debug(
                        f"Removing old dependency: {sanitize_log_message(str(existing.image_name))} at line {sanitize_log_message(str(existing.line_number))}"
                    )
                    await session.delete(existing)

            await session.commit()

        except IntegrityError as e:
            await session.rollback()
            logger.error(
                f"Database constraint violation saving dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
            )
            raise
        except OperationalError as e:
            await session.rollback()
            logger.error(
                f"Database error saving dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
            )
            raise

    async def get_container_dockerfile_dependencies(
        self, session: AsyncSession, container_id: int
    ) -> list[DockerfileDependency]:
        """
        Get all Dockerfile dependencies for a container.

        Args:
            session: Database session
            container_id: Container ID

        Returns:
            List of Dockerfile dependencies
        """
        result = await session.execute(
            select(DockerfileDependency)
            .where(DockerfileDependency.container_id == container_id)
            .order_by(DockerfileDependency.line_number)
        )
        return list(result.scalars().all())

    async def get_all_dockerfile_dependencies(
        self, session: AsyncSession
    ) -> dict[int, list[DockerfileDependency]]:
        """
        Get all Dockerfile dependencies grouped by container.

        Returns:
            Dictionary mapping container_id to list of dependencies
        """
        result = await session.execute(
            select(DockerfileDependency).order_by(
                DockerfileDependency.container_id, DockerfileDependency.line_number
            )
        )

        dependencies_by_container = {}
        for dep in result.scalars().all():
            if dep.container_id not in dependencies_by_container:
                dependencies_by_container[dep.container_id] = []
            dependencies_by_container[dep.container_id].append(dep)

        return dependencies_by_container

    async def check_all_for_updates(self, session: AsyncSession) -> dict[str, int]:
        """
        Check all Dockerfile dependencies for updates.

        Returns:
            Dictionary with scan statistics
        """
        stats = {"total_scanned": 0, "updates_found": 0, "errors": 0}

        try:
            # Get all dependencies
            result = await session.execute(select(DockerfileDependency))
            dependencies = list(result.scalars().all())

            for dep in dependencies:
                try:
                    await self._check_for_updates(dep)
                    stats["total_scanned"] += 1
                    if dep.update_available:
                        stats["updates_found"] += 1
                except (ValueError, KeyError, AttributeError) as e:
                    logger.error(
                        f"Invalid data checking dependency {sanitize_log_message(str(dep.id))}: {sanitize_log_message(str(e))}"
                    )
                    stats["errors"] += 1
                except (ImportError, ModuleNotFoundError) as e:
                    logger.error(
                        f"Missing module checking dependency {sanitize_log_message(str(dep.id))}: {sanitize_log_message(str(e))}"
                    )
                    stats["errors"] += 1

            # Save all updates
            await session.commit()

            logger.info(
                f"Dockerfile dependency update check complete: "
                f"{stats['total_scanned']} scanned, {stats['updates_found']} updates found"
            )

        except OperationalError as e:
            await session.rollback()
            logger.error(
                f"Database error in bulk update check: {sanitize_log_message(str(e))}"
            )
            raise
        except (ValueError, AttributeError) as e:
            await session.rollback()
            logger.error(
                f"Invalid data in bulk update check: {sanitize_log_message(str(e))}"
            )
            raise

        return stats

    def _calculate_severity(self, current_tag: str, latest_tag: str) -> str:
        """Calculate severity of update based on semver difference.

        Args:
            current_tag: Current image tag (e.g., "22-alpine", "3.14-slim")
            latest_tag: Latest available tag

        Returns:
            Severity level: "medium" (major), "low" (minor), "info" (patch)
        """
        try:
            # Extract version numbers from tags (strip common suffixes)
            def extract_version(tag: str) -> list[int]:
                # Remove common suffixes like -alpine, -slim, -bookworm, etc.
                version_str = tag.split("-")[0].lstrip("v")
                # Parse version parts
                parts = [int(x) for x in version_str.split(".")[:3]]
                # Pad to 3 parts
                while len(parts) < 3:
                    parts.append(0)
                return parts

            current_parts = extract_version(current_tag)
            latest_parts = extract_version(latest_tag)

            # Major version change (breaking changes expected per semver)
            if latest_parts[0] > current_parts[0]:
                return "high"  # Maps to "Major Update" in UI
            # Minor version change (backwards-compatible features)
            elif latest_parts[1] > current_parts[1]:
                return "low"  # Maps to "Minor Update" in UI
            # Patch version change (backwards-compatible bug fixes)
            else:
                return "info"  # Maps to "Patch Update" in UI
        except (ValueError, IndexError, AttributeError):
            # If we can't parse versions, default to info
            return "info"

    @staticmethod
    def update_from_instruction(
        dockerfile_path: Path,
        image_name: str,
        new_tag: str,
        line_number: int | None = None,
        stage_name: str | None = None,
    ) -> tuple[bool, str]:
        """
        Update FROM instruction in Dockerfile.

        Args:
            dockerfile_path: Path to Dockerfile
            image_name: Image name (e.g., "python", "node")
            new_tag: New tag to use (e.g., "3.15-slim")
            line_number: Specific line number to target (optional)
            stage_name: Stage name for multi-stage builds (optional)

        Returns:
            Tuple of (success: bool, updated_content: str)
        """
        try:
            with open(dockerfile_path, encoding="utf-8") as f:
                lines = f.readlines()

            updated = False
            for i, line in enumerate(lines, start=1):
                # Skip if line number specified and this isn't it
                if line_number and i != line_number:
                    continue

                # Check if this is a FROM instruction for our image
                match = re.match(
                    r"^(FROM\s+)([^\s:]+):?([^\s]+)?(\s+AS\s+([^\s]+))?(.*)$",
                    line,
                    re.IGNORECASE,
                )

                if match:
                    current_image = match.group(2)
                    current_stage = match.group(5)

                    # Check if this matches our target
                    if current_image == image_name:
                        # If stage_name specified, verify it matches
                        if stage_name and current_stage != stage_name:
                            continue

                        # Build new FROM line preserving formatting
                        new_line = f"{match.group(1)}{image_name}:{new_tag}"
                        if current_stage:
                            new_line += f" AS {current_stage}"
                        new_line += match.group(6)  # Any trailing content
                        new_line += "\n"

                        lines[i - 1] = new_line
                        updated = True

                        # If line number was specified, we're done
                        if line_number:
                            break

            if not updated:
                logger.warning(
                    f"Could not find FROM instruction for {image_name} "
                    f"in {dockerfile_path} (line: {line_number}, stage: {stage_name})"
                )
                return False, ""

            return True, "".join(lines)

        except (OSError, PermissionError) as e:
            logger.error(
                f"File system error updating Dockerfile {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
            return False, ""
        except UnicodeDecodeError as e:
            logger.error(
                f"Encoding error updating Dockerfile {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
            return False, ""

    @staticmethod
    def update_label_value(
        dockerfile_path: Path, label_key: str, new_value: str
    ) -> tuple[bool, str]:
        """
        Update LABEL value in Dockerfile (e.g., for HTTP server version).

        Supports formats:
        - LABEL http.server.version="2.6.0"
        - LABEL http.server.version "2.6.0"

        Args:
            dockerfile_path: Path to Dockerfile
            label_key: Label key to update (e.g., "http.server.version")
            new_value: New value for label

        Returns:
            Tuple of (success: bool, updated_content: str)
        """
        try:
            with open(dockerfile_path, encoding="utf-8") as f:
                lines = f.readlines()

            updated = False
            for i, line in enumerate(lines):
                # Match LABEL instructions with this key
                # Handles: LABEL key="value" or LABEL key "value"
                pattern = rf'^(LABEL\s+{re.escape(label_key)}\s*=?\s*["\']?)([^"\'\s]+)(["\']?.*)$'
                match = re.match(pattern, line, re.IGNORECASE)

                if match:
                    # Preserve quoting style
                    prefix = match.group(1)
                    suffix = match.group(3)

                    # Build new line
                    new_line = f"{prefix}{new_value}{suffix}\n"
                    lines[i] = new_line
                    updated = True
                    break  # Only update first match

            if not updated:
                logger.warning(f"Could not find LABEL {label_key} in {dockerfile_path}")
                return False, ""

            return True, "".join(lines)

        except (OSError, PermissionError) as e:
            logger.error(
                f"File system error updating Dockerfile label {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
            return False, ""
        except UnicodeDecodeError as e:
            logger.error(
                f"Encoding error updating Dockerfile label {sanitize_log_message(str(dockerfile_path))}: {sanitize_log_message(str(e))}"
            )
            return False, ""
