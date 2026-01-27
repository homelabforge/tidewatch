"""Tests for version comparison utilities (app/utils/version.py).

Tests semantic versioning (semver) parsing and comparison:
- Version parsing (major.minor.patch)
- Version change type detection (major, minor, patch)
- Prefix handling (v prefix)
- Suffix handling (-alpine, -slim, etc.)
- Edge cases (missing parts, invalid formats)
"""

import pytest

from app.utils.version import (
    get_version_change_type,
    is_major_update,
    is_minor_or_patch_update,
    is_patch_update,
    parse_version,
)


class TestParseVersion:
    """Test suite for parse_version() function."""

    def test_parses_standard_semver(self):
        """Test parses standard semantic version."""
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("0.0.1") == (0, 0, 1)
        assert parse_version("10.20.30") == (10, 20, 30)

    def test_parses_version_with_v_prefix(self):
        """Test parses version with 'v' prefix."""
        assert parse_version("v1.2.3") == (1, 2, 3)
        assert parse_version("v2.0.0") == (2, 0, 0)

    def test_parses_version_with_suffix(self):
        """Test parses version with suffix (e.g., -alpine)."""
        assert parse_version("3.14-alpine") == (3, 14, 0)
        assert parse_version("1.2.3-slim") == (1, 2, 3)
        assert parse_version("2.5-rc1") == (2, 5, 0)

    def test_parses_version_with_underscore_suffix(self):
        """Test parses version with underscore suffix."""
        assert parse_version("1.2.3_build123") == (1, 2, 3)

    def test_defaults_missing_minor_to_zero(self):
        """Test defaults missing minor version to 0."""
        assert parse_version("5") == (5, 0, 0)

    def test_defaults_missing_patch_to_zero(self):
        """Test defaults missing patch version to 0."""
        assert parse_version("3.14") == (3, 14, 0)

    def test_parses_double_digit_versions(self):
        """Test parses double-digit version numbers."""
        assert parse_version("12.34.56") == (12, 34, 56)

    def test_parses_large_version_numbers(self):
        """Test parses large version numbers."""
        assert parse_version("100.200.300") == (100, 200, 300)

    def test_handles_v_prefix_with_suffix(self):
        """Test handles both v prefix and suffix."""
        assert parse_version("v3.14-alpine") == (3, 14, 0)

    def test_raises_on_empty_string(self):
        """Test raises ValueError on empty version string."""
        with pytest.raises(ValueError, match="invalid literal for int"):
            parse_version("")

    def test_raises_on_non_numeric_major(self):
        """Test raises ValueError on non-numeric version parts."""
        with pytest.raises(ValueError):
            parse_version("abc.def.ghi")

    def test_raises_on_invalid_format(self):
        """Test raises ValueError on completely invalid format."""
        with pytest.raises(ValueError):
            parse_version("not-a-version")


class TestGetVersionChangeType:
    """Test suite for get_version_change_type() function."""

    def test_detects_major_version_change(self):
        """Test detects major version change."""
        assert get_version_change_type("1.0.0", "2.0.0") == "major"
        assert get_version_change_type("1.5.3", "2.0.0") == "major"
        assert get_version_change_type("0.9.9", "1.0.0") == "major"

    def test_detects_minor_version_change(self):
        """Test detects minor version change."""
        assert get_version_change_type("1.0.0", "1.1.0") == "minor"
        assert get_version_change_type("2.5.0", "2.6.0") == "minor"
        assert get_version_change_type("1.0.5", "1.1.0") == "minor"

    def test_detects_patch_version_change(self):
        """Test detects patch version change."""
        assert get_version_change_type("1.0.0", "1.0.1") == "patch"
        assert get_version_change_type("2.5.3", "2.5.4") == "patch"
        assert get_version_change_type("1.0.0", "1.0.10") == "patch"

    def test_returns_none_for_no_change(self):
        """Test returns None when versions are identical."""
        assert get_version_change_type("1.0.0", "1.0.0") is None
        assert get_version_change_type("2.5.3", "2.5.3") is None

    def test_returns_none_for_downgrade(self):
        """Test returns None for version downgrade."""
        assert get_version_change_type("2.0.0", "1.0.0") is None
        assert get_version_change_type("1.5.0", "1.4.0") is None
        assert get_version_change_type("1.0.5", "1.0.4") is None

    def test_handles_v_prefix_in_both_versions(self):
        """Test handles v prefix in version strings."""
        assert get_version_change_type("v1.0.0", "v2.0.0") == "major"
        assert get_version_change_type("v1.0.0", "v1.1.0") == "minor"

    def test_handles_suffixes_in_both_versions(self):
        """Test handles version suffixes."""
        assert get_version_change_type("1.0.0-alpine", "2.0.0-alpine") == "major"
        assert get_version_change_type("1.0.0-slim", "1.1.0-slim") == "minor"

    def test_handles_mixed_formats(self):
        """Test handles mixed version formats."""
        assert get_version_change_type("v1.0.0-alpine", "2.0") == "major"
        assert get_version_change_type("1.0", "1.1.0-slim") == "minor"

    def test_returns_none_for_invalid_from_version(self):
        """Test returns None when from_version is invalid."""
        assert get_version_change_type("invalid", "2.0.0") is None

    def test_returns_none_for_invalid_to_version(self):
        """Test returns None when to_version is invalid."""
        assert get_version_change_type("1.0.0", "invalid") is None

    def test_returns_none_for_both_invalid(self):
        """Test returns None when both versions are invalid."""
        assert get_version_change_type("invalid", "also-invalid") is None

    def test_major_takes_precedence_over_minor(self):
        """Test major version change takes precedence."""
        # Even if minor/patch also increased
        assert get_version_change_type("1.0.0", "2.5.3") == "major"

    def test_minor_takes_precedence_over_patch(self):
        """Test minor version change takes precedence."""
        # Even if patch also increased
        assert get_version_change_type("1.0.0", "1.1.5") == "minor"


