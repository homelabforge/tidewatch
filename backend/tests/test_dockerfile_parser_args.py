"""Tests for Dockerfile ARG expansion in DockerfileParser._parse_dockerfile.

Regression for the MyFinances case where the parser persisted FROM lines like
``oven/bun:${BUN_VERSION}-alpine`` literally instead of expanding the ARG.
"""

from pathlib import Path

import pytest

from app.services.dockerfile_parser import (
    DockerfileParser,
    _expand_args,
    _strip_quotes,
)

# ─── helpers ─────────────────────────────────────────────────────────────────


def test_strip_quotes_removes_matching_pair():
    assert _strip_quotes('"1.3.14"') == "1.3.14"
    assert _strip_quotes("'1.3.14'") == "1.3.14"
    assert _strip_quotes("1.3.14") == "1.3.14"
    # Mismatched quotes are left alone
    assert _strip_quotes('"1.3.14') == '"1.3.14'


def test_expand_args_basic_substitution():
    expanded, unresolved = _expand_args("oven/bun:${BUN_VERSION}-alpine", {"BUN_VERSION": "1.3.14"})
    assert expanded == "oven/bun:1.3.14-alpine"
    assert unresolved == set()


def test_expand_args_bare_variable():
    expanded, unresolved = _expand_args("oven/bun:$BUN_VERSION", {"BUN_VERSION": "1.3.14"})
    assert expanded == "oven/bun:1.3.14"
    assert unresolved == set()


def test_expand_args_default_value():
    expanded, unresolved = _expand_args("oven/bun:${BUN_VERSION:-1.0.0}-alpine", {})
    assert expanded == "oven/bun:1.0.0-alpine"
    assert unresolved == set()


def test_expand_args_unresolved_reports_missing():
    expanded, unresolved = _expand_args("oven/bun:${BUN_VERSION}-alpine", {})
    assert expanded == "oven/bun:${BUN_VERSION}-alpine"
    assert unresolved == {"BUN_VERSION"}


def test_expand_args_mixed_resolved_and_unresolved():
    expanded, unresolved = _expand_args(
        "${REGISTRY}/oven/bun:${BUN_VERSION}-alpine",
        {"REGISTRY": "ghcr.io"},
    )
    assert expanded == "ghcr.io/oven/bun:${BUN_VERSION}-alpine"
    assert unresolved == {"BUN_VERSION"}


# ─── parser integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_dockerfile_expands_arg_in_from(tmp_path):
    """The MyFinances scenario: ARG BUN_VERSION=1.3.14 / FROM oven/bun:${BUN_VERSION}-alpine."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG BUN_VERSION=1.3.14\n"
        "FROM oven/bun:${BUN_VERSION}-alpine AS deps\n"
        "FROM oven/bun:${BUN_VERSION}-alpine AS build\n"
        "FROM oven/bun:${BUN_VERSION}-alpine AS runtime\n"
    )

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    assert len(deps) == 3
    for dep in deps:
        assert dep.image_name == "oven/bun"
        assert dep.current_tag == "1.3.14-alpine"
        assert dep.full_image == "oven/bun:1.3.14-alpine"
    assert {d.stage_name for d in deps} == {"deps", "build", "runtime"}


@pytest.mark.asyncio
async def test_parse_dockerfile_handles_quoted_arg_value(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text('ARG BUN_VERSION="1.3.14"\nFROM oven/bun:${BUN_VERSION}-alpine AS deps\n')

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    assert len(deps) == 1
    assert deps[0].current_tag == "1.3.14-alpine"


@pytest.mark.asyncio
async def test_parse_dockerfile_skips_unresolved_arg(tmp_path):
    """An ARG without a default and never set elsewhere should drop the FROM
    rather than persist a literal `${VAR}` tag."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG BUN_VERSION\nFROM oven/bun:${BUN_VERSION}-alpine AS deps\n"
        "FROM python:3.14-slim AS base\n"
    )

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    # The bun stage drops out; the python base stage stays.
    names = [d.image_name for d in deps]
    assert names == ["python"]


@pytest.mark.asyncio
async def test_parse_dockerfile_arg_redeclaration_updates_value(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG BUN_VERSION=1.0.0\n"
        "FROM oven/bun:${BUN_VERSION}-alpine AS deps\n"
        "ARG BUN_VERSION=1.3.14\n"
        "FROM oven/bun:${BUN_VERSION}-alpine AS build\n"
    )

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    by_stage = {d.stage_name: d for d in deps}
    assert by_stage["deps"].current_tag == "1.0.0-alpine"
    assert by_stage["build"].current_tag == "1.3.14-alpine"


@pytest.mark.asyncio
async def test_parse_dockerfile_arg_without_default_falls_back(tmp_path):
    """`ARG VAR` without a value but with `${VAR:-default}` reference resolves
    via the default."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG BUN_VERSION\nFROM oven/bun:${BUN_VERSION:-1.3.14}-alpine AS deps\n")

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    assert len(deps) == 1
    assert deps[0].current_tag == "1.3.14-alpine"


@pytest.mark.asyncio
async def test_parse_dockerfile_no_args_unchanged(tmp_path: Path):
    """Existing baseline behavior — no ARGs in Dockerfile, plain FROM unchanged."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\nFROM node:22-alpine AS build\n")

    parser = DockerfileParser(projects_directory=str(tmp_path))
    deps = await parser._parse_dockerfile(dockerfile, container_id=1)

    assert {d.image_name for d in deps} == {"python", "node"}
    assert {d.current_tag for d in deps} == {"3.14-slim", "22-alpine"}
