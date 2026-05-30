"""Service for scanning and discovering dev containers in projects directory.

Discovery is signal-based, not compose-file-based: any subdirectory of the
configured projects directory that exposes a recognizable project signal is
treated as a project.

Signals (any one is sufficient):
    - Dockerfile, Containerfile
    - package.json, pyproject.toml, go.mod, Cargo.toml, composer.json
    - compose.yaml, compose.yml, docker-compose.yaml, docker-compose.yml
"""

import logging
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml import YAML, YAMLError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Container
from app.services.compose_parser import ComposeParser
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_log_message, sanitize_path

logger = logging.getLogger(__name__)


SignalKind = Literal["compose", "signal"]
Signal = tuple[SignalKind, str]

COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)

PROJECT_SIGNAL_FILES = (
    "Dockerfile",
    "Containerfile",
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "composer.json",
)

# Files that, on their own, declare "this is the canonical build context."
# When present, the directory name is the source of truth for the project name
# regardless of any service stubs in a top-level compose file (which is typically
# just a local smoke-test config like `myfinances-dev`, not the production name).
PRIMARY_BUILD_SIGNALS = ("Dockerfile", "Containerfile")

DIRECTORY_IGNORE_LIST = frozenset(
    {
        "scripts",
        "shared-workflows",
    }
)

INFRASTRUCTURE_SERVICES = frozenset(
    {
        "postgres",
        "redis",
        "mysql",
        "mariadb",
        "mongodb",
        "rabbitmq",
        "elasticsearch",
    }
)


