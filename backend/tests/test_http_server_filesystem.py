"""Tests for filesystem-based HTTP server detection.

Tests the scan_project_http_servers() method and its 4 sub-methods
that detect HTTP servers from Dockerfile and dependency files without
requiring a running container.
"""

from pathlib import Path

import pytest


@pytest.fixture
def scanner():
    """Create an HttpServerScanner with mocked Docker client."""
    from unittest.mock import MagicMock, patch

    with patch("app.services.http_server_scanner.docker") as mock_docker:
        mock_docker.from_env.return_value = MagicMock()
        from app.services.http_server_scanner import HttpServerScanner

        return HttpServerScanner()


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory structure."""

    def _create(
        dockerfile_content: str | None = None,
        pyproject_content: str | None = None,
        requirements_content: str | None = None,
        package_json_content: str | None = None,
        backend_pyproject_content: str | None = None,
        frontend_package_json_content: str | None = None,
    ) -> Path:
        project_root = tmp_path / "myproject"
        project_root.mkdir()

        if dockerfile_content is not None:
            (project_root / "Dockerfile").write_text(dockerfile_content)

        if pyproject_content is not None:
            (project_root / "pyproject.toml").write_text(pyproject_content)

        if requirements_content is not None:
            (project_root / "requirements.txt").write_text(requirements_content)

        if package_json_content is not None:
            (project_root / "package.json").write_text(package_json_content)

        if backend_pyproject_content is not None:
            backend = project_root / "backend"
            backend.mkdir()
            (backend / "pyproject.toml").write_text(backend_pyproject_content)

        if frontend_package_json_content is not None:
            frontend = project_root / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text(frontend_package_json_content)

        return project_root

    return _create


# ─── _detect_from_dockerfile_from ─────────────────────────────────────────


class TestDetectFromDockerfileFrom:
    def test_nginx_with_version(self, scanner, tmp_path):
        """Detects nginx from FROM nginx:1.27-alpine."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM nginx:1.27-alpine\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "nginx"
        assert result[0]["current_version"] == "1.27"
        assert result[0]["detection_method"] == "dockerfile_from"

    def test_caddy_with_full_version(self, scanner, tmp_path):
        """Detects caddy with full semver tag."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM caddy:2.9.0\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "caddy"
        assert result[0]["current_version"] == "2.9.0"

    def test_multistage_detects_server_only(self, scanner, tmp_path):
        """In multi-stage builds, only detects known HTTP server images."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.12-slim AS builder\n"
            "RUN pip install granian\n"
            "FROM caddy:2.9 AS server\n"
            "COPY --from=builder /app /srv\n"
        )

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "caddy"
        assert result[0]["current_version"] == "2.9"

    def test_version_parsing_variants(self, scanner, tmp_path):
        """Tests various tag formats for version extraction."""
        test_cases = [
            ("FROM nginx:1.27\n", "1.27"),
            ("FROM nginx:1.27.3\n", "1.27.3"),
            ("FROM nginx:1.27-alpine\n", "1.27"),
            ("FROM caddy:v2.9.0-rc1\n", "2.9.0"),
            ("FROM httpd:2.4-bookworm\n", "2.4"),
        ]

        for content, expected_version in test_cases:
            dockerfile = tmp_path / "Dockerfile"
            dockerfile.write_text(content)

            result = scanner._detect_from_dockerfile_from(dockerfile)

            assert len(result) >= 1, f"No server detected for: {content.strip()}"
            assert result[0]["current_version"] == expected_version, (
                f"Expected {expected_version} for {content.strip()}, got {result[0]['current_version']}"
            )

    def test_no_version_tag(self, scanner, tmp_path):
        """Handles FROM with no tag (e.g., FROM nginx)."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM nginx\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "nginx"
        assert result[0]["current_version"] is None

    def test_latest_tag(self, scanner, tmp_path):
        """Handles FROM nginx:latest — no version extractable."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM nginx:latest\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["current_version"] is None

    def test_registry_prefix_stripped(self, scanner, tmp_path):
        """Strips registry prefix from image name."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM docker.io/library/nginx:1.27\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "nginx"

    def test_platform_flag(self, scanner, tmp_path):
        """Handles FROM with --platform flag."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM --platform=linux/amd64 nginx:1.27-alpine\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "nginx"
        assert result[0]["current_version"] == "1.27"

    def test_non_server_image_ignored(self, scanner, tmp_path):
        """Non-server images like python, node, golang are not detected."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 0

    def test_httpd_detected_as_apache(self, scanner, tmp_path):
        """FROM httpd:2.4 is detected as apache."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM httpd:2.4\n")

        result = scanner._detect_from_dockerfile_from(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "apache"
        assert result[0]["current_version"] == "2.4"


# ─── _detect_from_dependency_files ────────────────────────────────────────


class TestDetectFromDependencyFiles:
    def test_pyproject_granian(self, scanner, tmp_project):
        """Detects granian from pyproject.toml dependencies."""
        project = tmp_project(
            pyproject_content=(
                '[project]\nname = "myapp"\ndependencies = [\n'
                '    "granian>=2.6.0",\n'
                '    "fastapi>=0.115.0",\n'
                "]\n"
            )
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "granian"
        assert result[0]["current_version"] == "2.6.0"
        assert result[0]["detection_method"] == "dependency_file"

    def test_requirements_txt_uvicorn(self, scanner, tmp_project):
        """Detects uvicorn from requirements.txt."""
        project = tmp_project(
            requirements_content="fastapi==0.115.0\nuvicorn[standard]==0.34.0\nrequests>=2.31.0\n"
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "uvicorn"
        assert result[0]["current_version"] == "0.34.0"

    def test_package_json_express(self, scanner, tmp_project):
        """Detects express (as node) from package.json."""
        project = tmp_project(
            package_json_content='{"dependencies": {"express": "^4.21.0", "lodash": "^4.17.21"}}'
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "node"
        assert result[0]["current_version"] == "4.21.0"

    def test_backend_subdirectory(self, scanner, tmp_project):
        """Scans backend/ subdirectory for manifests."""
        project = tmp_project(
            backend_pyproject_content=(
                '[project]\nname = "myapp"\ndependencies = [\n    "gunicorn>=22.0.0",\n]\n'
            )
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "gunicorn"
        assert result[0]["current_version"] == "22.0.0"

    def test_frontend_subdirectory(self, scanner, tmp_project):
        """Scans frontend/ subdirectory for manifests."""
        project = tmp_project(frontend_package_json_content='{"dependencies": {"next": "^14.2.0"}}')

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "node"
        assert result[0]["current_version"] == "14.2.0"

    def test_no_server_dependencies(self, scanner, tmp_project):
        """Returns empty when no HTTP server packages found."""
        project = tmp_project(
            pyproject_content=(
                '[project]\nname = "myapp"\ndependencies = [\n'
                '    "requests>=2.31.0",\n'
                '    "pydantic>=2.0.0",\n'
                "]\n"
            )
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 0

    def test_deduplicates_same_server(self, scanner, tmp_project):
        """If express and fastify both detected, 'node' only appears once."""
        project = tmp_project(
            package_json_content='{"dependencies": {"express": "^4.21.0", "fastify": "^5.0.0"}}'
        )

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 1
        assert result[0]["name"] == "node"

    def test_no_manifest_files(self, scanner, tmp_project):
        """Returns empty when no manifest files exist."""
        project = tmp_project()

        result = scanner._detect_from_dependency_files(project)

        assert len(result) == 0


# ─── _detect_from_dockerfile_run ──────────────────────────────────────────


class TestDetectFromDockerfileRun:
    def test_apt_get_nginx(self, scanner, tmp_path):
        """Detects nginx from apt-get install."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y nginx\n")

        result = scanner._detect_from_dockerfile_run(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "nginx"
        assert result[0]["current_version"] is None
        assert result[0]["detection_method"] == "dockerfile_run"

    def test_apk_add_lighttpd(self, scanner, tmp_path):
        """Detects lighttpd from apk add."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM alpine:3.19\nRUN apk add --no-cache lighttpd\n")

        result = scanner._detect_from_dockerfile_run(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "lighttpd"

    def test_pip_install_uvicorn(self, scanner, tmp_path):
        """Detects uvicorn from pip install."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install uvicorn[standard] fastapi\n")

        result = scanner._detect_from_dockerfile_run(dockerfile)

        assert len(result) == 1
        assert result[0]["name"] == "uvicorn"

    def test_deduplicates_multiple_matches(self, scanner, tmp_path):
        """Same server mentioned multiple times only appears once."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.12-slim\nRUN pip install uvicorn\nRUN pip install uvicorn[standard]\n"
        )

        result = scanner._detect_from_dockerfile_run(dockerfile)

        assert len(result) == 1

    def test_no_server_in_run(self, scanner, tmp_path):
        """Returns empty when no server-related RUN commands."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.12-slim\n"
            "RUN pip install requests\n"
            "RUN apt-get update && apt-get install -y curl\n"
        )

        result = scanner._detect_from_dockerfile_run(dockerfile)

        assert len(result) == 0


# ─── Precedence / Merge Logic ─────────────────────────────────────────────


class TestPrecedence:
    def test_from_overrides_dependency(self, scanner, tmp_project):
        """FROM takes precedence over dependency files."""
        project = tmp_project(
            pyproject_content=(
                '[project]\nname = "myapp"\ndependencies = [\n    "granian>=2.6.0",\n]\n'
            )
        )
        # Add a Dockerfile with a FROM nginx
        (project / "Dockerfile").write_text("FROM nginx:1.27\n")

        from_servers = scanner._detect_from_dockerfile_from(project / "Dockerfile")
        dep_servers = scanner._detect_from_dependency_files(project)

        # Both detected different servers
        assert from_servers[0]["name"] == "nginx"
        assert dep_servers[0]["name"] == "granian"

    def test_from_version_wins_over_dep_version(self, scanner, tmp_project):
        """FROM-detected version takes precedence (added first in merge)."""
        project = tmp_project(
            pyproject_content=(
                '[project]\nname = "myapp"\ndependencies = [\n    "granian>=2.6.0",\n]\n'
            )
        )
        # Dockerfile has no FROM server image, only python
        (project / "Dockerfile").write_text("FROM python:3.12-slim\n")

        from_servers = scanner._detect_from_dockerfile_from(project / "Dockerfile")
        dep_servers = scanner._detect_from_dependency_files(project)

        # FROM didn't detect a server (python is not a server image)
        assert len(from_servers) == 0
        # Dependency detection found granian
        assert dep_servers[0]["name"] == "granian"
        assert dep_servers[0]["current_version"] == "2.6.0"


# ─── scan_project_http_servers end-to-end ─────────────────────────────────


class TestScanProjectHttpServersE2E:
    @pytest.mark.asyncio
    async def test_full_scan(self, scanner, tmp_path, db):
        """End-to-end scan with temp directory containing Dockerfile + pyproject."""
        from unittest.mock import AsyncMock, patch

        from app.models.container import Container

        # Create project structure (no http.server.* labels — detection is automatic)
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        (project_root / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (project_root / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\ndependencies = [\n'
            '    "granian>=2.6.0",\n'
            '    "fastapi>=0.115.0",\n'
            "]\n"
        )

        # Create container in DB
        container = Container(
            name="myproject-dev",
            image="myproject",
            current_tag="latest",
            registry="ghcr.io",
            compose_file="/compose/myproject.yaml",
            service_name="myproject-dev",
            is_my_project=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Mock settings and project resolver (lazy imports inside method)
        mock_settings = AsyncMock()
        mock_settings.get = AsyncMock(return_value=str(tmp_path))

        with (
            patch("app.services.settings_service.SettingsService", mock_settings),
            patch(
                "app.utils.project_resolver.find_project_root",
                return_value=project_root,
            ),
        ):
            # Mock _get_latest_version to avoid network calls
            scanner._get_latest_version = AsyncMock(return_value="2.7.0")

            servers = await scanner.scan_project_http_servers(container_model=container, db=db)

        # Should detect granian from dependency file (pyproject.toml)
        assert len(servers) >= 1
        granian = next((s for s in servers if s["name"] == "granian"), None)
        assert granian is not None
        assert granian["current_version"] == "2.6.0"
        assert granian["detection_method"] == "dependency_file"

    @pytest.mark.asyncio
    async def test_project_root_not_found(self, scanner, db):
        """Logs warning and returns empty when project root not found."""
        from unittest.mock import AsyncMock, patch

        from app.models.container import Container

        container = Container(
            name="nonexistent",
            image="nonexistent",
            current_tag="latest",
            registry="ghcr.io",
            compose_file="/compose/nonexistent.yaml",
            service_name="nonexistent",
            is_my_project=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_settings = AsyncMock()
        mock_settings.get = AsyncMock(return_value="/projects")

        with (
            patch("app.services.settings_service.SettingsService", mock_settings),
            patch(
                "app.utils.project_resolver.find_project_root",
                return_value=None,
            ),
        ):
            servers = await scanner.scan_project_http_servers(container_model=container, db=db)

        assert servers == []

    @pytest.mark.asyncio
    async def test_no_dockerfile(self, scanner, tmp_path, db):
        """Scans dependency files even when no Dockerfile present."""
        from unittest.mock import AsyncMock, patch

        from app.models.container import Container

        project_root = tmp_path / "nodeapp"
        project_root.mkdir()
        (project_root / "package.json").write_text('{"dependencies": {"express": "^4.21.0"}}')

        container = Container(
            name="nodeapp",
            image="nodeapp",
            current_tag="latest",
            registry="ghcr.io",
            compose_file="/compose/nodeapp.yaml",
            service_name="nodeapp",
            is_my_project=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_settings = AsyncMock()
        mock_settings.get = AsyncMock(return_value=str(tmp_path))

        with (
            patch("app.services.settings_service.SettingsService", mock_settings),
            patch(
                "app.utils.project_resolver.find_project_root",
                return_value=project_root,
            ),
        ):
            scanner._get_latest_version = AsyncMock(return_value=None)

            servers = await scanner.scan_project_http_servers(container_model=container, db=db)

        assert len(servers) == 1
        assert servers[0]["name"] == "node"
        assert servers[0]["current_version"] == "4.21.0"

    @pytest.mark.asyncio
    async def test_dockerfile_in_subdirectory(self, scanner, tmp_path, db):
        """Finds Dockerfile in docker/ subdirectory."""
        from unittest.mock import AsyncMock, patch

        from app.models.container import Container

        project_root = tmp_path / "myapp"
        project_root.mkdir()
        docker_dir = project_root / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM nginx:1.27-alpine\n")

        container = Container(
            name="myapp",
            image="myapp",
            current_tag="latest",
            registry="ghcr.io",
            compose_file="/compose/myapp.yaml",
            service_name="myapp",
            is_my_project=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_settings = AsyncMock()
        mock_settings.get = AsyncMock(return_value=str(tmp_path))

        with (
            patch("app.services.settings_service.SettingsService", mock_settings),
            patch(
                "app.utils.project_resolver.find_project_root",
                return_value=project_root,
            ),
        ):
            scanner._get_latest_version = AsyncMock(return_value="1.28.0")

            servers = await scanner.scan_project_http_servers(container_model=container, db=db)

        assert len(servers) == 1
        assert servers[0]["name"] == "nginx"
        assert servers[0]["current_version"] == "1.27"


# ─── New server_patterns entries ──────────────────────────────────────────


class TestServerPatterns:
    def test_uvicorn_pattern_exists(self, scanner):
        """Verify uvicorn entry in server_patterns."""
        assert "uvicorn" in scanner.server_patterns
        assert scanner.server_patterns["uvicorn"]["latest_api"] is not None

    def test_gunicorn_pattern_exists(self, scanner):
        """Verify gunicorn entry in server_patterns."""
        assert "gunicorn" in scanner.server_patterns
        assert scanner.server_patterns["gunicorn"]["latest_api"] is not None

    def test_from_image_servers(self, scanner):
        """Verify from_image_servers mapping."""
        assert scanner.from_image_servers["nginx"] == "nginx"
        assert scanner.from_image_servers["httpd"] == "apache"
        assert scanner.from_image_servers["caddy"] == "caddy"
        assert scanner.from_image_servers["traefik"] == "traefik"

    def test_dependency_servers(self, scanner):
        """Verify dependency_servers mapping."""
        assert scanner.dependency_servers["granian"]["name"] == "granian"
        assert scanner.dependency_servers["express"]["name"] == "node"
        assert scanner.dependency_servers["uvicorn"]["ecosystem"] == "pypi"
        assert scanner.dependency_servers["next"]["ecosystem"] == "npm"
