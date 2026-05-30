"""Path-containment tests for the Dockerfile parser and project scanner.

H2: the parser must contain manual/auto Dockerfile paths within the configured
projects_directory (previously rooted at "/", which is no containment at all),
hard-reject absolute manual paths, and never follow symlinks. The R1-H2
regression guards that auto-scan parses the per-project Dockerfile, not a decoy
``<projects_dir>/Dockerfile`` at the root.

(Shared file — Phase-3 #9 adds scanner/compose/manifest containment classes.)
"""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.models.dockerfile_dependency import DockerfileDependency
from app.services.dockerfile_parser import DockerfileParser


class TestFindDockerfileContainment:
    """DockerfileParser._find_dockerfile manual_path policy (H2)."""

    def _container(self, make_container, *, project_root):
        # compose_file="" so only the project_root anchor drives auto-detection.
        return make_container(name="proj", project_root=str(project_root), compose_file="")

    async def test_rejects_absolute_outside_tree(self, tmp_path, make_container):
        proj = tmp_path / "proj"
        proj.mkdir()
        parser = DockerfileParser(projects_directory=str(tmp_path))
        container = self._container(make_container, project_root=proj)
        # /etc/hostname exists but is absolute → rejected, auto-detect finds nothing.
        assert await parser._find_dockerfile(container, "/etc/hostname") is None

    async def test_rejects_absolute_secret_in_projects(self, tmp_path, make_container):
        proj = tmp_path / "proj"
        proj.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret")
        parser = DockerfileParser(projects_directory=str(tmp_path))
        container = self._container(make_container, project_root=proj)
        assert await parser._find_dockerfile(container, str(secret)) is None

    async def test_accepts_in_tree_relative(self, tmp_path, make_container):
        proj = tmp_path / "proj"
        proj.mkdir()
        df = proj / "Dockerfile"
        df.write_text("FROM python:3.14-slim\n")
        parser = DockerfileParser(projects_directory=str(tmp_path))
        container = self._container(make_container, project_root=proj)
        result = await parser._find_dockerfile(container, "proj/Dockerfile")
        assert result is not None
        assert result == df.resolve()

    async def test_rejects_symlink_manual_path(self, tmp_path, make_container):
        proj = tmp_path / "proj"
        proj.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("FROM evil:latest\n")
        link = proj / "Dockerfile"
        link.symlink_to(outside)
        parser = DockerfileParser(projects_directory=str(tmp_path))
        container = self._container(make_container, project_root=proj)
        # The symlinked manual path is refused (allow_symlinks=False) and there is
        # no real Dockerfile to auto-detect → None (the symlink is never followed).
        assert await parser._find_dockerfile(container, "proj/Dockerfile") is None


class TestParseDockerfileContainment:
    """DockerfileParser._parse_dockerfile symlink rejection (H2 :255)."""

    async def test_parse_dockerfile_rejects_out_of_tree_symlink(self, tmp_path):
        real = tmp_path / "outside" / "Dockerfile"
        real.parent.mkdir()
        real.write_text("FROM python:3.14-slim\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        link = projects / "Dockerfile"
        link.symlink_to(real)
        parser = DockerfileParser(projects_directory=str(projects))
        # Final-component symlink → sanitize_path rejects → no deps parsed.
        deps = await parser._parse_dockerfile(link, container_id=1)
        assert deps == []


class TestAutoScanDockerfileRoot:
    """R1-H2 regression: auto-scan parses the per-project file, not a root decoy."""

    async def test_auto_scan_parses_project_dockerfile_not_root(self, tmp_path, db, make_container):
        from app.services.project_scanner import ProjectScanner
        from app.services.settings_service import SettingsService

        # Decoy at the projects-dir root + the real per-project Dockerfile.
        (tmp_path / "Dockerfile").write_text("FROM alpine:decoy\n")
        myapp = tmp_path / "myapp"
        myapp.mkdir()
        (myapp / "Dockerfile").write_text("FROM python:3.14-slim\n")

        await SettingsService.set(db, "projects_directory", str(tmp_path))
        await SettingsService.set(db, "dockerfile_auto_scan", "true")

        container = make_container(name="myapp", project_root=str(myapp))
        db.add(container)
        await db.commit()
        await db.refresh(container)

        scanner = ProjectScanner(db)
        with patch(
            "app.services.dockerfile_parser.DockerfileParser._check_for_updates",
            new_callable=AsyncMock,
        ):
            await scanner._auto_scan_dockerfile(container, myapp)

        deps = (
            (
                await db.execute(
                    select(DockerfileDependency).where(
                        DockerfileDependency.container_id == container.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(deps) == 1
        # The per-project file (python), never the root decoy (alpine).
        assert deps[0].image_name == "python"


class TestScannerContainment:
    """#9 — compose / manifest / resolver path containment."""

    async def test_parse_compose_file_rejects_symlink_escape(self, tmp_path):
        from app.services.compose_parser import ComposeParser

        outside = tmp_path / "outside" / "evil.yml"
        outside.parent.mkdir()
        outside.write_text("services:\n  evil:\n    image: evil:latest\n")
        base = tmp_path / "project"
        base.mkdir()
        link = base / "docker-compose.yml"
        link.symlink_to(outside)

        result = await ComposeParser._parse_compose_file(str(link), base, AsyncMock())
        assert result == []  # symlink escaping base_dir is refused

    async def test_parse_compose_file_in_tree_ok(self, tmp_path):
        from app.services.compose_parser import ComposeParser

        base = tmp_path / "project"
        base.mkdir()
        compose = base / "docker-compose.yml"
        compose.write_text("services:\n  web:\n    image: nginx:1.25\n")

        result = await ComposeParser._parse_compose_file(str(compose), base, AsyncMock())
        assert len(result) == 1

    async def test_scan_npm_rejects_symlinked_manifest(self, tmp_path):
        from app.services.app_dependencies import DependencyScanner

        outside = tmp_path / "outside.json"
        outside.write_text('{"dependencies": {"left-pad": "1.0.0"}}')
        project = tmp_path / "proj"
        project.mkdir()
        (project / "package.json").symlink_to(outside)

        scanner = DependencyScanner(projects_directory=str(tmp_path))
        deps = await scanner._scan_npm(project)
        assert deps == []  # symlinked manifest never read

    async def test_scan_python_in_tree_ok(self, tmp_path):
        from app.services.app_dependencies import DependencyScanner

        project = tmp_path / "proj"
        project.mkdir()
        (project / "requirements.txt").write_text("requests==2.31.0\n")

        scanner = DependencyScanner(projects_directory=str(tmp_path))
        with patch.object(
            DependencyScanner, "_get_pypi_latest", new=AsyncMock(return_value=None)
        ):
            deps = await scanner._scan_python(project)
        assert any(d.name == "requests" for d in deps)

    def test_resolve_project_root_contains_when_base_given(self, tmp_path, make_container):
        from app.utils.project_resolver import resolve_project_root

        outside = tmp_path / "outside"
        outside.mkdir()
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        container = make_container(name="x", project_root=str(outside))

        assert resolve_project_root(container, projects_directory=projects_dir) is None

    def test_resolve_project_root_in_tree_with_base(self, tmp_path, make_container):
        from app.utils.project_resolver import resolve_project_root

        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        proj = projects_dir / "myapp"
        proj.mkdir()
        container = make_container(name="x", project_root=str(proj))

        assert resolve_project_root(container, projects_directory=projects_dir) == proj
