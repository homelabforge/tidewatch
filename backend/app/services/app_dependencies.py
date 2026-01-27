"""Service for scanning and tracking application dependencies."""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_dependency import AppDependency as AppDependencyModel
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


@dataclass
class AppDependency:
    """Application dependency information (used for scanning)."""

    name: str
    ecosystem: str  # npm, pypi, composer, cargo, go
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    security_advisories: int = 0
    socket_score: float | None = None  # Socket.dev security score (0-100)
    severity: str = "info"  # critical, high, medium, low, info
    dependency_type: str = "production"  # production, development, optional, peer
    manifest_file: str = (
        "unknown"  # Path to manifest file (package.json, requirements.txt, etc.)
    )
    last_checked: datetime | None = None


class DependencyScanner:
    """Scanner for detecting and analyzing application dependencies."""

    # Allowed base path for file updates (must match dependency_update_service.py)
    ALLOWED_BASE_PATH = Path("/srv/raid0/docker/build")

    def __init__(self, projects_directory: str = "/projects"):
        self.timeout = httpx.Timeout(10.0)
        self.projects_directory = Path(projects_directory)

    def _normalize_manifest_path(self, file_path: Path) -> str:
        """
        Normalize manifest file path to be relative to ALLOWED_BASE_PATH.

        Converts /projects/... to relative path from /srv/raid0/docker/build.
        For example:
        - /projects/tidewatch/frontend/package.json -> tidewatch/frontend/package.json
        - /srv/raid0/docker/build/tidewatch/backend/pyproject.toml -> tidewatch/backend/pyproject.toml

        Args:
            file_path: Absolute path to manifest file

        Returns:
            Relative path string from ALLOWED_BASE_PATH
        """
        try:
            # Convert to absolute path
            abs_path = file_path.resolve()

            # Replace /projects with ALLOWED_BASE_PATH if necessary
            path_str = str(abs_path)
            if path_str.startswith("/projects/"):
                # Convert /projects/foo to /srv/raid0/docker/build/foo
                relative_part = path_str[len("/projects/") :]
                return relative_part
            elif path_str.startswith(str(self.ALLOWED_BASE_PATH)):
                # Already under ALLOWED_BASE_PATH, get relative part
                return str(abs_path.relative_to(self.ALLOWED_BASE_PATH))
            else:
                # Fallback - return the path as-is
                logger.warning(
                    f"Manifest path {sanitize_log_message(str(file_path))} not under /projects or {sanitize_log_message(str(self.ALLOWED_BASE_PATH))}"
                )
                return str(file_path)
        except Exception as e:
            logger.error(
                f"Error normalizing manifest path {sanitize_log_message(str(file_path))}: {sanitize_log_message(str(e))}"
            )
            return str(file_path)

    async def scan_container_dependencies(
        self, compose_file: str, service_name: str, manual_path: str | None = None
    ) -> list[AppDependency]:
        """
        Scan a container for application dependencies.

        Args:
            compose_file: Path to the compose file
            service_name: Service name in the compose file (container name)
            manual_path: Optional manual path to dependency files

        Returns:
            List of discovered dependencies
        """
        dependencies = []

        # Use manual path if provided
        if manual_path:
            project_root = Path(manual_path)
        else:
            # Auto-detect project root from compose file location
            project_root = self._find_project_root(compose_file, service_name)

        if not project_root or not project_root.exists():
            logger.warning(
                f"Could not determine project root for {sanitize_log_message(str(service_name))}"
            )
            return dependencies

        logger.info(
            f"Scanning dependencies for {sanitize_log_message(str(service_name))} in {sanitize_log_message(str(project_root))}"
        )

        # Scan for different dependency types
        dependencies.extend(await self._scan_npm(project_root))
        dependencies.extend(await self._scan_python(project_root))
        dependencies.extend(await self._scan_php(project_root))
        dependencies.extend(await self._scan_go(project_root))
        dependencies.extend(await self._scan_rust(project_root))

        return dependencies

    def _find_project_root(
        self, compose_file: str, service_name: str
    ) -> Path | None:
        """
        Find the project root directory from mounted projects directory.

        Args:
            compose_file: Path to the compose file (e.g., /compose/mygarage.yaml)
            service_name: Service name in the compose file (e.g., mygarage-dev)

        Returns:
            Path to project root or None
        """
        try:
            # Extract project name from compose file path
            # /compose/mygarage.yaml -> mygarage
            compose_path = Path(compose_file)
            project_name = compose_path.stem

            # Remove common suffixes like -dev, -prod, _dev, _prod from service_name
            clean_service_name = re.sub(
                r"[-_](dev|prod|test|staging)$", "", service_name
            )

            # Try multiple patterns
            possible_paths = [
                # Direct match: /projects/mygarage
                self.projects_directory / project_name,
                # Service name match: /projects/mygarage-dev
                self.projects_directory / service_name,
                # Clean service name: /projects/mygarage
                self.projects_directory / clean_service_name,
            ]

            for path in possible_paths:
                if path.exists() and path.is_dir():
                    logger.info(
                        f"Found project root: {sanitize_log_message(str(path))}"
                    )
                    return path

            logger.warning(
                f"No project root found. Tried: {sanitize_log_message(str([str(p) for p in possible_paths]))}"
            )
            return None
        except (OSError, PermissionError) as e:
            logger.error(
                f"File system error finding project root: {sanitize_log_message(str(e))}"
            )
            return None
        except ValueError as e:
            logger.error(
                f"Invalid path finding project root: {sanitize_log_message(str(e))}"
            )
            return None

    async def _scan_npm(self, project_root: Path) -> list[AppDependency]:
        """Scan for npm/Node.js dependencies."""
        dependencies = []

        # Try multiple common locations
        locations = [
            project_root / "package.json",
            project_root / "frontend" / "package.json",
            project_root / "client" / "package.json",
            project_root / "app" / "package.json",
        ]

        for package_json in locations:
            if package_json.exists():
                logger.info(
                    f"Found package.json at {sanitize_log_message(str(package_json))}"
                )
                content = package_json.read_text()
                dependencies.extend(
                    await self._parse_package_json(content, package_json)
                )

        return dependencies

    async def _scan_python(self, project_root: Path) -> list[AppDependency]:
        """Scan for Python dependencies."""
        dependencies = []

        # Try multiple common locations
        locations = [
            # pyproject.toml
            (project_root / "pyproject.toml", self._parse_pyproject_content),
            (
                project_root / "backend" / "pyproject.toml",
                self._parse_pyproject_content,
            ),
            (project_root / "api" / "pyproject.toml", self._parse_pyproject_content),
            # requirements.txt
            (project_root / "requirements.txt", self._parse_requirements_content),
            (
                project_root / "backend" / "requirements.txt",
                self._parse_requirements_content,
            ),
            (
                project_root / "api" / "requirements.txt",
                self._parse_requirements_content,
            ),
        ]

        for file_path, parser in locations:
            if file_path.exists():
                logger.info(
                    f"Found Python dependency file at {sanitize_log_message(str(file_path))}"
                )
                content = file_path.read_text()
                dependencies.extend(await parser(content, file_path))

        return dependencies

    async def _scan_php(self, project_root: Path) -> list[AppDependency]:
        """Scan for PHP/Composer dependencies."""
        locations = [
            project_root / "composer.json",
            project_root / "backend" / "composer.json",
            project_root / "api" / "composer.json",
        ]

        for composer_json in locations:
            if composer_json.exists():
                logger.info(
                    f"Found composer.json at {sanitize_log_message(str(composer_json))}"
                )
                content = composer_json.read_text()
                return await self._parse_composer_json(content, composer_json)

        return []

    async def _scan_go(self, project_root: Path) -> list[AppDependency]:
        """Scan for Go module dependencies."""
        locations = [
            project_root / "go.mod",
            project_root / "backend" / "go.mod",
            project_root / "api" / "go.mod",
        ]

        for go_mod in locations:
            if go_mod.exists():
                logger.info(f"Found go.mod at {sanitize_log_message(str(go_mod))}")
                content = go_mod.read_text()
                return await self._parse_go_mod_content(content, go_mod)

        return []

    async def _scan_rust(self, project_root: Path) -> list[AppDependency]:
        """Scan for Rust/Cargo dependencies."""
        locations = [
            project_root / "Cargo.toml",
            project_root / "backend" / "Cargo.toml",
            project_root / "api" / "Cargo.toml",
        ]

        for cargo_toml in locations:
            if cargo_toml.exists():
                logger.info(
                    f"Found Cargo.toml at {sanitize_log_message(str(cargo_toml))}"
                )
                content = cargo_toml.read_text()
                return await self._parse_cargo_toml_content(content, cargo_toml)

        return []

    async def _parse_package_json(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse package.json content."""
        try:
            data = json.loads(content)
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            # Parse each dependency type separately to tag them
            dep_types = [
                ("dependencies", "production"),
                ("devDependencies", "development"),
                ("optionalDependencies", "optional"),
                ("peerDependencies", "peer"),
            ]

            for dep_key, dep_type in dep_types:
                deps_dict = data.get(dep_key, {})
                for name, version in deps_dict.items():
                    clean_version = self._clean_version(version)
                    latest = await self._get_npm_latest(name)

                    dep = AppDependency(
                        name=name,
                        ecosystem="npm",
                        current_version=clean_version,
                        latest_version=latest,
                        update_available=latest is not None and latest != clean_version,
                        dependency_type=dep_type,
                        manifest_file=manifest_file,
                        last_checked=datetime.utcnow(),
                    )
                    dep.severity = self._calculate_severity(
                        clean_version, latest, dep.update_available
                    )
                    dependencies.append(dep)

            # Parse engines field (node, npm, python versions)
            engines = data.get("engines", {})
            for engine_name, version_spec in engines.items():
                clean_version = self._clean_version(version_spec)
                # For engines, we'll use a special ecosystem name
                dep = AppDependency(
                    name=engine_name,
                    ecosystem="engine",
                    current_version=clean_version,
                    latest_version=None,  # Engines don't have "latest" - they're constraints
                    update_available=False,
                    dependency_type="production",
                    manifest_file=manifest_file,
                    last_checked=datetime.utcnow(),
                )
                dependencies.append(dep)

            # Parse packageManager field (npm@9.0.0, yarn@3.0.0, pnpm@8.0.0, bun@1.0.0)
            package_manager = data.get("packageManager", "")
            if package_manager:
                # Format is "manager@version"
                match = re.match(r"^([a-zA-Z0-9_-]+)@(.+)$", package_manager)
                if match:
                    manager_name, manager_version = match.groups()
                    dep = AppDependency(
                        name=manager_name,
                        ecosystem="package-manager",
                        current_version=manager_version,
                        latest_version=None,  # Package managers can be updated independently
                        update_available=False,
                        dependency_type="production",
                        manifest_file=manifest_file,
                        last_checked=datetime.utcnow(),
                    )
                    dependencies.append(dep)

            return dependencies
        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON in package.json: {sanitize_log_message(str(e))}"
            )
            return []
        except (KeyError, ValueError) as e:
            logger.error(
                f"Invalid package.json structure: {sanitize_log_message(str(e))}"
            )
            return []

    async def _parse_toml_deps(
        self, section_content: str, dep_type: str, manifest_file: str
    ) -> list[AppDependency]:
        """Parse TOML dependency section and return list of dependencies."""
        dependencies = []
        for line in section_content.split("\n"):
            line = line.strip().rstrip(",")  # Remove trailing comma
            if not line or line.startswith("#") or line == "python":
                continue

            # Parse: package = "^1.0.0" or "package>=1.0.0"
            match = re.match(r'^([a-zA-Z0-9_-]+)\s*=\s*["\']([^"\']+)["\']', line)
            if match:
                name, version = match.groups()
            elif re.match(r'^"([^"]+)([><=]+)([^"]+)"', line):
                # Handle: "package>=1.0.0" or "package>=1.0.0",
                match = re.match(r'^"([a-zA-Z0-9_-]+)([><=]+)([^"]+)"', line)
                if match:
                    name, operator, version = match.groups()
                else:
                    continue
            else:
                continue

            clean_version = self._clean_version(version)
            latest = await self._get_pypi_latest(name)

            dep = AppDependency(
                name=name,
                ecosystem="pypi",
                current_version=clean_version,
                latest_version=latest,
                update_available=latest is not None and latest != clean_version,
                dependency_type=dep_type,
                manifest_file=manifest_file,
                last_checked=datetime.utcnow(),
            )
            dep.severity = self._calculate_severity(
                clean_version, latest, dep.update_available
            )
            dependencies.append(dep)

        return dependencies

    async def _parse_pyproject_content(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse pyproject.toml content."""
        try:
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            # Parse [project.dependencies] - production
            prod_section = re.search(
                r"\[project\.dependencies\](.*?)(?=\[|$)",
                content,
                re.DOTALL,
            )
            if prod_section:
                deps = await self._parse_toml_deps(
                    prod_section.group(1), "production", manifest_file
                )
                dependencies.extend(deps)

            # Parse [project.optional-dependencies.*] - optional/development (subtable format)
            optional_pattern = (
                r"\[project\.optional-dependencies\.([^\]]+)\](.*?)(?=\[|$)"
            )
            for match in re.finditer(optional_pattern, content, re.DOTALL):
                group_name = match.group(1)
                # Treat 'dev' group as development, others as optional
                dep_type = "development" if group_name == "dev" else "optional"
                deps = await self._parse_toml_deps(
                    match.group(2), dep_type, manifest_file
                )
                dependencies.extend(deps)

            # Parse [project.optional-dependencies] with inline groups (e.g., dev = [...])
            optional_inline = re.search(
                r"\[project\.optional-dependencies\](.*?)(?=^\[|\Z)",
                content,
                re.DOTALL | re.MULTILINE,
            )
            if optional_inline:
                section_content = optional_inline.group(1)
                # Find inline group definitions like: dev = ["package>=1.0", ...]
                # Match group_name = [ ... ] where ... can span multiple lines
                group_pattern = r"([a-zA-Z0-9_-]+)\s*=\s*\[\s*(.*?)\s*\]"
                for group_match in re.finditer(
                    group_pattern, section_content, re.DOTALL
                ):
                    group_name = group_match.group(1)
                    group_deps = group_match.group(2)
                    # Treat 'dev' group as development, others as optional
                    dep_type = "development" if group_name == "dev" else "optional"
                    deps = await self._parse_toml_deps(
                        group_deps, dep_type, manifest_file
                    )
                    dependencies.extend(deps)

            # Parse [tool.poetry.dependencies] - production
            poetry_section = re.search(
                r"\[tool\.poetry\.dependencies\](.*?)(?=\[|$)",
                content,
                re.DOTALL,
            )
            if poetry_section:
                deps = await self._parse_toml_deps(
                    poetry_section.group(1), "production", manifest_file
                )
                dependencies.extend(deps)

            # Parse [tool.poetry.group.*.dependencies] - development/optional
            poetry_group_pattern = (
                r"\[tool\.poetry\.group\.([^\]]+)\.dependencies\](.*?)(?=\[|$)"
            )
            for match in re.finditer(poetry_group_pattern, content, re.DOTALL):
                group_name = match.group(1)
                # Treat 'dev' group as development, others as optional
                dep_type = "development" if group_name == "dev" else "optional"
                deps = await self._parse_toml_deps(
                    match.group(2), dep_type, manifest_file
                )
                dependencies.extend(deps)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(
                f"Invalid pyproject.toml structure: {sanitize_log_message(str(e))}"
            )
            return []

    async def _parse_requirements_content(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse requirements.txt content."""
        try:
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Parse package==version or package>=version
                match = re.match(r"^([a-zA-Z0-9_-]+)([=<>!]+)(.+)$", line)
                if not match:
                    continue

                name, operator, version = match.groups()
                clean_version = self._clean_version(version)
                latest = await self._get_pypi_latest(name)

                dep = AppDependency(
                    name=name,
                    ecosystem="pypi",
                    current_version=clean_version,
                    latest_version=latest,
                    update_available=latest is not None and latest != clean_version,
                    manifest_file=manifest_file,
                    last_checked=datetime.utcnow(),
                )
                dep.severity = self._calculate_severity(
                    clean_version, latest, dep.update_available
                )
                dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(
                f"Invalid requirements.txt structure: {sanitize_log_message(str(e))}"
            )
            return []

    async def _parse_composer_json(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse composer.json content."""
        try:
            data = json.loads(content)
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            # Parse each dependency type separately to tag them
            dep_types = [
                ("require", "production"),
                ("require-dev", "development"),
            ]

            for dep_key, dep_type in dep_types:
                deps_dict = data.get(dep_key, {})
                for name, version in deps_dict.items():
                    if name == "php":
                        continue

                    clean_version = self._clean_version(version)
                    latest = await self._get_packagist_latest(name)

                    dep = AppDependency(
                        name=name,
                        ecosystem="composer",
                        current_version=clean_version,
                        latest_version=latest,
                        update_available=latest is not None and latest != clean_version,
                        dependency_type=dep_type,
                        manifest_file=manifest_file,
                        last_checked=datetime.utcnow(),
                    )
                    dep.severity = self._calculate_severity(
                        clean_version, latest, dep.update_available
                    )
                    dependencies.append(dep)

            return dependencies
        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON in composer.json: {sanitize_log_message(str(e))}"
            )
            return []
        except (KeyError, ValueError) as e:
            logger.error(
                f"Invalid composer.json structure: {sanitize_log_message(str(e))}"
            )
            return []

    async def _parse_go_mod_content(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse go.mod content."""
        try:
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            require_match = re.search(r"require\s*\((.*?)\)", content, re.DOTALL)
            if require_match:
                for line in require_match.group(1).split("\n"):
                    line = line.strip()
                    if not line or line.startswith("//"):
                        continue

                    parts = line.split()
                    if len(parts) >= 2:
                        name, version = parts[0], parts[1]
                        clean_version = self._clean_version(version)
                        latest = await self._get_go_latest(name)

                        dep = AppDependency(
                            name=name,
                            ecosystem="go",
                            current_version=clean_version,
                            latest_version=latest,
                            update_available=latest is not None
                            and latest != clean_version,
                            manifest_file=manifest_file,
                            last_checked=datetime.utcnow(),
                        )
                        dep.severity = self._calculate_severity(
                            clean_version, latest, dep.update_available
                        )
                        dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError, IndexError) as e:
            logger.error(f"Invalid go.mod structure: {sanitize_log_message(str(e))}")
            return []

    async def _parse_cargo_toml_content(
        self, content: str, file_path: Path
    ) -> list[AppDependency]:
        """Parse Cargo.toml content."""
        try:
            dependencies = []

            # Normalize the manifest file path
            manifest_file = self._normalize_manifest_path(file_path)

            dep_section = re.search(
                r"\[dependencies\](.*?)(?=\[|$)", content, re.DOTALL
            )

            if dep_section:
                for line in dep_section.group(1).split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    match = re.match(
                        r'^([a-zA-Z0-9_-]+)\s*=\s*["\']([^"\']+)["\']', line
                    )
                    if not match:
                        match = re.match(
                            r'^([a-zA-Z0-9_-]+)\s*=\s*\{.*?version\s*=\s*["\']([^"\']+)["\']',
                            line,
                        )

                    if not match:
                        continue

                    name, version = match.groups()
                    clean_version = self._clean_version(version)
                    latest = await self._get_crates_latest(name)

                    dep = AppDependency(
                        name=name,
                        ecosystem="cargo",
                        current_version=clean_version,
                        latest_version=latest,
                        update_available=latest is not None and latest != clean_version,
                        manifest_file=manifest_file,
                        last_checked=datetime.utcnow(),
                    )
                    dep.severity = self._calculate_severity(
                        clean_version, latest, dep.update_available
                    )
                    dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(
                f"Invalid Cargo.toml structure: {sanitize_log_message(str(e))}"
            )
            return []

    def _clean_version(self, version: str) -> str:
        """Clean version string by removing operators and whitespace."""
        # Remove ^, ~, >=, etc.
        version = re.sub(r"^[\^~>=<]+", "", version.strip())
        # Remove 'v' prefix
        version = version.lstrip("v")
        return version

    def _calculate_severity(
        self, current: str, latest: str | None, has_update: bool
    ) -> str:
        """Calculate severity of update based on semver difference."""
        if not has_update or not latest:
            return "info"

        try:
            current_parts = [int(x) for x in current.split(".")[:3]]
            latest_parts = [int(x) for x in latest.split(".")[:3]]

            # Pad to 3 parts
            while len(current_parts) < 3:
                current_parts.append(0)
            while len(latest_parts) < 3:
                latest_parts.append(0)

            # Major version change (breaking changes expected per semver)
            if latest_parts[0] > current_parts[0]:
                return "high"
            # Minor version change (backwards-compatible features)
            elif latest_parts[1] > current_parts[1]:
                return "low"
            # Patch version change (backwards-compatible bug fixes)
            else:
                return "info"
        except (ValueError, IndexError, TypeError):
            # If version parsing fails, default to info severity
            return "info"

    async def _get_npm_latest(self, package: str) -> str | None:
        """Fetch latest version from npm registry."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"https://registry.npmjs.org/{package}/latest"
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("version")
        except httpx.HTTPStatusError as e:
            logger.debug(
                f"HTTP error fetching npm version for {sanitize_log_message(str(package))}: {e.response.status_code}"
            )
        except httpx.ConnectError as e:
            logger.debug(
                f"Connection error fetching npm version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except httpx.TimeoutException as e:
            logger.debug(
                f"Timeout fetching npm version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, KeyError) as e:
            logger.debug(
                f"Invalid response fetching npm version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        return None

    async def _get_pypi_latest(self, package: str) -> str | None:
        """Fetch latest version from PyPI."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"https://pypi.org/pypi/{package}/json")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("info", {}).get("version")
        except httpx.HTTPStatusError as e:
            logger.debug(
                f"HTTP error fetching PyPI version for {sanitize_log_message(str(package))}: {e.response.status_code}"
            )
        except httpx.ConnectError as e:
            logger.debug(
                f"Connection error fetching PyPI version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except httpx.TimeoutException as e:
            logger.debug(
                f"Timeout fetching PyPI version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, KeyError) as e:
            logger.debug(
                f"Invalid response fetching PyPI version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        return None

    async def _get_packagist_latest(self, package: str) -> str | None:
        """Fetch latest version from Packagist."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"https://repo.packagist.org/p2/{package}.json"
                )
                if response.status_code == 200:
                    data = response.json()
                    packages = data.get("packages", {}).get(package, [])
                    if packages:
                        # Get latest non-dev version
                        versions = [
                            p["version"]
                            for p in packages
                            if not p["version"].startswith("dev-")
                        ]
                        if versions:
                            return versions[0]
        except httpx.HTTPStatusError as e:
            logger.debug(
                f"HTTP error fetching Packagist version for {sanitize_log_message(str(package))}: {e.response.status_code}"
            )
        except httpx.ConnectError as e:
            logger.debug(
                f"Connection error fetching Packagist version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except httpx.TimeoutException as e:
            logger.debug(
                f"Timeout fetching Packagist version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, KeyError) as e:
            logger.debug(
                f"Invalid response fetching Packagist version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        return None

    async def _get_crates_latest(self, package: str) -> str | None:
        """Fetch latest version from crates.io."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"https://crates.io/api/v1/crates/{package}",
                    headers={"User-Agent": "TideWatch/2.6.0"},
                )
                if response.status_code == 200:
                    data = response.json()
                    crate = data.get("crate", {})
                    return crate.get("max_version")
        except httpx.HTTPStatusError as e:
            logger.debug(
                f"HTTP error fetching crates.io version for {sanitize_log_message(str(package))}: {e.response.status_code}"
            )
        except httpx.ConnectError as e:
            logger.debug(
                f"Connection error fetching crates.io version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except httpx.TimeoutException as e:
            logger.debug(
                f"Timeout fetching crates.io version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, KeyError) as e:
            logger.debug(
                f"Invalid response fetching crates.io version for {sanitize_log_message(str(package))}: {sanitize_log_message(str(e))}"
            )
        return None

    async def _get_go_latest(self, module: str) -> str | None:
        """Fetch latest version from Go proxy."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"https://proxy.golang.org/{module}/@latest"
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("Version", "").lstrip("v")
        except httpx.HTTPStatusError as e:
            logger.debug(
                f"HTTP error fetching Go version for {sanitize_log_message(str(module))}: {e.response.status_code}"
            )
        except httpx.ConnectError as e:
            logger.debug(
                f"Connection error fetching Go version for {sanitize_log_message(str(module))}: {sanitize_log_message(str(e))}"
            )
        except httpx.TimeoutException as e:
            logger.debug(
                f"Timeout fetching Go version for {sanitize_log_message(str(module))}: {sanitize_log_message(str(e))}"
            )
        except (ValueError, KeyError) as e:
            logger.debug(
                f"Invalid response fetching Go version for {sanitize_log_message(str(module))}: {sanitize_log_message(str(e))}"
            )
        return None

    async def persist_dependencies(
        self, db: AsyncSession, container_id: int, dependencies: list[AppDependency]
    ) -> int:
        """
        Persist scanned app dependencies to the database.

        Updates existing dependencies while preserving ignored status.
        Creates new dependencies if they don't exist.
        Removes dependencies that are no longer detected.

        Args:
            db: Database session
            container_id: Container ID
            dependencies: List of scanned dependencies

        Returns:
            Number of dependencies persisted
        """
        try:
            # Get existing dependencies for this container
            result = await db.execute(
                select(AppDependencyModel).where(
                    AppDependencyModel.container_id == container_id
                )
            )
            existing_deps = {
                (dep.name, dep.ecosystem, dep.manifest_file): dep
                for dep in result.scalars().all()
            }

            # Track which existing deps we've seen
            seen_keys = set()

            # Update or create each new dependency
            for new_dep in dependencies:
                # Use manifest_file from dependency if set, otherwise fall back to ecosystem-based guess
                manifest_file = (
                    new_dep.manifest_file
                    if new_dep.manifest_file != "unknown"
                    else self._get_manifest_file_for_dependency(new_dep)
                )

                key = (new_dep.name, new_dep.ecosystem, manifest_file)
                seen_keys.add(key)

                if key in existing_deps:
                    # Update existing dependency while preserving ignored status
                    existing = existing_deps[key]

                    # Update version and availability info
                    existing.current_version = new_dep.current_version
                    existing.latest_version = new_dep.latest_version
                    existing.update_available = new_dep.update_available
                    existing.severity = new_dep.severity
                    existing.dependency_type = new_dep.dependency_type
                    existing.security_advisories = new_dep.security_advisories
                    existing.socket_score = new_dep.socket_score
                    existing.last_checked = datetime.utcnow()

                    # PRESERVE ignored fields - only reset ignore if version has moved past ignored version
                    if existing.ignored and existing.ignored_version:
                        # If the latest version has changed beyond what was ignored, clear the ignore
                        if new_dep.latest_version != existing.ignored_version:
                            logger.info(
                                f"Clearing ignore for {existing.name} ({existing.ecosystem}) - "
                                f"new version {new_dep.latest_version} available (was ignoring {existing.ignored_version})"
                            )
                            existing.ignored = False
                            existing.ignored_version = None
                            existing.ignored_by = None
                            existing.ignored_at = None
                            existing.ignored_reason = None

                    logger.debug(
                        f"Updated existing dependency: {sanitize_log_message(str(existing.name))} ({sanitize_log_message(str(existing.ecosystem))})"
                    )
                else:
                    # Add new dependency
                    db_dep = AppDependencyModel(
                        container_id=container_id,
                        name=new_dep.name,
                        ecosystem=new_dep.ecosystem,
                        current_version=new_dep.current_version,
                        latest_version=new_dep.latest_version,
                        update_available=new_dep.update_available,
                        dependency_type=new_dep.dependency_type,
                        security_advisories=new_dep.security_advisories,
                        socket_score=new_dep.socket_score,
                        severity=new_dep.severity,
                        manifest_file=manifest_file,
                        last_checked=datetime.utcnow(),
                    )
                    db.add(db_dep)
                    logger.debug(
                        f"Created new dependency: {sanitize_log_message(str(new_dep.name))} ({sanitize_log_message(str(new_dep.ecosystem))})"
                    )

            # Remove dependencies that are no longer detected
            for key, existing in existing_deps.items():
                if key not in seen_keys:
                    logger.debug(
                        f"Removing old dependency: {sanitize_log_message(str(existing.name))} ({sanitize_log_message(str(existing.ecosystem))})"
                    )
                    await db.delete(existing)

            await db.commit()
            logger.info(
                f"Persisted {sanitize_log_message(str(len(dependencies)))} app dependencies for container {sanitize_log_message(str(container_id))}"
            )
            return len(dependencies)

        except Exception as e:
            await db.rollback()
            logger.error(
                f"Failed to persist app dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
            )
            raise

    def _get_manifest_file_for_dependency(self, dep: AppDependency) -> str:
        """
        Determine the manifest file path for a dependency based on its ecosystem.

        Args:
            dep: App dependency

        Returns:
            Relative path to manifest file
        """
        ecosystem_manifest_map = {
            "npm": "package.json",
            "pypi": "requirements.txt",  # or pyproject.toml, but we'll use requirements.txt as default
            "composer": "composer.json",
            "go": "go.mod",
            "cargo": "Cargo.toml",
            "engine": "package.json",
            "package-manager": "package.json",
        }
        return ecosystem_manifest_map.get(dep.ecosystem, "unknown")

    async def get_persisted_dependencies(
        self, db: AsyncSession, container_id: int
    ) -> list[AppDependency]:
        """
        Fetch persisted app dependencies from the database.

        Args:
            db: Database session
            container_id: Container ID

        Returns:
            List of app dependencies
        """
        try:
            result = await db.execute(
                select(AppDependencyModel)
                .where(AppDependencyModel.container_id == container_id)
                .order_by(AppDependencyModel.name)
            )
            db_deps = result.scalars().all()

            # Return database models directly (will be converted to schemas in API layer)
            return list(db_deps)

        except Exception as e:
            logger.error(
                f"Failed to fetch persisted app dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
            )
            raise


# Global scanner instance
scanner = DependencyScanner()
