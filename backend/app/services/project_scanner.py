"""Service for scanning and discovering dev containers in projects directory."""

import logging
from pathlib import Path
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from ruamel.yaml import YAML, YAMLError

from app.models import Container
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_path, sanitize_log_message

logger = logging.getLogger(__name__)


class ProjectScanner:
    """Scanner for auto-discovering dev containers in projects directory."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def scan_projects_directory(self) -> Dict[str, any]:
        """
        Scan projects directory for dev containers.

        Returns:
            Dictionary with scan results (added, updated, skipped counts)
        """
        # Get settings
        projects_dir = await SettingsService.get(self.db, "projects_directory")
        enabled = await SettingsService.get(self.db, "my_projects_enabled")
        auto_scan = await SettingsService.get(self.db, "my_projects_auto_scan")

        if not enabled or enabled.lower() != "true":
            logger.info("My Projects feature is disabled")
            return {"added": 0, "updated": 0, "skipped": 0, "error": "Feature disabled"}

        if not auto_scan or auto_scan.lower() != "true":
            logger.info("My Projects auto-scan is disabled")
            return {"added": 0, "updated": 0, "skipped": 0, "error": "Auto-scan disabled"}

        if not projects_dir:
            projects_dir = "/projects"

        # Validate projects directory path to prevent path traversal
        # Allowed base directories: /projects (production), /tmp (tests), /srv/raid0/docker/build (homelab)
        try:
            if projects_dir.startswith("/projects"):
                projects_path = sanitize_path(projects_dir, "/projects", allow_symlinks=False)
            elif projects_dir.startswith("/tmp"):
                projects_path = sanitize_path(projects_dir, "/tmp", allow_symlinks=False)
            elif projects_dir.startswith("/srv/raid0/docker/build"):
                projects_path = sanitize_path(projects_dir, "/srv/raid0/docker/build", allow_symlinks=False)
            else:
                logger.warning(f"Projects directory outside allowed paths: {sanitize_log_message(projects_dir)}")
                return {"added": 0, "updated": 0, "skipped": 0, "error": "Invalid directory path"}

            if not projects_path.exists():
                logger.warning(f"Projects directory does not exist: {projects_path}")
                return {"added": 0, "updated": 0, "skipped": 0, "error": f"Directory not found: {projects_path}"}

        except (ValueError, FileNotFoundError) as e:
            logger.error(f"Invalid projects directory path: {sanitize_log_message(str(e))}")
            return {"added": 0, "updated": 0, "skipped": 0, "error": f"Invalid directory path: {str(e)}"}

        logger.info(f"Scanning projects directory: {projects_dir}")

        added = 0
        updated = 0
        skipped = 0
        errors = []
        found_containers = set()  # Track containers we found during scan

        # Find all compose.yaml files in subdirectories
        for compose_file in projects_path.glob("*/compose.yaml"):
            try:
                result, container_name = await self._process_compose_file(compose_file)
                if container_name:
                    found_containers.add(container_name)
                if result == "added":
                    added += 1
                elif result == "updated":
                    updated += 1
                elif result == "skipped":
                    skipped += 1
            except YAMLError as e:
                logger.error(f"YAML parsing error in {compose_file}: {e}")
                errors.append(str(e))
            except (OSError, PermissionError) as e:
                logger.error(f"File access error for {compose_file}: {e}")
                errors.append(str(e))
            except OperationalError as e:
                logger.error(f"Database error processing {compose_file}: {e}")
                errors.append(str(e))
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid data in {compose_file}: {e}")
                errors.append(str(e))

        # Remove containers that are marked as My Projects but weren't found in scan
        stmt = select(Container).where(Container.is_my_project)
        result = await self.db.execute(stmt)
        all_my_projects = result.scalars().all()

        removed = 0
        for container in all_my_projects:
            if container.name not in found_containers:
                logger.info(f"Removing stale My Project container: {container.name}")
                await self.db.delete(container)
                removed += 1

        if removed > 0:
            await self.db.commit()

        logger.info(f"Scan complete: {added} added, {updated} updated, {skipped} skipped, {removed} removed")

        result_dict = {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errors": errors if errors else None,
        }
        if removed > 0:
            result_dict["removed"] = removed

        return result_dict

    async def _process_compose_file(self, compose_file: Path) -> tuple[str, str | None]:
        """
        Process a single compose file and add/update containers.

        Returns:
            Tuple of (result, container_name) where result is "added", "updated", or "skipped"
        """
        try:
            # Read compose file
            yaml = YAML()
            with open(compose_file, "r") as f:
                compose_data = yaml.load(f)

            if not compose_data or "services" not in compose_data:
                logger.debug(f"No services found in {compose_file}")
                return ("skipped", None)

            # Find the main dev container service
            services = compose_data["services"]
            if not services:
                return ("skipped", None)

            # Infrastructure services to skip
            skip_services = {"postgres", "redis", "mysql", "mariadb", "mongodb", "rabbitmq", "elasticsearch"}

            # Try to find service ending with -dev first
            dev_service = None
            for svc_name, svc_config in services.items():
                container_name = svc_config.get("container_name", svc_name)

                # Skip infrastructure services
                if svc_name.lower() in skip_services:
                    continue

                # Prefer services/containers ending with -dev
                if svc_name.endswith("-dev") or container_name.endswith("-dev"):
                    dev_service = (svc_name, svc_config)
                    break

            # If no -dev service found, use first non-infrastructure service
            if not dev_service:
                for svc_name, svc_config in services.items():
                    if svc_name.lower() not in skip_services:
                        dev_service = (svc_name, svc_config)
                        break

            # If still nothing found, skip this compose file
            if not dev_service:
                logger.debug(f"No suitable dev service found in {compose_file}")
                return ("skipped", None)

            service_name, service_config = dev_service

            # Extract container details
            container_name = service_config.get("container_name", service_name)
            image_full = service_config.get("image", "")

            # Parse image into name and tag
            if ":" in image_full:
                image, tag = image_full.rsplit(":", 1)
            else:
                image = image_full
                tag = "latest"

            # Skip if no image defined
            if not image:
                logger.debug(f"No image defined for {service_name} in {compose_file}")
                return ("skipped", None)

            # Check if container already exists
            stmt = select(Container).where(Container.name == container_name)
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

            compose_file_str = str(compose_file)

            if existing:
                # Update existing container
                existing.compose_file = compose_file_str
                existing.service_name = service_name
                existing.is_my_project = True

                # Only update image info if it changed
                if existing.image != image or existing.current_tag != tag:
                    existing.image = image
                    existing.current_tag = tag
                    existing.latest_tag = None  # Clear to trigger update check
                    existing.update_available = False

                await self.db.commit()
                logger.info(f"Updated existing container: {container_name}")
                return ("updated", container_name)
            else:
                # Add new container
                new_container = Container(
                    name=container_name,
                    image=image,
                    current_tag=tag,
                    registry="dockerhub",  # Default, will be updated by discovery
                    compose_file=compose_file_str,
                    service_name=service_name,
                    policy="manual",  # Default policy for dev containers
                    scope="patch",
                    is_my_project=True,
                    vulnforge_enabled=True,
                    labels=service_config.get("labels", {}),
                )

                self.db.add(new_container)
                await self.db.commit()
                logger.info(f"Added new container: {container_name}")

                # Auto-scan Dockerfile if enabled
                await self._auto_scan_dockerfile(new_container.id, compose_file.parent)

                return ("added", container_name)

        except YAMLError as e:
            logger.error(f"YAML parsing error in {compose_file}: {e}")
            raise
        except (OSError, PermissionError) as e:
            logger.error(f"File access error for {compose_file}: {e}")
            raise
        except OperationalError as e:
            logger.error(f"Database error processing {compose_file}: {e}")
            raise
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid data in {compose_file}: {e}")
            raise

    async def _auto_scan_dockerfile(self, container_id: int, project_dir: Path) -> None:
        """
        Auto-scan Dockerfile for dependencies if enabled.

        Args:
            container_id: ID of the container
            project_dir: Path to project directory containing Dockerfile
        """
        try:
            # Check if auto-scan is enabled
            auto_scan_enabled = await SettingsService.get(self.db, "dockerfile_auto_scan")
            if not auto_scan_enabled or auto_scan_enabled.lower() != "true":
                return

            # Look for Dockerfile in project directory
            dockerfile_path = project_dir / "Dockerfile"
            if not dockerfile_path.exists():
                logger.debug(f"No Dockerfile found in {project_dir}")
                return

            # Scan the Dockerfile
            from app.services.dockerfile_parser import DockerfileParser
            from sqlalchemy import select
            from app.models.container import Container

            # Get container object
            result = await self.db.execute(
                select(Container).where(Container.id == container_id)
            )
            container = result.scalar_one_or_none()
            if not container:
                logger.warning(f"Container {container_id} not found for Dockerfile scan")
                return

            logger.info(f"Auto-scanning Dockerfile for container {container_id}")
            parser = DockerfileParser()
            dependencies = await parser.scan_container_dockerfile(
                self.db, container, str(dockerfile_path)
            )
            logger.info(
                f"Dockerfile scan completed: {len(dependencies)} dependencies found"
            )

        except (OSError, PermissionError) as e:
            logger.error(f"File access error auto-scanning Dockerfile for container {container_id}: {e}")
            # Don't raise - this is optional functionality
        except OperationalError as e:
            logger.error(f"Database error auto-scanning Dockerfile for container {container_id}: {e}")
            # Don't raise - this is optional functionality
        except (ImportError, AttributeError) as e:
            logger.error(f"Parser dependency error auto-scanning Dockerfile for container {container_id}: {e}")
            # Don't raise - this is optional functionality
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Invalid Dockerfile data for container {container_id}: {e}")
            # Don't raise - this is optional functionality

    async def remove_missing_projects(self) -> int:
        """
        Remove containers marked as My Projects if their compose file no longer exists.

        Returns:
            Number of containers removed
        """
        stmt = select(Container).where(Container.is_my_project)
        result = await self.db.execute(stmt)
        my_projects = result.scalars().all()

        removed = 0
        for container in my_projects:
            compose_path = Path(container.compose_file)
            if not compose_path.exists():
                logger.info(f"Removing missing project: {container.name}")
                await self.db.delete(container)
                removed += 1

        if removed > 0:
            await self.db.commit()
            logger.info(f"Removed {removed} missing project containers")

        return removed
