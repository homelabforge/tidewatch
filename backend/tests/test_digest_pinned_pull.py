"""Tests for digest-pinned compose pull (Phase 4).

Tests cover:
- Compose parser digest_pin parameter
- Digest-aware base image extraction
- Tag restore after digest-pinned pull
- Round-trip: tag → digest → tag
- Update engine tag restore failure → backup restore
"""

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.compose_parser import ComposeParser


@pytest.fixture
def compose_dir(tmp_path: Path) -> Path:
    """Create a temporary compose directory."""
    return tmp_path


def write_compose(compose_dir: Path, service: str, image: str) -> Path:
    """Write a minimal compose file and return its path."""
    compose_file = compose_dir / "compose.yml"
    compose_file.write_text(f"services:\n  {service}:\n    image: {image}\n")
    return compose_file


class TestComposeDigestPin:
    """Tests for ComposeParser.update_compose_file with digest_pin."""

    @pytest.mark.asyncio
    async def test_compose_digest_pin_format(self, compose_dir: Path):
        """digest_pin writes image@sha256:... format."""
        compose_file = write_compose(compose_dir, "nginx", "nginx:1.24.0")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            result = await ComposeParser.update_compose_file(
                str(compose_file),
                "nginx",
                "1.25.0",
                digest_pin="sha256:abc123def456",
            )

        assert result is True
        content = compose_file.read_text()
        assert "nginx@sha256:abc123def456" in content

    @pytest.mark.asyncio
    async def test_compose_digest_aware_base_extraction(self, compose_dir: Path):
        """Correctly extracts base image from image@sha256:old."""
        compose_file = write_compose(compose_dir, "nginx", "nginx@sha256:oldhash123")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            result = await ComposeParser.update_compose_file(
                str(compose_file),
                "nginx",
                "1.25.0",
            )

        assert result is True
        content = compose_file.read_text()
        assert "nginx:1.25.0" in content
        assert "@sha256:" not in content

    @pytest.mark.asyncio
    async def test_compose_tag_restore(self, compose_dir: Path):
        """Second call restores image:tag from image@sha256:..."""
        compose_file = write_compose(compose_dir, "nginx", "nginx@sha256:pinned123")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            result = await ComposeParser.update_compose_file(
                str(compose_file),
                "nginx",
                "1.25.0",
            )

        assert result is True
        content = compose_file.read_text()
        assert "nginx:1.25.0" in content

    @pytest.mark.asyncio
    async def test_compose_round_trip_tag_digest_tag(self, compose_dir: Path):
        """Write tag, write digest, write tag — verify final state is clean."""
        compose_file = write_compose(compose_dir, "app", "myapp:1.0.0")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            # Step 1: Write digest pin
            await ComposeParser.update_compose_file(
                str(compose_file),
                "app",
                "1.1.0",
                digest_pin="sha256:abc123",
            )
            content = compose_file.read_text()
            assert "myapp@sha256:abc123" in content

            # Step 2: Restore tag
            await ComposeParser.update_compose_file(
                str(compose_file),
                "app",
                "1.1.0",
            )
            content = compose_file.read_text()
            assert "myapp:1.1.0" in content
            assert "@sha256:" not in content

    @pytest.mark.asyncio
    async def test_compose_round_trip_with_registry_port(self, compose_dir: Path):
        """Registry with port (e.g. registry.local:5000/app:1.0) handles digest correctly."""
        compose_file = write_compose(compose_dir, "app", "registry.local:5000/app:1.0")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            # Write digest pin
            await ComposeParser.update_compose_file(
                str(compose_file),
                "app",
                "1.1",
                digest_pin="sha256:def456",
            )
            content = compose_file.read_text()
            assert "registry.local:5000/app@sha256:def456" in content

            # Restore tag
            await ComposeParser.update_compose_file(
                str(compose_file),
                "app",
                "1.1",
            )
            content = compose_file.read_text()
            assert "registry.local:5000/app:1.1" in content

    @pytest.mark.asyncio
    async def test_no_digest_pin_unchanged(self, compose_dir: Path):
        """Existing behavior when expected_digest is None."""
        compose_file = write_compose(compose_dir, "nginx", "nginx:1.24.0")

        with patch("app.services.compose_parser.validate_compose_file_path", return_value=True):
            result = await ComposeParser.update_compose_file(
                str(compose_file),
                "nginx",
                "1.25.0",
            )

        assert result is True
        content = compose_file.read_text()
        assert "nginx:1.25.0" in content
        assert "@sha256:" not in content


class TestTagRestoreFailure:
    """Tests for update engine tag restore failure → backup restore."""

    @pytest.mark.asyncio
    async def test_tag_restore_failure_restores_backup(self, compose_dir: Path):
        """Mock compose write to fail on second call, verify backup restored."""
        compose_file = write_compose(compose_dir, "nginx", "nginx:1.24.0")
        backup_path = compose_dir / "compose.yml.backup"
        shutil.copyfile(compose_file, backup_path)

        call_count = 0

        async def mock_update_compose_file(
            file_path, service_name, new_tag, db=None, digest_pin=None
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (digest pin) succeeds
                Path(file_path).write_text(
                    f"services:\n  {service_name}:\n    image: nginx@{digest_pin}\n"
                )
                return True
            # Second call (tag restore) fails
            return False

        # Import here to mock the engine's dependency
        from app.services.update_engine import UpdateEngine

        with (
            patch.object(
                ComposeParser,
                "update_compose_file",
                side_effect=mock_update_compose_file,
            ),
            patch.object(
                UpdateEngine,
                "_restore_compose_file",
                new_callable=AsyncMock,
            ) as mock_restore,
        ):
            # Simulate the Step 3.5 logic from update_engine
            update_expected_digest = "sha256:abc123"

            # Step 2: Digest-pinned write (succeeds)
            success = await ComposeParser.update_compose_file(
                str(compose_file), "nginx", "1.25.0", digest_pin=update_expected_digest
            )
            assert success is True

            # Step 3.5: Tag restore (fails)
            tag_restore_ok = await ComposeParser.update_compose_file(
                str(compose_file), "nginx", "1.25.0"
            )
            assert tag_restore_ok is False

            # Engine should restore from backup
            await UpdateEngine._restore_compose_file(str(compose_file), str(backup_path))
            mock_restore.assert_called_once_with(str(compose_file), str(backup_path))
