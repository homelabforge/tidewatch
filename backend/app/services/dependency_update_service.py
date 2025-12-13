"""Service for updating dependency files (Dockerfiles, package.json, etc.).

Handles preview and actual updates for all dependency types:
- Dockerfile base images
- HTTP server version labels
- Application dependencies (npm, pypi, etc.)
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dockerfile_dependency import DockerfileDependency
from app.models.http_server import HttpServer
from app.models.app_dependency import AppDependency
from app.models.history import UpdateHistory
from app.models.container import Container
from app.utils.file_operations import (
    validate_file_path_for_update,
    validate_version_string,
    create_timestamped_backup,
    atomic_file_write,
    restore_from_backup,
    cleanup_old_backups,
    FileOperationError,
    PathValidationError,
    VersionValidationError,
)
from app.services.dockerfile_parser import DockerfileParser
from app.services.changelog import ChangelogFetcher
from app.utils.manifest_parsers import (
    update_package_json,
    update_requirements_txt,
    update_pyproject_toml,
    update_composer_json,
    update_cargo_toml,
    update_go_mod,
)

logger = logging.getLogger(__name__)


class DependencyUpdateService:
    """Service for updating dependency files."""

    # Common Docker image to GitHub repository mappings
    DOCKER_IMAGE_GITHUB_REPOS = {
        "python": "python/cpython",
        "node": "nodejs/node",
        "golang": "golang/go",
        "go": "golang/go",
        "rust": "rust-lang/rust",
        "nginx": "nginx/nginx",
        "postgres": "postgres/postgres",
        "redis": "redis/redis",
        "mysql": "mysql/mysql-server",
        "mariadb": "mariadb/server",
        "mongo": "mongodb/mongo",
        "elasticsearch": "elastic/elasticsearch",
        "rabbitmq": "rabbitmq/rabbitmq-server",
        "openjdk": "openjdk/jdk",
        "php": "php/php-src",
        "ruby": "ruby/ruby",
        "alpine": "alpinelinux/docker-alpine",
        "ubuntu": "ubuntu/ubuntu",
        "debian": "debian/debian",
    }

    @staticmethod
    def _get_github_repo_for_image(image_name: str) -> Optional[str]:
        """Get GitHub repo for a Docker image name.

        Args:
            image_name: Docker image name (e.g., "python", "node")

        Returns:
            GitHub repo in owner/repo format, or None if not found
        """
        # Remove registry prefix if present
        if "/" in image_name:
            parts = image_name.split("/")
            image_name = parts[-1]  # Take last part (e.g., "python" from "docker.io/library/python")

        return DependencyUpdateService.DOCKER_IMAGE_GITHUB_REPOS.get(image_name.lower())

    @staticmethod
    async def _get_github_repo_for_package(package_name: str, ecosystem: str) -> Optional[str]:
        """Get GitHub repo for a package from its registry.

        Args:
            package_name: Package name (e.g., "express", "pytest")
            ecosystem: Package ecosystem (npm, pypi, etc.)

        Returns:
            GitHub repo in owner/repo format, or None if not found
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if ecosystem == "npm":
                    # Fetch from npm registry
                    response = await client.get(f"https://registry.npmjs.org/{package_name}")
                    if response.status_code == 200:
                        data = response.json()
                        repo_url = data.get("repository", {})
                        if isinstance(repo_url, dict):
                            repo_url = repo_url.get("url", "")
                        elif isinstance(repo_url, str):
                            pass
                        else:
                            return None

                        # Extract owner/repo from GitHub URL
                        if "github.com/" in repo_url:
                            parts = repo_url.split("github.com/")[-1].rstrip("/").removesuffix(".git").split("/")
                            if len(parts) >= 2:
                                return f"{parts[0]}/{parts[1]}"

                elif ecosystem == "pypi":
                    # Fetch from PyPI JSON API
                    response = await client.get(f"https://pypi.org/pypi/{package_name}/json")
                    if response.status_code == 200:
                        data = response.json()
                        project_urls = data.get("info", {}).get("project_urls", {})

                        # Check various common keys for GitHub URL
                        for key in ["Source", "Repository", "Homepage", "GitHub"]:
                            url = project_urls.get(key, "")
                            if "github.com/" in url:
                                parts = url.split("github.com/")[-1].rstrip("/").removesuffix(".git").split("/")
                                if len(parts) >= 2:
                                    return f"{parts[0]}/{parts[1]}"

        except Exception as e:
            logger.debug(f"Could not fetch GitHub repo for {package_name} ({ecosystem}): {e}")

        return None

    @staticmethod
    async def update_dockerfile_base_image(
        db: AsyncSession,
        dependency_id: int,
        new_version: str,
        triggered_by: str = "user"
    ) -> Dict[str, Any]:
        """
        Update Dockerfile FROM instruction.

        Steps:
        1. Validate dependency exists
        2. Validate new_version format
        3. Validate file path security
        4. Create backup
        5. Parse and update Dockerfile
        6. Write atomically
        7. Create UpdateHistory record
        8. Update dependency record
        9. Return result

        Args:
            db: Database session
            dependency_id: Dockerfile dependency ID
            new_version: New tag to use (e.g., "3.15-slim")
            triggered_by: Who triggered the update

        Returns:
            Dict with success, backup_path, history_id, changes_made
        """
        backup_path = None
        try:
            # Get dependency
            result = await db.execute(
                select(DockerfileDependency).where(DockerfileDependency.id == dependency_id)
            )
            dependency = result.scalar_one_or_none()

            if not dependency:
                return {
                    "success": False,
                    "error": "Dependency not found",
                    "backup_path": None,
                    "history_id": None,
                }

            # Get container for name
            container_result = await db.execute(
                select(Container).where(Container.id == dependency.container_id)
            )
            container = container_result.scalar_one_or_none()
            container_name = container.name if container else "unknown"

            # Validate new version
            try:
                validate_version_string(new_version, ecosystem="docker")
            except VersionValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid version format: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Construct full file path
            # dependency.dockerfile_path is relative, need to make it absolute
            # Inside container, files are mounted at /projects
            file_path = Path("/projects") / dependency.dockerfile_path

            # Validate file path
            try:
                validated_path = validate_file_path_for_update(str(file_path))
            except PathValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid file path: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Create backup
            try:
                backup_path = create_timestamped_backup(validated_path)
            except FileOperationError as e:
                return {
                    "success": False,
                    "error": f"Backup failed: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Update Dockerfile
            success, updated_content = DockerfileParser.update_from_instruction(
                dockerfile_path=validated_path,
                image_name=dependency.image_name,
                new_tag=new_version,
                line_number=dependency.line_number,
                stage_name=dependency.stage_name,
            )

            if not success:
                return {
                    "success": False,
                    "error": "Failed to update Dockerfile (FROM instruction not found or could not be parsed)",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Write atomically
            try:
                atomic_file_write(validated_path, updated_content)
            except FileOperationError as e:
                # Try to restore backup
                if backup_path:
                    try:
                        restore_from_backup(backup_path, validated_path)
                        logger.warning(f"Restored backup after write failure: {e}")
                    except FileOperationError as restore_error:
                        logger.error(f"Failed to restore backup: {restore_error}")

                return {
                    "success": False,
                    "error": f"Write failed: {e}",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Update dependency record
            old_tag = dependency.current_tag
            dependency.current_tag = new_version
            dependency.update_available = False
            dependency.latest_tag = new_version
            dependency.last_checked = datetime.now(timezone.utc)

            # Create history record
            history = UpdateHistory(
                container_id=dependency.container_id,
                container_name=container_name,
                update_id=None,
                from_tag=old_tag,
                to_tag=new_version,
                update_type="manual",
                backup_path=str(backup_path),
                status="success",
                event_type="dependency_update",
                dependency_type="dockerfile",
                dependency_id=dependency.id,
                dependency_name=dependency.image_name,
                file_path=str(validated_path),
                reason=f"Updated {dependency.image_name} from {old_tag} to {new_version}",
                triggered_by=triggered_by,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)

            # Cleanup old backups (keep 5 most recent)
            cleanup_old_backups(validated_path, keep_count=5)

            logger.info(
                f"Successfully updated Dockerfile dependency {dependency.image_name} "
                f"from {old_tag} to {new_version} (file: {validated_path})"
            )

            return {
                "success": True,
                "backup_path": str(backup_path),
                "history_id": history.id,
                "changes_made": f"FROM {dependency.image_name}:{old_tag} → FROM {dependency.image_name}:{new_version}",
            }

        except Exception as e:
            await db.rollback()
            logger.error(f"Unexpected error updating Dockerfile dependency {dependency_id}: {e}")

            # Try to restore backup
            if backup_path and Path(backup_path).exists():
                try:
                    file_path = Path("/projects") / dependency.dockerfile_path
                    restore_from_backup(Path(backup_path), file_path)
                    logger.warning(f"Restored backup after unexpected error: {e}")
                except Exception as restore_error:
                    logger.error(f"Failed to restore backup: {restore_error}")

            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "backup_path": str(backup_path) if backup_path else None,
                "history_id": None,
            }

    @staticmethod
    async def update_http_server_label(
        db: AsyncSession,
        server_id: int,
        new_version: str,
        triggered_by: str = "user"
    ) -> Dict[str, Any]:
        """
        Update http.server.version label in Dockerfile.

        Similar to update_dockerfile_base_image but for LABEL instructions.
        """
        backup_path = None
        try:
            # Get HTTP server
            result = await db.execute(
                select(HttpServer).where(HttpServer.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                return {
                    "success": False,
                    "error": "HTTP server not found",
                    "backup_path": None,
                    "history_id": None,
                }

            # Get container for name
            container_result = await db.execute(
                select(Container).where(Container.id == server.container_id)
            )
            container = container_result.scalar_one_or_none()
            container_name = container.name if container else "unknown"

            # Validate new version (generic validation)
            try:
                validate_version_string(new_version)
            except VersionValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid version format: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Need Dockerfile path (should be in server.dockerfile_path)
            if not server.dockerfile_path:
                return {
                    "success": False,
                    "error": "HTTP server does not have associated Dockerfile path",
                    "backup_path": None,
                    "history_id": None,
                }

            # Inside container, files are mounted at /projects
            file_path = Path("/projects") / server.dockerfile_path

            # Validate file path
            try:
                validated_path = validate_file_path_for_update(str(file_path))
            except PathValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid file path: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Create backup
            try:
                backup_path = create_timestamped_backup(validated_path)
            except FileOperationError as e:
                return {
                    "success": False,
                    "error": f"Backup failed: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Update label
            success, updated_content = DockerfileParser.update_label_value(
                dockerfile_path=validated_path,
                label_key="http.server.version",
                new_value=new_version,
            )

            if not success:
                return {
                    "success": False,
                    "error": "Failed to update http.server.version label in Dockerfile",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Write atomically
            try:
                atomic_file_write(validated_path, updated_content)
            except FileOperationError as e:
                if backup_path:
                    try:
                        restore_from_backup(backup_path, validated_path)
                    except FileOperationError:
                        pass
                return {
                    "success": False,
                    "error": f"Write failed: {e}",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Update server record
            old_version = server.current_version
            server.current_version = new_version
            server.update_available = False
            server.latest_version = new_version
            server.last_checked = datetime.now(timezone.utc)

            # Create history record
            history = UpdateHistory(
                container_id=server.container_id,
                container_name=container_name,
                update_id=None,
                from_tag=old_version or "unknown",
                to_tag=new_version,
                update_type="manual",
                backup_path=str(backup_path),
                status="success",
                event_type="dependency_update",
                dependency_type="http_server",
                dependency_id=server.id,
                dependency_name=server.name,
                file_path=str(validated_path),
                reason=f"Updated {server.name} from {old_version} to {new_version}",
                triggered_by=triggered_by,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)

            cleanup_old_backups(validated_path, keep_count=5)

            logger.info(
                f"Successfully updated HTTP server {server.name} "
                f"from {old_version} to {new_version}"
            )

            return {
                "success": True,
                "backup_path": str(backup_path),
                "history_id": history.id,
                "changes_made": f"LABEL http.server.version: {old_version} → {new_version}",
            }

        except Exception as e:
            await db.rollback()
            logger.error(f"Unexpected error updating HTTP server {server_id}: {e}")

            if backup_path and Path(backup_path).exists():
                try:
                    file_path = Path("/projects") / server.dockerfile_path
                    restore_from_backup(Path(backup_path), file_path)
                except Exception:
                    pass

            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "backup_path": str(backup_path) if backup_path else None,
                "history_id": None,
            }

    @staticmethod
    async def update_app_dependency(
        db: AsyncSession,
        dependency_id: int,
        new_version: str,
        triggered_by: str = "user"
    ) -> Dict[str, Any]:
        """
        Update app dependency in manifest file.

        Supports: package.json, requirements.txt, pyproject.toml, composer.json, Cargo.toml, go.mod
        """
        backup_path = None
        try:
            # Get dependency
            result = await db.execute(
                select(AppDependency).where(AppDependency.id == dependency_id)
            )
            dependency = result.scalar_one_or_none()

            if not dependency:
                return {
                    "success": False,
                    "error": "App dependency not found",
                    "backup_path": None,
                    "history_id": None,
                }

            # Get container for name
            container_result = await db.execute(
                select(Container).where(Container.id == dependency.container_id)
            )
            container = container_result.scalar_one_or_none()
            container_name = container.name if container else "unknown"

            # Validate new version based on ecosystem
            try:
                validate_version_string(new_version, ecosystem=dependency.ecosystem)
            except VersionValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid version format: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Construct full file path
            # Inside container, files are mounted at /projects
            file_path = Path("/projects") / dependency.manifest_file

            # Validate file path
            try:
                validated_path = validate_file_path_for_update(str(file_path))
            except PathValidationError as e:
                return {
                    "success": False,
                    "error": f"Invalid file path: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Create backup
            try:
                backup_path = create_timestamped_backup(validated_path)
            except FileOperationError as e:
                return {
                    "success": False,
                    "error": f"Backup failed: {e}",
                    "backup_path": None,
                    "history_id": None,
                }

            # Update manifest file based on ecosystem
            success = False
            updated_content = ""

            manifest_name = validated_path.name.lower()

            if manifest_name == "package.json":
                # Map dependency_type to package.json section names
                section_name = "dependencies" if dependency.dependency_type == "production" else "devDependencies"
                success, updated_content = update_package_json(
                    validated_path,
                    dependency.name,
                    new_version,
                    section_name
                )
            elif manifest_name == "requirements.txt":
                success, updated_content = update_requirements_txt(
                    validated_path,
                    dependency.name,
                    new_version
                )
            elif manifest_name == "pyproject.toml":
                # Map dependency_type to pyproject.toml section
                # dependency_type can be: production, development, optional, peer
                section = dependency.dependency_type  # Use dependency_type directly
                success, updated_content = update_pyproject_toml(
                    validated_path,
                    dependency.name,
                    new_version,
                    section
                )
            elif manifest_name == "composer.json":
                success, updated_content = update_composer_json(
                    validated_path,
                    dependency.name,
                    new_version,
                    "require" if dependency.dependency_type == "production" else "require-dev"
                )
            elif manifest_name == "cargo.toml":
                # Map dependency_type to Cargo.toml section
                section = "dependencies" if dependency.dependency_type == "production" else "dev-dependencies"
                success, updated_content = update_cargo_toml(
                    validated_path,
                    dependency.name,
                    new_version,
                    section
                )
            elif manifest_name == "go.mod":
                success, updated_content = update_go_mod(
                    validated_path,
                    dependency.name,
                    new_version
                )
            else:
                return {
                    "success": False,
                    "error": f"Unsupported manifest file type: {manifest_name}",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            if not success:
                return {
                    "success": False,
                    "error": f"Failed to update dependency in {manifest_name}",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Write atomically
            try:
                atomic_file_write(validated_path, updated_content)
            except FileOperationError as e:
                if backup_path:
                    try:
                        restore_from_backup(backup_path, validated_path)
                    except FileOperationError:
                        pass
                return {
                    "success": False,
                    "error": f"Write failed: {e}",
                    "backup_path": str(backup_path),
                    "history_id": None,
                }

            # Update dependency record
            old_version = dependency.current_version
            dependency.current_version = new_version
            dependency.update_available = False
            dependency.latest_version = new_version
            dependency.last_checked = datetime.now(timezone.utc)

            # Create history record
            history = UpdateHistory(
                container_id=dependency.container_id,
                container_name=container_name,
                update_id=None,
                from_tag=old_version,
                to_tag=new_version,
                update_type="manual",
                backup_path=str(backup_path),
                status="success",
                event_type="dependency_update",
                dependency_type="app_dependency",
                dependency_id=dependency.id,
                dependency_name=dependency.name,
                file_path=str(validated_path),
                reason=f"Updated {dependency.name} ({dependency.ecosystem}) from {old_version} to {new_version}",
                triggered_by=triggered_by,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)

            cleanup_old_backups(validated_path, keep_count=5)

            logger.info(
                f"Successfully updated app dependency {dependency.name} "
                f"from {old_version} to {new_version} in {manifest_name}"
            )

            return {
                "success": True,
                "backup_path": str(backup_path),
                "history_id": history.id,
                "changes_made": f"{dependency.name}: {old_version} → {new_version} ({manifest_name})",
            }

        except Exception as e:
            await db.rollback()
            logger.error(f"Unexpected error updating app dependency {dependency_id}: {e}")

            if backup_path and Path(backup_path).exists():
                try:
                    file_path = Path("/projects") / dependency.manifest_file
                    restore_from_backup(Path(backup_path), file_path)
                except Exception:
                    pass

            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "backup_path": str(backup_path) if backup_path else None,
                "history_id": None,
            }

    @staticmethod
    async def preview_update(
        db: AsyncSession,
        dependency_type: str,
        dependency_id: int,
        new_version: str
    ) -> Dict[str, Any]:
        """
        Generate preview of update without applying.

        Returns current and new line for display, plus changelog if available.
        """
        try:
            if dependency_type == "dockerfile":
                result = await db.execute(
                    select(DockerfileDependency).where(DockerfileDependency.id == dependency_id)
                )
                dependency = result.scalar_one_or_none()

                if not dependency:
                    return {"error": "Dependency not found"}

                # Try to fetch changelog
                changelog_text = None
                changelog_url = None
                github_repo = DependencyUpdateService._get_github_repo_for_image(dependency.image_name)
                if github_repo:
                    try:
                        fetcher = ChangelogFetcher()
                        # Extract version number without tag suffix (e.g., "3.15.0" from "3.15.0-slim")
                        version_parts = new_version.split("-")
                        version_number = version_parts[0]
                        changelog_result = await fetcher.fetch(github_repo, dependency.image_name, version_number)
                        if changelog_result:
                            changelog_text = changelog_result.raw_text
                            changelog_url = changelog_result.url
                            logger.info(f"Fetched changelog for {dependency.image_name}:{new_version} from {github_repo}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch changelog for {dependency.image_name}: {e}")

                return {
                    "current_line": f"FROM {dependency.image_name}:{dependency.current_tag}",
                    "new_line": f"FROM {dependency.image_name}:{new_version}",
                    "file_path": dependency.dockerfile_path,
                    "line_number": dependency.line_number,
                    "current_version": dependency.current_tag,
                    "new_version": new_version,
                    "changelog": changelog_text,
                    "changelog_url": changelog_url,
                }

            elif dependency_type == "http_server":
                result = await db.execute(
                    select(HttpServer).where(HttpServer.id == dependency_id)
                )
                server = result.scalar_one_or_none()

                if not server:
                    return {"error": "HTTP server not found"}

                return {
                    "current_line": f'LABEL http.server.version="{server.current_version}"',
                    "new_line": f'LABEL http.server.version="{new_version}"',
                    "file_path": server.dockerfile_path or "unknown",
                    "line_number": server.line_number,
                    "current_version": server.current_version or "unknown",
                    "new_version": new_version,
                }

            elif dependency_type == "app_dependency":
                result = await db.execute(
                    select(AppDependency).where(AppDependency.id == dependency_id)
                )
                dependency = result.scalar_one_or_none()

                if not dependency:
                    return {"error": "App dependency not found"}

                # Try to fetch changelog
                changelog_text = None
                changelog_url = None
                github_repo = await DependencyUpdateService._get_github_repo_for_package(
                    dependency.name, dependency.ecosystem
                )
                if github_repo:
                    try:
                        fetcher = ChangelogFetcher()
                        changelog_result = await fetcher.fetch(github_repo, dependency.name, new_version)
                        if changelog_result:
                            changelog_text = changelog_result.raw_text
                            changelog_url = changelog_result.url
                            logger.info(f"Fetched changelog for {dependency.name}@{new_version} from {github_repo}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch changelog for {dependency.name}: {e}")

                # Format depends on manifest type
                manifest_name = Path(dependency.manifest_file).name.lower()

                if manifest_name == "package.json":
                    current_line = f'"{dependency.name}": "{dependency.current_version}"'
                    new_line = f'"{dependency.name}": "{new_version}"'
                elif manifest_name in ["requirements.txt", "pyproject.toml", "cargo.toml"]:
                    current_line = f'{dependency.name} = "{dependency.current_version}"'
                    new_line = f'{dependency.name} = "{new_version}"'
                elif manifest_name == "go.mod":
                    current_line = f'{dependency.name} {dependency.current_version}'
                    new_line = f'{dependency.name} {new_version}'
                else:
                    current_line = f'{dependency.name}: {dependency.current_version}'
                    new_line = f'{dependency.name}: {new_version}'

                return {
                    "current_line": current_line,
                    "new_line": new_line,
                    "file_path": dependency.manifest_file,
                    "line_number": None,
                    "current_version": dependency.current_version,
                    "new_version": new_version,
                    "changelog": changelog_text,
                    "changelog_url": changelog_url,
                }

            else:
                return {"error": f"Unknown dependency type: {dependency_type}"}

        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            return {"error": f"Preview failed: {str(e)}"}
