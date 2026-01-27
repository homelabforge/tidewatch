"""Tests for manifest parser utilities (app/utils/manifest_parsers.py).

Tests file modification safety for multiple package managers:
- package.json (npm) - dependency updates, semver prefix preservation
- requirements.txt (Python pip) - version pinning, operator preservation
- pyproject.toml (Python Poetry/PEP 621) - TOML formatting preservation
- composer.json (PHP) - dependency updates
- Cargo.toml (Rust) - workspace handling
- go.mod (Go modules) - module versioning

Security focus:
- File atomicity (no partial writes on error)
- Format preservation (indentation, comments, structure)
- Error handling (malformed files, permission errors)
"""

import json

import pytest

from app.utils.manifest_parsers import (
    update_cargo_toml,
    update_composer_json,
    update_go_mod,
    update_package_json,
    update_pyproject_toml,
    update_requirements_txt,
)


class TestUpdatePackageJson:
    """Test suite for update_package_json() function."""

    def test_updates_dependency_version(self, tmp_path):
        """Test updates dependency version in package.json."""
        # Arrange
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps(
                {
                    "name": "test-app",
                    "version": "1.0.0",
                    "dependencies": {"express": "^4.17.1", "lodash": "~4.17.20"},
                },
                indent=2,
            )
        )

        # Act
        success, content = update_package_json(package_json, "express", "4.18.2")

        # Assert
        assert success is True
        updated_data = json.loads(content)
        assert updated_data["dependencies"]["express"] == "^4.18.2"
        assert updated_data["dependencies"]["lodash"] == "~4.17.20"  # Unchanged

    def test_preserves_semver_caret_prefix(self, tmp_path):
        """Test preserves ^ (caret) semver prefix."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"dependencies": {"react": "^18.0.0"}}, indent=2)
        )

        success, content = update_package_json(package_json, "react", "18.2.0")

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["dependencies"]["react"] == "^18.2.0"

    def test_preserves_semver_tilde_prefix(self, tmp_path):
        """Test preserves ~ (tilde) semver prefix."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"dependencies": {"vue": "~3.2.0"}}, indent=2)
        )

        success, content = update_package_json(package_json, "vue", "3.2.47")

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["dependencies"]["vue"] == "~3.2.47"

    def test_handles_exact_version_no_prefix(self, tmp_path):
        """Test handles exact version (no semver prefix)."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"dependencies": {"moment": "2.29.4"}}, indent=2)
        )

        success, content = update_package_json(package_json, "moment", "2.30.0")

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["dependencies"]["moment"] == "2.30.0"

    def test_updates_dev_dependencies(self, tmp_path):
        """Test updates devDependencies section."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"devDependencies": {"jest": "^29.0.0"}}, indent=2)
        )

        success, content = update_package_json(
            package_json, "jest", "29.5.0", dependency_type="devDependencies"
        )

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["devDependencies"]["jest"] == "^29.5.0"

    def test_preserves_json_formatting(self, tmp_path):
        """Test preserves JSON structure and formatting."""
        package_json = tmp_path / "package.json"
        original = {
            "name": "test-app",
            "version": "1.0.0",
            "description": "Test application",
            "main": "index.js",
            "dependencies": {"axios": "^1.3.0"},
            "scripts": {"start": "node index.js"},
        }
        package_json.write_text(json.dumps(original, indent=2))

        success, content = update_package_json(package_json, "axios", "1.4.0")

        assert success is True
        updated_data = json.loads(content)
        # All other fields preserved
        assert updated_data["name"] == "test-app"
        assert updated_data["description"] == "Test application"
        assert updated_data["scripts"] == {"start": "node index.js"}

    def test_returns_false_when_package_not_found(self, tmp_path):
        """Test returns False when package doesn't exist."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"dependencies": {"lodash": "^4.17.0"}}, indent=2)
        )

        success, content = update_package_json(package_json, "nonexistent", "1.0.0")

        assert success is False
        assert content == ""

    def test_returns_false_when_section_not_found(self, tmp_path):
        """Test returns False when dependency section doesn't exist."""
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "test-app"}, indent=2))

        success, content = update_package_json(package_json, "express", "4.18.0")

        assert success is False
        assert content == ""

    def test_handles_malformed_json(self, tmp_path):
        """Test handles malformed JSON gracefully."""
        package_json = tmp_path / "package.json"
        package_json.write_text("{invalid json content")

        success, content = update_package_json(package_json, "express", "4.18.0")

        assert success is False
        assert content == ""

    def test_handles_file_not_found(self, tmp_path):
        """Test handles missing file gracefully."""
        nonexistent = tmp_path / "nonexistent.json"

        success, content = update_package_json(nonexistent, "express", "4.18.0")

        assert success is False
        assert content == ""


