"""Tests for Cleanup API (app/api/cleanup.py).

Tests cleanup task endpoints:
- POST /api/v1/cleanup/images - Clean up unused Docker images
- POST /api/v1/cleanup/containers - Clean up exited containers
- GET /api/v1/cleanup/stats - Get disk usage stats
- GET /api/v1/cleanup/preview - Preview cleanup
- GET /api/v1/cleanup/settings - Get cleanup settings
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import status


class TestCleanupImagesEndpoint:
    """Test suite for POST /api/v1/cleanup/images endpoint."""

    async def test_cleanup_dangling_images(self, authenticated_client, db):
        """Test removes dangling Docker images."""
        # Mock CleanupService
        with patch('app.api.cleanup.CleanupService.prune_dangling_images', new_callable=AsyncMock) as mock_prune:
            mock_prune.return_value = {
                "images_removed": 5,
                "space_reclaimed": 1024 * 1024 * 100  # 100 MB
            }

            # Act
            response = await authenticated_client.post("/api/v1/cleanup/images?dangling_only=true")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["images_removed"] == 5
            assert data["space_reclaimed"] == 1024 * 1024 * 100
            assert "space_reclaimed_formatted" in data
            mock_prune.assert_called_once()

    async def test_cleanup_old_images_by_age(self, authenticated_client, db):
        """Test removes images older than specified days."""
        # Mock CleanupService methods
        with patch('app.api.cleanup.CleanupService.prune_dangling_images', new_callable=AsyncMock) as mock_prune_dangling, \
             patch('app.api.cleanup.CleanupService.cleanup_old_images', new_callable=AsyncMock) as mock_cleanup_old:

            mock_prune_dangling.return_value = {
                "images_removed": 2,
                "space_reclaimed": 1024 * 1024 * 50
            }
            mock_cleanup_old.return_value = {
                "images_removed": 3,
                "space_reclaimed": 1024 * 1024 * 150
            }

            # Act
            response = await authenticated_client.post("/api/v1/cleanup/images?dangling_only=false&older_than_days=30")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["images_removed"] == 5  # 2 + 3
            assert data["space_reclaimed"] == 1024 * 1024 * 200  # 50 MB + 150 MB
            mock_prune_dangling.assert_called_once()
            mock_cleanup_old.assert_called_once()

    async def test_cleanup_preview_mode(self, authenticated_client, db):
        """Test preview mode returns list without deleting."""
        # Mock preview method
        with patch('app.api.cleanup.CleanupService.get_cleanup_preview', new_callable=AsyncMock) as mock_preview:
            mock_preview.return_value = {
                "images_to_remove": 3,
                "space_to_reclaim": 1024 * 1024 * 75,
                "image_list": ["nginx:old", "redis:old", "postgres:old"]
            }

            # Act
            response = await authenticated_client.get("/api/v1/cleanup/preview")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "preview" in data
            assert data["preview"]["images_to_remove"] == 3
            assert "settings" in data
            mock_preview.assert_called_once()

    async def test_cleanup_requires_auth(self, client):
        """Test requires authentication."""
        # Act
        response = await client.post("/api/v1/cleanup/images")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCleanupContainersEndpoint:
    """Test suite for POST /api/v1/cleanup/containers endpoint."""

    async def test_cleanup_exited_containers(self, authenticated_client, db):
        """Test removes exited containers."""
        # Mock CleanupService
        with patch('app.api.cleanup.CleanupService.prune_exited_containers', new_callable=AsyncMock) as mock_prune:
            mock_prune.return_value = {
                "success": True,
                "containers_removed": 3,
                "space_reclaimed": 1024 * 1024 * 10
            }

            # Act
            response = await authenticated_client.post("/api/v1/cleanup/containers")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["containers_removed"] == 3
            mock_prune.assert_called_once()

    async def test_cleanup_respects_exclude_patterns(self, authenticated_client, db):
        """Test respects configured exclude patterns."""
        # Set exclude patterns in settings
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "cleanup_exclude_patterns", "-dev,-test,rollback")
        await db.commit()

        # Mock CleanupService
        with patch('app.api.cleanup.CleanupService.prune_exited_containers', new_callable=AsyncMock) as mock_prune:
            mock_prune.return_value = {
                "success": True,
                "containers_removed": 2,
                "space_reclaimed": 1024 * 1024 * 5
            }

            # Act
            response = await authenticated_client.post("/api/v1/cleanup/containers")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            # Verify exclude patterns were passed to service
            call_args = mock_prune.call_args[0]
            assert "-dev" in call_args[0]
            assert "-test" in call_args[0]
            assert "rollback" in call_args[0]

    async def test_cleanup_containers_requires_auth(self, client):
        """Test requires authentication."""
        # Act
        response = await client.post("/api/v1/cleanup/containers")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCleanupStatsEndpoint:
    """Test suite for GET /api/v1/cleanup/stats endpoint."""

    async def test_stats_returns_disk_usage(self, authenticated_client):
        """Test returns Docker disk usage statistics."""
        # Mock disk usage stats
        with patch('app.api.cleanup.CleanupService.get_disk_usage', new_callable=AsyncMock) as mock_stats:
            mock_stats.return_value = {
                "images": {"active": 10, "size": 1024 * 1024 * 1024},
                "containers": {"active": 5, "size": 1024 * 1024 * 512},
                "volumes": {"active": 3, "size": 1024 * 1024 * 256},
                "build_cache": {"size": 1024 * 1024 * 128}
            }

            # Act
            response = await authenticated_client.get("/api/v1/cleanup/stats")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "stats" in data
            assert data["stats"]["images"]["active"] == 10
            assert data["stats"]["containers"]["active"] == 5
            mock_stats.assert_called_once()

    async def test_stats_requires_auth(self, client):
        """Test requires authentication."""
        # Act
        response = await client.get("/api/v1/cleanup/stats")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCleanupSettingsEndpoint:
    """Test suite for GET /api/v1/cleanup/settings endpoint."""

    async def test_get_cleanup_settings(self, authenticated_client, db):
        """Test returns current cleanup settings."""
        # Set some settings
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "cleanup_mode", "moderate")
        await SettingsService.set(db, "cleanup_after_days", "14")
        await SettingsService.set(db, "cleanup_old_images", "true")
        await db.commit()

        # Act
        response = await authenticated_client.get("/api/v1/cleanup/settings")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "settings" in data
        assert data["settings"]["mode"] == "moderate"
        assert data["settings"]["days"] == 14
        assert data["settings"]["enabled"] is True

    async def test_cleanup_settings_requires_auth(self, client):
        """Test requires authentication."""

        # Act
        response = await client.get("/api/v1/cleanup/settings")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
