"""Service for scanning and tracking application dependencies."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import httpx
import logging

from app.schemas.container import AppDependency

logger = logging.getLogger(__name__)


class DependencyScanner:
    """Scanner for detecting and analyzing application dependencies."""

    def __init__(self, projects_directory: str = "/projects"):
        self.timeout = httpx.Timeout(10.0)
        self.projects_directory = Path(projects_directory)

    async def scan_container_dependencies(
        self, compose_file: str, service_name: str, manual_path: Optional[str] = None
    ) -> List[AppDependency]:
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
            logger.warning(f"Could not determine project root for {service_name}")
            return dependencies

        logger.info(f"Scanning dependencies for {service_name} in {project_root}")

        # Scan for different dependency types
        dependencies.extend(await self._scan_npm(project_root))
        dependencies.extend(await self._scan_python(project_root))
        dependencies.extend(await self._scan_php(project_root))
        dependencies.extend(await self._scan_go(project_root))
        dependencies.extend(await self._scan_rust(project_root))

        return dependencies

    def _find_project_root(self, compose_file: str, service_name: str) -> Optional[Path]:
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
            clean_service_name = re.sub(r'[-_](dev|prod|test|staging)$', '', service_name)

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
                    logger.info(f"Found project root: {path}")
                    return path

            logger.warning(f"No project root found. Tried: {[str(p) for p in possible_paths]}")
            return None
        except (OSError, PermissionError) as e:
            logger.error(f"File system error finding project root: {e}")
            return None
        except ValueError as e:
            logger.error(f"Invalid path finding project root: {e}")
            return None

    async def _scan_npm(self, project_root: Path) -> List[AppDependency]:
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
                logger.info(f"Found package.json at {package_json}")
                content = package_json.read_text()
                dependencies.extend(await self._parse_package_json(content))

        return dependencies

    async def _scan_python(self, project_root: Path) -> List[AppDependency]:
        """Scan for Python dependencies."""
        dependencies = []

        # Try multiple common locations
        locations = [
            # pyproject.toml
            (project_root / "pyproject.toml", self._parse_pyproject_content),
            (project_root / "backend" / "pyproject.toml", self._parse_pyproject_content),
            (project_root / "api" / "pyproject.toml", self._parse_pyproject_content),
            # requirements.txt
            (project_root / "requirements.txt", self._parse_requirements_content),
            (project_root / "backend" / "requirements.txt", self._parse_requirements_content),
            (project_root / "api" / "requirements.txt", self._parse_requirements_content),
        ]

        for file_path, parser in locations:
            if file_path.exists():
                logger.info(f"Found Python dependency file at {file_path}")
                content = file_path.read_text()
                dependencies.extend(await parser(content))

        return dependencies

    async def _scan_php(self, project_root: Path) -> List[AppDependency]:
        """Scan for PHP/Composer dependencies."""
        locations = [
            project_root / "composer.json",
            project_root / "backend" / "composer.json",
            project_root / "api" / "composer.json",
        ]

        for composer_json in locations:
            if composer_json.exists():
                logger.info(f"Found composer.json at {composer_json}")
                content = composer_json.read_text()
                return await self._parse_composer_json(content)

        return []

    async def _scan_go(self, project_root: Path) -> List[AppDependency]:
        """Scan for Go module dependencies."""
        locations = [
            project_root / "go.mod",
            project_root / "backend" / "go.mod",
            project_root / "api" / "go.mod",
        ]

        for go_mod in locations:
            if go_mod.exists():
                logger.info(f"Found go.mod at {go_mod}")
                content = go_mod.read_text()
                return await self._parse_go_mod_content(content)

        return []

    async def _scan_rust(self, project_root: Path) -> List[AppDependency]:
        """Scan for Rust/Cargo dependencies."""
        locations = [
            project_root / "Cargo.toml",
            project_root / "backend" / "Cargo.toml",
            project_root / "api" / "Cargo.toml",
        ]

        for cargo_toml in locations:
            if cargo_toml.exists():
                logger.info(f"Found Cargo.toml at {cargo_toml}")
                content = cargo_toml.read_text()
                return await self._parse_cargo_toml_content(content)

        return []

    async def _parse_package_json(self, content: str) -> List[AppDependency]:
        """Parse package.json content."""
        try:
            data = json.loads(content)
            dependencies = []

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
                        last_checked=datetime.utcnow(),
                    )
                    dependencies.append(dep)

            return dependencies
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in package.json: {e}")
            return []
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid package.json structure: {e}")
            return []

    async def _parse_toml_deps(self, section_content: str, dep_type: str) -> List[AppDependency]:
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
                last_checked=datetime.utcnow(),
            )
            dep.severity = self._calculate_severity(
                clean_version, latest, dep.update_available
            )
            dependencies.append(dep)

        return dependencies

    async def _parse_pyproject_content(self, content: str) -> List[AppDependency]:
        """Parse pyproject.toml content."""
        try:
            dependencies = []

            # Parse [project.dependencies] - production
            prod_section = re.search(
                r"\[project\.dependencies\](.*?)(?=\[|$)",
                content,
                re.DOTALL,
            )
            if prod_section:
                deps = await self._parse_toml_deps(prod_section.group(1), "production")
                dependencies.extend(deps)

            # Parse [project.optional-dependencies.*] - optional/development (subtable format)
            optional_pattern = r"\[project\.optional-dependencies\.([^\]]+)\](.*?)(?=\[|$)"
            for match in re.finditer(optional_pattern, content, re.DOTALL):
                group_name = match.group(1)
                # Treat 'dev' group as development, others as optional
                dep_type = "development" if group_name == "dev" else "optional"
                deps = await self._parse_toml_deps(match.group(2), dep_type)
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
                group_pattern = r'([a-zA-Z0-9_-]+)\s*=\s*\[\s*(.*?)\s*\]'
                for group_match in re.finditer(group_pattern, section_content, re.DOTALL):
                    group_name = group_match.group(1)
                    group_deps = group_match.group(2)
                    # Treat 'dev' group as development, others as optional
                    dep_type = "development" if group_name == "dev" else "optional"
                    deps = await self._parse_toml_deps(group_deps, dep_type)
                    dependencies.extend(deps)

            # Parse [tool.poetry.dependencies] - production
            poetry_section = re.search(
                r"\[tool\.poetry\.dependencies\](.*?)(?=\[|$)",
                content,
                re.DOTALL,
            )
            if poetry_section:
                deps = await self._parse_toml_deps(poetry_section.group(1), "production")
                dependencies.extend(deps)

            # Parse [tool.poetry.group.*.dependencies] - development/optional
            poetry_group_pattern = r"\[tool\.poetry\.group\.([^\]]+)\.dependencies\](.*?)(?=\[|$)"
            for match in re.finditer(poetry_group_pattern, content, re.DOTALL):
                group_name = match.group(1)
                # Treat 'dev' group as development, others as optional
                dep_type = "development" if group_name == "dev" else "optional"
                deps = await self._parse_toml_deps(match.group(2), dep_type)
                dependencies.extend(deps)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid pyproject.toml structure: {e}")
            return []

    async def _parse_requirements_content(self, content: str) -> List[AppDependency]:
        """Parse requirements.txt content."""
        try:
            dependencies = []
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
                    last_checked=datetime.utcnow(),
                )
                dep.severity = self._calculate_severity(
                    clean_version, latest, dep.update_available
                )
                dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid requirements.txt structure: {e}")
            return []

    async def _parse_composer_json(self, content: str) -> List[AppDependency]:
        """Parse composer.json content."""
        try:
            data = json.loads(content)
            dependencies = []

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
                        last_checked=datetime.utcnow(),
                    )
                    dep.severity = self._calculate_severity(
                        clean_version, latest, dep.update_available
                    )
                    dependencies.append(dep)

            return dependencies
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in composer.json: {e}")
            return []
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid composer.json structure: {e}")
            return []

    async def _parse_go_mod_content(self, content: str) -> List[AppDependency]:
        """Parse go.mod content."""
        try:
            dependencies = []
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
                            update_available=latest is not None and latest != clean_version,
                            last_checked=datetime.utcnow(),
                        )
                        dep.severity = self._calculate_severity(
                            clean_version, latest, dep.update_available
                        )
                        dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError, IndexError) as e:
            logger.error(f"Invalid go.mod structure: {e}")
            return []

    async def _parse_cargo_toml_content(self, content: str) -> List[AppDependency]:
        """Parse Cargo.toml content."""
        try:
            dependencies = []
            dep_section = re.search(
                r"\[dependencies\](.*?)(?=\[|$)", content, re.DOTALL
            )

            if dep_section:
                for line in dep_section.group(1).split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    match = re.match(r'^([a-zA-Z0-9_-]+)\s*=\s*["\']([^"\']+)["\']', line)
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
                        last_checked=datetime.utcnow(),
                    )
                    dep.severity = self._calculate_severity(
                        clean_version, latest, dep.update_available
                    )
                    dependencies.append(dep)

            return dependencies
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid Cargo.toml structure: {e}")
            return []

    def _clean_version(self, version: str) -> str:
        """Clean version string by removing operators and whitespace."""
        # Remove ^, ~, >=, etc.
        version = re.sub(r"^[\^~>=<]+", "", version.strip())
        # Remove 'v' prefix
        version = version.lstrip("v")
        return version

    def _calculate_severity(
        self, current: str, latest: Optional[str], has_update: bool
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

            # Major version change
            if latest_parts[0] > current_parts[0]:
                return "medium"
            # Minor version change
            elif latest_parts[1] > current_parts[1]:
                return "low"
            # Patch version change
            else:
                return "info"
        except:
            return "info"

    async def _get_npm_latest(self, package: str) -> Optional[str]:
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
            logger.debug(f"HTTP error fetching npm version for {package}: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.debug(f"Connection error fetching npm version for {package}: {e}")
        except httpx.TimeoutException as e:
            logger.debug(f"Timeout fetching npm version for {package}: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Invalid response fetching npm version for {package}: {e}")
        return None

    async def _get_pypi_latest(self, package: str) -> Optional[str]:
        """Fetch latest version from PyPI."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"https://pypi.org/pypi/{package}/json")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("info", {}).get("version")
        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP error fetching PyPI version for {package}: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.debug(f"Connection error fetching PyPI version for {package}: {e}")
        except httpx.TimeoutException as e:
            logger.debug(f"Timeout fetching PyPI version for {package}: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Invalid response fetching PyPI version for {package}: {e}")
        return None

    async def _get_packagist_latest(self, package: str) -> Optional[str]:
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
            logger.debug(f"HTTP error fetching Packagist version for {package}: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.debug(f"Connection error fetching Packagist version for {package}: {e}")
        except httpx.TimeoutException as e:
            logger.debug(f"Timeout fetching Packagist version for {package}: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Invalid response fetching Packagist version for {package}: {e}")
        return None

    async def _get_crates_latest(self, package: str) -> Optional[str]:
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
            logger.debug(f"HTTP error fetching crates.io version for {package}: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.debug(f"Connection error fetching crates.io version for {package}: {e}")
        except httpx.TimeoutException as e:
            logger.debug(f"Timeout fetching crates.io version for {package}: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Invalid response fetching crates.io version for {package}: {e}")
        return None

    async def _get_go_latest(self, module: str) -> Optional[str]:
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
            logger.debug(f"HTTP error fetching Go version for {module}: {e.response.status_code}")
        except httpx.ConnectError as e:
            logger.debug(f"Connection error fetching Go version for {module}: {e}")
        except httpx.TimeoutException as e:
            logger.debug(f"Timeout fetching Go version for {module}: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Invalid response fetching Go version for {module}: {e}")
        return None


# Global scanner instance
scanner = DependencyScanner()