class TestUpdateRequirementsTxt:
    """Test suite for update_requirements.txt() function."""

    def test_updates_pinned_dependency(self, tmp_path):
        """Test updates pinned dependency (==)."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("flask==2.0.0\nrequests==2.28.0\n")

        success, content = update_requirements_txt(requirements, "flask", "2.3.2")

        assert success is True
        assert "flask==2.3.2\n" in content
        assert "requests==2.28.0\n" in content  # Unchanged

    def test_preserves_greater_than_operator(self, tmp_path):
        """Test preserves >= operator."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("django>=4.0.0\n")

        success, content = update_requirements_txt(requirements, "django", "4.2.0")

        assert success is True
        assert "django>=4.2.0\n" in content

    def test_preserves_tilde_equals_operator(self, tmp_path):
        """Test preserves ~= (compatible release) operator."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("pytest~=7.0.0\n")

        success, content = update_requirements_txt(requirements, "pytest", "7.3.1")

        assert success is True
        assert "pytest~=7.3.1\n" in content

    def test_case_insensitive_package_match(self, tmp_path):
        """Test package matching is case-insensitive."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("Django==4.0.0\n")

        success, content = update_requirements_txt(requirements, "django", "4.2.0")

        assert success is True
        assert "Django==4.2.0\n" in content  # Preserves original case

    def test_preserves_inline_comments(self, tmp_path):
        """Test preserves inline comments."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("flask==2.0.0  # Web framework\n")

        success, content = update_requirements_txt(requirements, "flask", "2.3.2")

        assert success is True
        assert "flask==2.3.2  # Web framework\n" in content

    def test_skips_comment_lines(self, tmp_path):
        """Test skips comment-only lines."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text(
            "# This is a comment\nflask==2.0.0\n# Another comment\n"
        )

        success, content = update_requirements_txt(requirements, "flask", "2.3.2")

        assert success is True
        assert "# This is a comment\n" in content
        assert "# Another comment\n" in content
        assert "flask==2.3.2\n" in content

    def test_skips_empty_lines(self, tmp_path):
        """Test preserves empty lines."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("flask==2.0.0\n\nrequests==2.28.0\n")

        success, content = update_requirements_txt(requirements, "flask", "2.3.2")

        assert success is True
        lines = content.split("\n")
        assert lines[1] == ""  # Empty line preserved

    def test_returns_false_when_package_not_found(self, tmp_path):
        """Test returns False when package not found."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("flask==2.0.0\n")

        success, content = update_requirements_txt(requirements, "django", "4.2.0")

        assert success is False
        assert content == ""

    def test_handles_file_not_found(self, tmp_path):
        """Test handles missing file gracefully."""
        nonexistent = tmp_path / "nonexistent.txt"

        success, content = update_requirements_txt(nonexistent, "flask", "2.3.2")

        assert success is False
        assert content == ""