class TestIsMajorUpdate:
    """Test suite for is_major_update() function."""

    def test_returns_true_for_major_update(self):
        """Test returns True for major version updates."""
        assert is_major_update("1.0.0", "2.0.0") is True
        assert is_major_update("0.9.9", "1.0.0") is True

    def test_returns_false_for_minor_update(self):
        """Test returns False for minor version updates."""
        assert is_major_update("1.0.0", "1.1.0") is False

    def test_returns_false_for_patch_update(self):
        """Test returns False for patch version updates."""
        assert is_major_update("1.0.0", "1.0.1") is False

    def test_returns_false_for_no_change(self):
        """Test returns False when no version change."""
        assert is_major_update("1.0.0", "1.0.0") is False

    def test_returns_false_for_invalid_versions(self):
        """Test returns False for invalid version strings."""
        assert is_major_update("invalid", "2.0.0") is False
        assert is_major_update("1.0.0", "invalid") is False


class TestIsMinorOrPatchUpdate:
    """Test suite for is_minor_or_patch_update() function."""

    def test_returns_true_for_minor_update(self):
        """Test returns True for minor version updates."""
        assert is_minor_or_patch_update("1.0.0", "1.1.0") is True
        assert is_minor_or_patch_update("2.5.0", "2.6.0") is True

    def test_returns_true_for_patch_update(self):
        """Test returns True for patch version updates."""
        assert is_minor_or_patch_update("1.0.0", "1.0.1") is True
        assert is_minor_or_patch_update("2.5.3", "2.5.4") is True

    def test_returns_false_for_major_update(self):
        """Test returns False for major version updates."""
        assert is_minor_or_patch_update("1.0.0", "2.0.0") is False

    def test_returns_false_for_no_change(self):
        """Test returns False when no version change."""
        assert is_minor_or_patch_update("1.0.0", "1.0.0") is False

    def test_returns_false_for_invalid_versions(self):
        """Test returns False for invalid version strings."""
        assert is_minor_or_patch_update("invalid", "1.1.0") is False


class TestIsPatchUpdate:
    """Test suite for is_patch_update() function."""

    def test_returns_true_for_patch_update(self):
        """Test returns True for patch version updates only."""
        assert is_patch_update("1.0.0", "1.0.1") is True
        assert is_patch_update("2.5.3", "2.5.10") is True

    def test_returns_false_for_minor_update(self):
        """Test returns False for minor version updates."""
        assert is_patch_update("1.0.0", "1.1.0") is False

    def test_returns_false_for_major_update(self):
        """Test returns False for major version updates."""
        assert is_patch_update("1.0.0", "2.0.0") is False

    def test_returns_false_for_no_change(self):
        """Test returns False when no version change."""
        assert is_patch_update("1.0.0", "1.0.0") is False

    def test_returns_false_for_invalid_versions(self):
        """Test returns False for invalid version strings."""
        assert is_patch_update("invalid", "1.0.1") is False


class TestVersionEdgeCases:
    """Test edge cases and real-world version scenarios."""

    def test_docker_image_tags(self):
        """Test common Docker image tag formats."""
        # Alpine variants
        assert parse_version("3.14-alpine") == (3, 14, 0)
        assert get_version_change_type("3.14-alpine", "3.15-alpine") == "minor"

        # Slim variants
        assert parse_version("11-slim") == (11, 0, 0)

        # Node.js style
        assert parse_version("18.16.0") == (18, 16, 0)

    def test_python_versions(self):
        """Test Python version formats."""
        assert get_version_change_type("3.9.0", "3.10.0") == "minor"
        assert get_version_change_type("3.11.4", "3.11.5") == "patch"

    def test_zero_versions(self):
        """Test versions starting with 0 (pre-1.0 projects)."""
        assert get_version_change_type("0.1.0", "0.2.0") == "minor"
        assert get_version_change_type("0.0.1", "0.0.2") == "patch"
        assert get_version_change_type("0.9.9", "1.0.0") == "major"

    def test_large_version_jumps(self):
        """Test large version number increases."""
        assert get_version_change_type("1.0.0", "100.0.0") == "major"
        assert get_version_change_type("1.0.0", "1.99.0") == "minor"
        assert get_version_change_type("1.0.0", "1.0.999") == "patch"

    def test_calendar_versioning(self):
        """Test calendar-style versioning (YYYY.MM)."""
        # These are treated as major.minor.0
        assert parse_version("2024.01") == (2024, 1, 0)
        assert get_version_change_type("2024.01", "2024.02") == "minor"