class ProjectScanner:
    """Scanner for auto-discovering dev containers in projects directory."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def scan_projects_directory(self) -> dict[str, Any]:
        """Scan projects directory for projects using signal-based discovery."""
        projects_dir = await SettingsService.get(self.db, "projects_directory")
        enabled = await SettingsService.get(self.db, "my_projects_enabled")
        auto_scan = await SettingsService.get(self.db, "my_projects_auto_scan")

        if not enabled or enabled.lower() != "true":
            logger.info("My Projects feature is disabled")
            return {"added": 0, "updated": 0, "skipped": 0, "error": "Feature disabled"}

        if not auto_scan or auto_scan.lower() != "true":
            logger.info("My Projects auto-scan is disabled")
            return {
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "error": "Auto-scan disabled",
            }

        if not projects_dir:
            projects_dir = "/projects"

        try:
            base_dir = projects_dir.split("/")[1] if projects_dir.startswith("/") else ""
            base_path = f"/{base_dir}" if base_dir else projects_dir
            projects_path = sanitize_path(projects_dir, base_path, allow_symlinks=False)

            if not projects_path.exists():
                logger.warning(f"Projects directory does not exist: {projects_path}")
                return {
                    "added": 0,
                    "updated": 0,
                    "skipped": 0,
                    "error": f"Directory not found: {projects_path}",
                }
        except (ValueError, FileNotFoundError) as e:
            logger.error(f"Invalid projects directory path: {sanitize_log_message(str(e))}")
            return {
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "error": f"Invalid directory path: {str(e)}",
            }

        logger.info(f"Scanning projects directory: {projects_dir}")

        # Single My Project query at the start; reused for stale-removal at the end.
        await self._backfill_project_root()
        existing_by_root: dict[str, Container] = {}
        legacy_by_compose: dict[tuple[str, str], Container] = {}
        stmt = select(Container).where(Container.is_my_project)
        for row in (await self.db.execute(stmt)).scalars().all():
            if row.project_root:
                existing_by_root[row.project_root] = row
            elif row.compose_file:
                legacy_by_compose[(row.service_name, row.compose_file)] = row

        added = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        found_roots: set[str] = set()
        newly_added: list[tuple[Container, Path]] = []

        for child in sorted(projects_path.iterdir()):
            try:
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name in DIRECTORY_IGNORE_LIST:
                    continue

                # Containment: a symlinked child must not let the scan descend
                # outside the projects directory.
                try:
                    sanitize_path(child.name, str(projects_path), allow_symlinks=False)
                except (ValueError, FileNotFoundError) as e:
                    logger.warning(
                        "Skipping child outside projects directory: %s - %s",
                        sanitize_log_message(str(child)),
                        sanitize_log_message(str(e)),
                    )
                    continue

                try:
                    files_in_dir = {p.name for p in child.iterdir() if p.is_file()}
                except (OSError, PermissionError) as e:
                    logger.warning(
                        "Could not list %s: %s",
                        sanitize_log_message(str(child)),
                        sanitize_log_message(str(e)),
                    )
                    continue

                signal = _detect_project_signal(files_in_dir)
                if signal is None:
                    logger.debug("No project signal in %s, skipping", child)
                    continue

                result, root, fresh_container = await self._process_project(
                    child, signal, existing_by_root, legacy_by_compose
                )
                if root:
                    found_roots.add(root)
                if result == "added":
                    added += 1
                    if fresh_container is not None:
                        newly_added.append((fresh_container, child))
                elif result == "updated":
                    updated += 1
                elif result == "skipped":
                    skipped += 1
            except YAMLError as e:
                logger.error(f"YAML parsing error in {child}: {e}")
                errors.append(str(e))
            except (OSError, PermissionError) as e:
                logger.error(f"File access error for {child}: {e}")
                errors.append(str(e))
            except OperationalError as e:
                logger.error(f"Database error processing {child}: {e}")
                errors.append(str(e))
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid data in {child}: {e}")
                errors.append(str(e))

        # Stale-removal — in-memory diff against the cached rows.
        removed = 0
        for root, container in existing_by_root.items():
            if root in found_roots:
                continue
            logger.info(f"Removing stale My Project container: {container.name}")
            await self.db.delete(container)
            removed += 1
        for (service, compose_file), container in legacy_by_compose.items():
            derived = str(Path(compose_file).parent)
            if derived in found_roots:
                continue
            logger.info(f"Removing stale legacy My Project container: {container.name}")
            await self.db.delete(container)
            removed += 1

        # One commit for the whole scan (discovery + stale-removal).
        await self.db.commit()

        # Auto-scan Dockerfiles for newly added rows after the commit so the
        # Dockerfile-dependency rows reference a persisted container_id.
        for container, project_dir in newly_added:
            await self._auto_scan_dockerfile(container, project_dir)

        logger.info(
            f"Scan complete: {added} added, {updated} updated, {skipped} skipped, {removed} removed"
        )

        result_dict: dict[str, Any] = {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "errors": errors if errors else None,
        }
        if removed > 0:
            result_dict["removed"] = removed

        return result_dict

    async def _backfill_project_root(self) -> None:
        """Backfill project_root on legacy rows where compose_file is set but
        project_root is NULL. One-shot per row — once set, the filtered query
        is empty going forward."""
        stmt = select(Container).where(
            Container.is_my_project,
            Container.project_root.is_(None),
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        if not rows:
            return

        updated = 0
        for row in rows:
            if row.compose_file:
                row.project_root = str(Path(row.compose_file).parent)
                updated += 1

        if updated:
            await self.db.flush()
            logger.info("Backfilled project_root on %d legacy My Project row(s)", updated)

    async def _process_project(
        self,
        project_dir: Path,
        signal: Signal,
        existing_by_root: dict[str, Container],
        legacy_by_compose: dict[tuple[str, str], Container],
    ) -> tuple[str, str | None, Container | None]:
        """Upsert a project from its detected signal.

        Returns:
            (result, project_root_str, fresh_container) where fresh_container
            is the newly-inserted Container (for post-commit auto-scan) or None.
        """
        kind, filename = signal
        if kind == "compose":
            return await self._process_compose_project(
                project_dir, filename, existing_by_root, legacy_by_compose
            )
        return await self._process_signal_project(project_dir, filename, existing_by_root)

    async def _process_signal_project(
        self,
        project_dir: Path,
        signal_file: str,
        existing_by_root: dict[str, Container],
    ) -> tuple[str, str, Container | None]:
        """Upsert a compose-independent My Project row."""
        project_root_str = str(project_dir)
        service_name = project_dir.name

        existing = existing_by_root.get(project_root_str)
        if existing:
            changed = (
                existing.name != service_name
                or existing.service_name != service_name
                or existing.compose_file != ""
                or existing.project_root != project_root_str
                or not existing.is_my_project
            )
            # Normalize name to the directory name so legacy `<name>-dev` rows
            # from earlier scanner versions get rewritten on first re-scan.
            existing.name = service_name
            existing.service_name = service_name
            existing.project_root = project_root_str
            existing.compose_file = ""
            existing.is_my_project = True
            if changed:
                logger.info(
                    "Updated compose-independent project '%s' (signal: %s)",
                    sanitize_log_message(service_name),
                    sanitize_log_message(signal_file),
                )
                return ("updated", project_root_str, None)
            return ("skipped", project_root_str, None)

        new_container = self._build_container(
            name=service_name,
            project_root=project_root_str,
            service_name=service_name,
            compose_file="",
            image="",
            tag="",
            registry="local",
            labels={},
        )
        self.db.add(new_container)
        await self.db.flush()
        existing_by_root[project_root_str] = new_container
        logger.info(
            "Added compose-independent project '%s' (signal: %s)",
            sanitize_log_message(service_name),
            sanitize_log_message(signal_file),
        )
        return ("added", project_root_str, new_container)

    async def _process_compose_project(
        self,
        project_dir: Path,
        compose_filename: str,
        existing_by_root: dict[str, Container],
        legacy_by_compose: dict[tuple[str, str], Container],
    ) -> tuple[str, str | None, Container | None]:
        """Process a project that has a compose file at the root."""
        compose_file = project_dir / compose_filename
        project_root_str = str(project_dir)

        # Containment: refuse a compose filename that escapes the project dir
        # (e.g. a symlink). The logical path stored on the Container stays
        # project_dir/compose_filename; we only OPEN the validated path.
        try:
            safe_compose = sanitize_path(compose_filename, str(project_dir), allow_symlinks=False)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Skipping compose file outside project dir: %s - %s",
                sanitize_log_message(str(compose_file)),
                sanitize_log_message(str(e)),
            )
            return ("skipped", project_root_str, None)

        try:
            yaml = YAML()
            with open(safe_compose) as f:
                compose_data = yaml.load(f)
        except YAMLError as e:
            logger.error(f"YAML parsing error in {compose_file}: {e}")
            raise

        if not compose_data or "services" not in compose_data:
            logger.debug(f"No services found in {compose_file}")
            return ("skipped", project_root_str, None)

        services = compose_data["services"] or {}
        dev_service = _pick_primary_service(services)
        if not dev_service:
            logger.debug(f"No suitable service found in {compose_file}")
            return ("skipped", project_root_str, None)

        service_name, service_config = dev_service
        container_name = service_config.get("container_name", service_name)
        image_full = service_config.get("image", "")
        labels = _normalize_labels(service_config.get("labels"))

        if not image_full:
            # Build-only entry — treat as a compose-independent project.
            return await self._process_signal_project(
                project_dir, compose_filename, existing_by_root
            )

        parsed = ComposeParser._parse_image_string(image_full)
        if parsed is None:
            logger.debug(
                "Could not parse image %s in %s; treating as build-only",
                sanitize_log_message(image_full),
                sanitize_log_message(str(compose_file)),
            )
            return await self._process_signal_project(
                project_dir, compose_filename, existing_by_root
            )
        registry, image, tag = parsed

        compose_file_str = str(compose_file)
        existing = existing_by_root.get(project_root_str) or legacy_by_compose.get(
            (service_name, compose_file_str)
        )

        if existing:
            image_changed = existing.image != image or existing.current_tag != tag
            changed = (
                image_changed
                or existing.compose_file != compose_file_str
                or existing.service_name != service_name
                or existing.project_root != project_root_str
                or not existing.is_my_project
            )

            existing.compose_file = compose_file_str
            existing.service_name = service_name
            existing.project_root = project_root_str
            existing.is_my_project = True

            if image_changed:
                existing.image = image
                existing.current_tag = tag
                existing.latest_tag = None
                existing.update_available = False

            existing_by_root[project_root_str] = existing
            if changed:
                logger.info(f"Updated existing container: {container_name}")
                return ("updated", project_root_str, None)
            return ("skipped", project_root_str, None)

        new_container = self._build_container(
            name=container_name,
            project_root=project_root_str,
            service_name=service_name,
            compose_file=compose_file_str,
            image=image,
            tag=tag,
            registry=registry,
            labels=labels,
        )
        self.db.add(new_container)
        await self.db.flush()
        existing_by_root[project_root_str] = new_container
        logger.info(f"Added new container: {container_name}")
        return ("added", project_root_str, new_container)

    @staticmethod
    def _build_container(
        *,
        name: str,
        project_root: str,
        service_name: str,
        compose_file: str,
        image: str,
        tag: str,
        registry: str,
        labels: dict[str, str],
    ) -> Container:
        """Build a new My Project Container row with the standard defaults."""
        return Container(
            name=name,
            image=image,
            current_tag=tag,
            registry=registry,
            compose_file=compose_file,
            service_name=service_name,
            project_root=project_root,
            policy="monitor",
            scope="patch",
            is_my_project=True,
            vulnforge_enabled=True,
            labels=labels,
        )

    async def _auto_scan_dockerfile(self, container: Container, project_dir: Path) -> None:
        """Auto-scan Dockerfile for dependencies if enabled."""
        try:
            auto_scan_enabled = await SettingsService.get(self.db, "dockerfile_auto_scan")
            if not auto_scan_enabled or auto_scan_enabled.lower() != "true":
                return

            dockerfile_path = project_dir / "Dockerfile"
            if not dockerfile_path.exists():
                logger.debug(f"No Dockerfile found in {project_dir}")
                return

            # Root the parser at the configured projects directory and pass a path
            # RELATIVE to it that includes the project subdir. A bare "Dockerfile"
            # would resolve to <projects_dir>/Dockerfile (the wrong file), and an
            # absolute path is now hard-rejected by the parser (H2).
            projects_dir = await SettingsService.get(self.db, "projects_directory") or "/projects"
            try:
                rel = str(project_dir.relative_to(projects_dir) / "Dockerfile")
            except ValueError:
                logger.warning(
                    f"Project dir {sanitize_log_message(str(project_dir))} is outside "
                    f"projects_directory {sanitize_log_message(str(projects_dir))}; skipping auto-scan"
                )
                return

            from app.services.dockerfile_parser import DockerfileParser

            logger.info(f"Auto-scanning Dockerfile for container {container.id}")
            parser = DockerfileParser(projects_directory=projects_dir)
            dependencies = await parser.scan_container_dockerfile(self.db, container, rel)
            logger.info(f"Dockerfile scan completed: {len(dependencies)} dependencies found")

        except (OSError, PermissionError) as e:
            logger.error(
                f"File access error auto-scanning Dockerfile for container {container.id}: {e}"
            )
        except OperationalError as e:
            logger.error(
                f"Database error auto-scanning Dockerfile for container {container.id}: {e}"
            )
        except (ImportError, AttributeError) as e:
            logger.error(
                f"Parser dependency error auto-scanning Dockerfile for container {container.id}: {e}"
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Invalid Dockerfile data for container {container.id}: {e}")

    async def remove_missing_projects(self) -> int:
        """Remove My Project rows whose anchor no longer exists on disk."""
        stmt = select(Container).where(Container.is_my_project)
        result = await self.db.execute(stmt)
        my_projects = result.scalars().all()

        removed = 0
        for container in my_projects:
            anchor: Path | None = None
            if container.project_root:
                anchor = Path(container.project_root)
            elif container.compose_file:
                anchor = Path(container.compose_file)

            if anchor is None or not anchor.exists():
                logger.info(f"Removing missing project: {container.name}")
                await self.db.delete(container)
                removed += 1

        if removed > 0:
            await self.db.commit()
            logger.info(f"Removed {removed} missing project containers")

        return removed


def _detect_project_signal(filenames: set[str]) -> Signal | None:
    """Return the strongest project signal in a directory listing.

    Order:
        1. A primary build signal (Dockerfile/Containerfile) wins — the
           directory is the canonical project; local compose stubs may use
           ``<name>-dev`` service names that aren't the project's identity.
        2. Otherwise any other manifest signal (package.json, pyproject.toml,
           go.mod, Cargo.toml, composer.json) → signal path.
        3. Otherwise a compose file at the root → compose path.
    """
    for filename in PRIMARY_BUILD_SIGNALS:
        if filename in filenames:
            return ("signal", filename)
    for filename in PROJECT_SIGNAL_FILES:
        if filename in filenames and filename not in PRIMARY_BUILD_SIGNALS:
            return ("signal", filename)
    for filename in COMPOSE_FILENAMES:
        if filename in filenames:
            return ("compose", filename)
    return None


def _pick_primary_service(
    services: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Pick the primary service from a compose 'services:' map.

    Prefers services/containers whose name ends with -dev; falls back to the
    first non-infrastructure service.
    """
    for svc_name, svc_config in services.items():
        if svc_name.lower() in INFRASTRUCTURE_SERVICES:
            continue
        container_name = svc_config.get("container_name", svc_name)
        if svc_name.endswith("-dev") or container_name.endswith("-dev"):
            return (svc_name, svc_config)

    for svc_name, svc_config in services.items():
        if svc_name.lower() not in INFRASTRUCTURE_SERVICES:
            return (svc_name, svc_config)

    return None


def _normalize_labels(raw: Any) -> dict[str, str]:
    """Normalize compose labels (list-form or dict-form) and sanitize."""
    if not raw:
        return {}
    if isinstance(raw, list):
        raw = ComposeParser._labels_list_to_dict(raw)
    return ComposeParser._sanitize_labels(raw)