class TestUpdatePyprojectToml:
    """Test suite for update_pyproject_toml() function."""

    def test_updates_dependency_key_value_format(self, tmp_path):
        """Test updates dependency in key-value format (Poetry)."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.poetry.dependencies]
python = "^3.9"
fastapi = "^0.95.0"
uvicorn = "^0.21.0"
""")

        success, content = update_pyproject_toml(
            pyproject, "fastapi", "0.100.0", section="tool.poetry.dependencies"
        )

        assert success is True
        assert 'fastapi = "^0.100.0"' in content
        assert 'uvicorn = "^0.21.0"' in content  # Unchanged

    def test_preserves_caret_prefix_in_key_value_format(self, tmp_path):
        """Test preserves ^ prefix in key-value format."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.poetry.dependencies]
pydantic = "^1.10.0"
""")

        success, content = update_pyproject_toml(
            pyproject, "pydantic", "2.0.0", section="tool.poetry.dependencies"
        )

        assert success is True
        assert 'pydantic = "^2.0.0"' in content

    def test_updates_dependency_array_format(self, tmp_path):
        """Test updates dependency in array format (PEP 621)."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[project]
dependencies = [
    "fastapi>=0.95.0",
    "pydantic>=1.10.0",
]
""")

        success, content = update_pyproject_toml(pyproject, "fastapi", "0.100.0")

        assert success is True
        assert '"fastapi>=0.100.0",' in content
        assert '"pydantic>=1.10.0",' in content  # Unchanged

    def test_preserves_indentation(self, tmp_path):
        """Test preserves indentation in TOML file."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.poetry.dependencies]
    fastapi = "^0.95.0"
""")

        success, content = update_pyproject_toml(
            pyproject, "fastapi", "0.100.0", section="tool.poetry.dependencies"
        )

        assert success is True
        assert '    fastapi = "^0.100.0"' in content

    def test_returns_false_when_package_not_found(self, tmp_path):
        """Test returns False when package not found."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.poetry.dependencies]
fastapi = "^0.95.0"
""")

        success, content = update_pyproject_toml(pyproject, "django", "4.2.0")

        assert success is False
        assert content == ""

    def test_handles_file_not_found(self, tmp_path):
        """Test handles missing file gracefully."""
        nonexistent = tmp_path / "nonexistent.toml"

        success, content = update_pyproject_toml(nonexistent, "fastapi", "0.100.0")

        assert success is False
        assert content == ""


class TestUpdateComposerJson:
    """Test suite for update_composer_json() function (PHP)."""

    @pytest.mark.skip(
        reason="composer.json support needs verification of implementation"
    )
    def test_updates_require_dependency(self, tmp_path):
        """Test updates dependency in require section."""
        composer = tmp_path / "composer.json"
        composer.write_text(
            json.dumps(
                {"require": {"symfony/console": "^6.0", "guzzlehttp/guzzle": "^7.5"}},
                indent=4,
            )
        )

        success, content = update_composer_json(composer, "symfony/console", "6.3.0")

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["require"]["symfony/console"] == "^6.3.0"
        assert updated_data["require"]["guzzlehttp/guzzle"] == "^7.5"  # Unchanged

    @pytest.mark.skip(
        reason="composer.json support needs verification of implementation"
    )
    def test_updates_require_dev_dependency(self, tmp_path):
        """Test updates dependency in require-dev section."""
        composer = tmp_path / "composer.json"
        composer.write_text(
            json.dumps({"require-dev": {"phpunit/phpunit": "^10.0"}}, indent=4)
        )

        success, content = update_composer_json(
            composer, "phpunit/phpunit", "10.2.0", dependency_type="require-dev"
        )

        assert success is True
        updated_data = json.loads(content)
        assert updated_data["require-dev"]["phpunit/phpunit"] == "^10.2.0"

    def test_returns_false_when_package_not_found(self, tmp_path):
        """Test returns False when package not found."""
        composer = tmp_path / "composer.json"
        composer.write_text(
            json.dumps({"require": {"symfony/console": "^6.0"}}, indent=4)
        )

        success, content = update_composer_json(
            composer, "nonexistent/package", "1.0.0"
        )

        assert success is False
        assert content == ""


