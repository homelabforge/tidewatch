"""Phase 0 tests: signal-based project discovery + project_root resolver.

Covers:
- Discovery picks up bare Dockerfile projects, monorepos, package.json-only
  projects, and traditional compose-file projects.
- Ignore list: scripts/, shared-workflows/, dotted dirs.
- Stale-removal uses project_root as the stable key.
- resolve_project_root() prefers Container.project_root over compose_file.
- DockerfileParser / HttpServerScanner / DependencyScanner read project paths
  through resolve_project_root (regression for the resolver contract).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Container
from app.services.project_scanner import ProjectScanner
from app.services.settings_service import SettingsService
from app.utils.project_resolver import resolve_project_root

# ─── resolver ────────────────────────────────────────────────────────────────


def test_resolve_project_root_prefers_project_root_attr(tmp_path):
    project = tmp_path / "myproject"
    project.mkdir()
    container = SimpleNamespace(project_root=str(project), compose_file="")
    assert resolve_project_root(container) == project


def test_resolve_project_root_falls_back_to_compose_file_parent(tmp_path):
    compose_dir = tmp_path / "foo"
    compose_dir.mkdir()
    compose_file = compose_dir / "compose.yaml"
    compose_file.write_text("services: {}\n")
    container = SimpleNamespace(project_root=None, compose_file=str(compose_file))
    assert resolve_project_root(container) == compose_dir


def test_resolve_project_root_returns_none_when_no_anchor():
    container = SimpleNamespace(project_root=None, compose_file=None)
    assert resolve_project_root(container) is None


def test_resolve_project_root_handles_empty_string_compose_file(tmp_path):
    container = SimpleNamespace(project_root=None, compose_file="")
    assert resolve_project_root(container) is None


# ─── scanner discovery ───────────────────────────────────────────────────────


def _make_dockerfile_project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir()
    (project / "Dockerfile").write_text("FROM scratch\n")
    return project


def _make_monorepo_project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir()
    (project / "package.json").write_text('{"name": "x", "workspaces": ["apps/*"]}\n')
    (project / "Dockerfile").write_text("FROM oven/bun:1\n")
    apps = project / "apps"
    apps.mkdir()
    api = apps / "api"
    api.mkdir()
    (api / "package.json").write_text('{"name": "api"}\n')
    return project


def _make_python_only_project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return project


def _make_compose_project(root: Path, name: str, compose_name: str = "compose.yaml") -> Path:
    project = root / name
    project.mkdir()
    (project / compose_name).write_text("services:\n  app:\n    image: ghcr.io/example/app:1.0\n")
    return project


async def _enable_my_projects(db, projects_dir: Path) -> None:
    await SettingsService.set(db, "my_projects_enabled", "true")
    await SettingsService.set(db, "my_projects_auto_scan", "true")
    await SettingsService.set(db, "projects_directory", str(projects_dir))
    await SettingsService.set(db, "dockerfile_auto_scan", "false")  # skip side effects


@pytest.fixture
async def projects_tree(tmp_path):
    """Build a realistic projects/ tree that exercises every signal."""
    root = tmp_path / "projects"
    root.mkdir()
    _make_dockerfile_project(root, "dockerfile-only")
    _make_monorepo_project(root, "monorepo")
    _make_python_only_project(root, "python-only")
    _make_compose_project(root, "compose-yaml", "compose.yaml")
    _make_compose_project(root, "compose-yml", "compose.yml")
    _make_compose_project(root, "docker-compose", "docker-compose.yml")

    # Ignored: directory ignore list
    (root / "scripts").mkdir()
    (root / "shared-workflows").mkdir()
    (root / ".hidden").mkdir()

    # Ignored: a directory with no signals at all
    (root / "no-signal").mkdir()
    (root / "no-signal" / "README.md").write_text("just a readme\n")

    return root


@pytest.mark.asyncio
async def test_scanner_discovers_all_signal_types(db, projects_tree):
    await _enable_my_projects(db, projects_tree)

    scanner = ProjectScanner(db)
    result = await scanner.scan_projects_directory()

    assert result.get("error") is None
    assert result["added"] == 6, result

    rows = (await db.execute(select(Container).where(Container.is_my_project))).scalars().all()
    names = {c.name for c in rows}
    assert "dockerfile-only" in names
    assert "monorepo" in names
    assert "python-only" in names
    # Compose-derived rows use the service's container_name (here "app")
    assert "app" in names or "compose-yaml" in names

    # Every row has a project_root set
    for c in rows:
        assert c.project_root, f"{c.name} missing project_root"

    # Compose-independent rows have empty compose_file
    bare = next(c for c in rows if c.name == "dockerfile-only")
    assert bare.compose_file == ""
    assert bare.service_name == "dockerfile-only"
    assert Path(bare.project_root) == projects_tree / "dockerfile-only"


@pytest.mark.asyncio
async def test_scanner_skips_ignored_directories(db, projects_tree):
    await _enable_my_projects(db, projects_tree)
    scanner = ProjectScanner(db)
    result = await scanner.scan_projects_directory()
    assert result.get("error") is None

    rows = (await db.execute(select(Container).where(Container.is_my_project))).scalars().all()
    names = {c.name for c in rows}
    assert "scripts" not in names
    assert "shared-workflows" not in names
    assert ".hidden" not in names
    assert "no-signal" not in names


@pytest.mark.asyncio
async def test_scanner_idempotent_second_run_reports_no_changes(db, projects_tree):
    """A clean re-scan with no real changes must report skipped, not updated.

    Previously every re-scan re-wrote the same fields and counted as 'updated',
    which made the scan summary meaningless. Now `updated` requires a real
    field delta.
    """
    await _enable_my_projects(db, projects_tree)
    scanner = ProjectScanner(db)

    first = await scanner.scan_projects_directory()
    assert first["added"] == 6

    second = await scanner.scan_projects_directory()
    assert second["added"] == 0
    assert second["updated"] == 0
    assert second["skipped"] == 6
    assert second.get("removed", 0) == 0


@pytest.mark.asyncio
async def test_scanner_removes_stale_projects(db, projects_tree):
    await _enable_my_projects(db, projects_tree)
    scanner = ProjectScanner(db)
    await scanner.scan_projects_directory()

    # Delete one project from disk
    import shutil

    shutil.rmtree(projects_tree / "python-only")

    result = await scanner.scan_projects_directory()
    assert result.get("removed", 0) == 1

    rows = (await db.execute(select(Container).where(Container.is_my_project))).scalars().all()
    assert all(c.name != "python-only" for c in rows)


@pytest.mark.asyncio
async def test_scanner_prefers_dockerfile_over_compose(db, tmp_path):
    """When both a Dockerfile and a compose file are at the project root, the
    Dockerfile wins and the project gets the directory name (not the compose
    service's container_name, which may be a `<dirname>-dev` local stub)."""
    projects = tmp_path / "projects"
    projects.mkdir()
    project = projects / "myfinances"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM oven/bun:1.3.14-alpine\n")
    (project / "docker-compose.yml").write_text(
        "services:\n"
        "  myfinances:\n"
        "    image: ghcr.io/homelabforge/myfinances:latest\n"
        "    container_name: myfinances-dev\n"
    )

    await _enable_my_projects(db, projects)
    scanner = ProjectScanner(db)
    await scanner.scan_projects_directory()

    rows = (await db.execute(select(Container).where(Container.is_my_project))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "myfinances", f"expected directory name, got {row.name}"
    assert row.compose_file == "", "Dockerfile signal should produce empty compose_file"


@pytest.mark.asyncio
async def test_scanner_normalizes_legacy_dev_suffix_name(db, tmp_path):
    """A row created by an earlier scanner with name=`myfinances-dev` must be
    normalized to the directory name on the next signal-path scan."""
    projects = tmp_path / "projects"
    projects.mkdir()
    project = projects / "myfinances"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM oven/bun:1.3.14-alpine\n")

    legacy = Container(
        name="myfinances-dev",
        image="ghcr.io/homelabforge/myfinances",
        current_tag="latest",
        registry="ghcr",
        compose_file="",
        service_name="myfinances-dev",
        project_root=str(project),
        is_my_project=True,
    )
    db.add(legacy)
    await db.commit()

    await _enable_my_projects(db, projects)
    scanner = ProjectScanner(db)
    result = await scanner.scan_projects_directory()

    assert result["updated"] == 1
    assert result["skipped"] == 0

    await db.refresh(legacy)
    assert legacy.name == "myfinances"
    assert legacy.service_name == "myfinances"


@pytest.mark.asyncio
async def test_scanner_backfills_legacy_project_root(db, tmp_path):
    """Pre-Phase-0 rows have project_root=None but compose_file set; scanner backfills."""
    projects = tmp_path / "projects"
    projects.mkdir()
    legacy_dir = _make_compose_project(projects, "legacy")

    # Manually insert a legacy row mimicking pre-Phase-0 schema.
    legacy = Container(
        name="app",
        image="ghcr.io/example/app",
        current_tag="1.0",
        registry="dockerhub",
        compose_file=str(legacy_dir / "compose.yaml"),
        service_name="app",
        project_root=None,  # pre-Phase-0
        is_my_project=True,
    )
    db.add(legacy)
    await db.commit()

    await _enable_my_projects(db, projects)
    scanner = ProjectScanner(db)
    await scanner.scan_projects_directory()

    await db.refresh(legacy)
    assert legacy.project_root == str(legacy_dir)


@pytest.mark.asyncio
async def test_scanner_disabled_returns_error(db, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    await SettingsService.set(db, "my_projects_enabled", "false")
    await SettingsService.set(db, "projects_directory", str(projects))

    scanner = ProjectScanner(db)
    result = await scanner.scan_projects_directory()
    assert result["error"] == "Feature disabled"


# ─── resolver call-site regression ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dockerfile_parser_uses_project_root_for_no_compose_row(tmp_path):
    """Regression: DockerfileParser._find_dockerfile must read from project_root
    when the container has no compose_file."""
    from app.services.dockerfile_parser import DockerfileParser

    project = tmp_path / "myapp"
    project.mkdir()
    dockerfile = project / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\n")

    container = SimpleNamespace(
        name="myapp",
        compose_file="",
        project_root=str(project),
        id=1,
    )

    parser = DockerfileParser(projects_directory=str(tmp_path))
    found = await parser._find_dockerfile(container, manual_path=None)
    assert found is not None
    assert found.resolve() == dockerfile.resolve()


@pytest.mark.asyncio
async def test_http_server_scanner_uses_project_root_for_no_compose_row(tmp_path, db):
    """Regression: HttpServerScanner.scan_project_http_servers must read from
    project_root when compose_file is empty."""
    from app.services.http_server_scanner import HttpServerScanner

    project = tmp_path / "bunapp"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM oven/bun:1\nRUN bun install\n")

    await SettingsService.set(db, "projects_directory", str(tmp_path))

    container = SimpleNamespace(
        id=1,
        name="bunapp",
        compose_file="",
        project_root=str(project),
        service_name="bunapp",
    )

    # Patch the network-touching version lookup so we just test detection
    with (
        patch.object(HttpServerScanner, "_get_latest_version", new=AsyncMock(return_value=None)),
        patch.object(HttpServerScanner, "persist_http_servers", new=AsyncMock(return_value=[])),
        patch("app.services.docker_access.make_docker_client", return_value=None),
    ):
        scanner = HttpServerScanner()
        servers = await scanner.scan_project_http_servers(container_model=container, db=db)

    # We don't assert which server is detected — just that the scan ran end-to-end
    # against the project_root path and didn't crash on an empty compose_file.
    assert isinstance(servers, list)


@pytest.mark.asyncio
async def test_dependency_scanner_uses_project_root_for_no_compose_row(tmp_path):
    """Regression: DependencyScanner.scan_container_dependencies must read from
    project_root when called with container= and an empty compose_file."""
    from app.services.app_dependencies import DependencyScanner

    project = tmp_path / "npmapp"
    project.mkdir()
    (project / "package.json").write_text(
        '{"name": "x", "version": "1.0.0", "dependencies": {"react": "^19.0.0"}}\n'
    )

    container = SimpleNamespace(
        compose_file="",
        project_root=str(project),
        service_name="npmapp",
    )

    scanner = DependencyScanner(projects_directory=str(tmp_path))
    deps = await scanner.scan_container_dependencies(
        compose_file="",
        service_name="npmapp",
        container=container,
    )
    await scanner.close()

    # react should be picked up from package.json
    assert any(d.name == "react" for d in deps), [d.name for d in deps]