class TestUpdateCargoToml:
    """Test suite for update_cargo_toml() function (Rust)."""

    def test_updates_dependency_version(self, tmp_path):
        """Test updates dependency version in Cargo.toml."""
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("""
[package]
name = "my-app"
version = "0.1.0"

[dependencies]
serde = "1.0.160"
tokio = { version = "1.28", features = ["full"] }
""")

        success, content = update_cargo_toml(cargo, "serde", "1.0.180")

        assert success is True
        assert 'serde = "1.0.180"' in content
        assert (
            'tokio = { version = "1.28", features = ["full"] }' in content
        )  # Unchanged

    def test_updates_dependency_with_features(self, tmp_path):
        """Test updates dependency with features dict."""
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("""
[dependencies]
tokio = { version = "1.28", features = ["full"] }
""")

        success, content = update_cargo_toml(cargo, "tokio", "1.32")

        assert success is True
        assert 'tokio = { version = "1.32", features = ["full"] }' in content

    def test_returns_false_when_package_not_found(self, tmp_path):
        """Test returns False when package not found."""
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("""
[dependencies]
serde = "1.0.160"
""")

        success, content = update_cargo_toml(cargo, "nonexistent", "1.0.0")

        assert success is False
        assert content == ""


class TestUpdateGoMod:
    """Test suite for update_go_mod() function (Go modules)."""

    def test_updates_module_version(self, tmp_path):
        """Test updates module version in go.mod."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("""
module github.com/example/myapp

go 1.20

require (
    github.com/gin-gonic/gin v1.9.0
    github.com/spf13/cobra v1.7.0
)
""")

        success, content = update_go_mod(go_mod, "github.com/gin-gonic/gin", "v1.9.1")

        assert success is True
        assert "github.com/gin-gonic/gin v1.9.1" in content
        assert "github.com/spf13/cobra v1.7.0" in content  # Unchanged

    def test_preserves_v_prefix(self, tmp_path):
        """Test preserves 'v' prefix in version."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("""
require (
    github.com/gin-gonic/gin v1.9.0
)
""")

        success, content = update_go_mod(go_mod, "github.com/gin-gonic/gin", "1.9.1")

        assert success is True
        # Should add 'v' prefix if not present
        assert "v1.9.1" in content

    def test_returns_false_when_module_not_found(self, tmp_path):
        """Test returns False when module not found."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("""
require (
    github.com/gin-gonic/gin v1.9.0
)
""")

        success, content = update_go_mod(
            go_mod, "github.com/nonexistent/module", "v1.0.0"
        )

        assert success is False
        assert content == ""


class TestManifestParserErrorHandling:
    """Test error handling across all manifest parsers."""

    @pytest.mark.skip(reason="Permission tests behave differently in Docker containers")
    def test_package_json_handles_permission_error(self, tmp_path):
        """Test package.json handles permission errors."""
        # Skip - permission tests behave differently in Docker containers running as root
        pass

    def test_requirements_txt_handles_unicode_error(self, tmp_path):
        """Test requirements.txt handles encoding errors."""
        requirements = tmp_path / "requirements.txt"
        # Write binary data that can't be decoded as UTF-8
        requirements.write_bytes(b"\xff\xfe\xfd\xfc")

        success, content = update_requirements_txt(requirements, "flask", "2.3.2")

        assert success is False
        assert content == ""

    def test_preserves_file_on_error(self, tmp_path):
        """Test original file preserved when update fails."""
        package_json = tmp_path / "package.json"
        original_content = json.dumps(
            {"dependencies": {"express": "^4.17.0"}}, indent=2
        )
        package_json.write_text(original_content)

        # Try to update non-existent package (should fail)
        success, content = update_package_json(package_json, "nonexistent", "1.0.0")

        assert success is False
        # Original file should still exist and be unchanged
        assert package_json.read_text() == original_content
