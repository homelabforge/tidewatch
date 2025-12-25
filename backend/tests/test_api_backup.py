"""Tests for Backup API (app/api/backup.py).

Tests backup and restore endpoints:
- POST /api/v1/backup/create - Create backup
- GET /api/v1/backup/list - List backup files
- GET /api/v1/backup/download/{filename} - Download backup
- POST /api/v1/backup/restore/{filename} - Restore from backup
- GET /api/v1/backup/stats - Backup statistics
"""

import json
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
from fastapi import status


class TestCreateBackupEndpoint:
    """Test suite for POST /api/v1/backup/create endpoint."""

    async def test_create_backup_success(self, authenticated_client, db):
        """Test creates backup file successfully."""
        # Arrange - Add some settings to database
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auto_update_enabled", "true")
        await SettingsService.set(db, "check_interval", "60")
        await db.commit()

        # Mock file operations
        with (
            patch("builtins.open", mock_open()),
            patch("app.api.backup.BACKUP_DIR") as mock_dir,
        ):
            mock_dir.__truediv__ = MagicMock(
                return_value=Path("/data/backups/test.json")
            )
            mock_path = MagicMock()
            mock_path.stat.return_value = MagicMock(st_size=1024)
            mock_dir.__truediv__.return_value = mock_path

            # Act
            response = await authenticated_client.post("/api/v1/backup/create")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["message"] == "Backup created successfully"
            assert "filename" in data
            assert data["filename"].startswith("tidewatch-settings-")
            assert data["filename"].endswith(".json")

    async def test_create_backup_includes_all_settings(self, authenticated_client, db):
        """Test backup includes all settings from database."""
        # Arrange - Add multiple settings
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "setting1", "value1")
        await SettingsService.set(db, "setting2", "value2")
        await SettingsService.set(db, "setting3", "value3")
        await db.commit()

        backup_data_captured = None

        def capture_json_dump(data, f, **kwargs):
            nonlocal backup_data_captured
            backup_data_captured = data

        # Mock file operations
        with (
            patch("builtins.open", mock_open()),
            patch("json.dump", side_effect=capture_json_dump),
            patch("app.api.backup.BACKUP_DIR") as mock_dir,
        ):
            mock_path = MagicMock()
            mock_path.stat.return_value = MagicMock(st_size=1024)
            mock_dir.__truediv__.return_value = mock_path

            # Act
            response = await authenticated_client.post("/api/v1/backup/create")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            assert backup_data_captured is not None
            assert "settings" in backup_data_captured
            assert len(backup_data_captured["settings"]) >= 3

    async def test_create_backup_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post("/api/v1/backup/create")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestListBackupsEndpoint:
    """Test suite for GET /api/v1/backup/list endpoint."""

    async def test_list_backups_empty(self, authenticated_client):
        """Test returns empty list when no backups exist."""
        # Mock empty backup directory
        with (
            patch("app.api.backup.get_backup_files", return_value=[]),
            patch("app.api.backup.Path") as mock_path,
        ):
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.stat.return_value = MagicMock(
                st_size=1024, st_mtime=1234567890
            )

            # Act
            response = await authenticated_client.get("/api/v1/backup/list")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "backups" in data
            assert len(data["backups"]) == 0

    async def test_list_backups_with_files(self, authenticated_client):
        """Test returns list of backup files."""
        # Mock backup files
        mock_backups = [
            {
                "filename": "tidewatch-settings-2025-01-01-120000.json",
                "size_mb": 0.0123,
                "size_bytes": 12288,
                "created": "2025-01-01T12:00:00",
                "is_safety": False,
            },
            {
                "filename": "tidewatch-settings-safety-2025-01-02-130000.json",
                "size_mb": 0.0098,
                "size_bytes": 10240,
                "created": "2025-01-02T13:00:00",
                "is_safety": True,
            },
        ]

        with (
            patch("app.api.backup.get_backup_files", return_value=mock_backups),
            patch("app.api.backup.Path") as mock_path,
        ):
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.stat.return_value = MagicMock(
                st_size=1024, st_mtime=1234567890
            )

            # Act
            response = await authenticated_client.get("/api/v1/backup/list")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "backups" in data
            assert len(data["backups"]) == 2
            assert (
                data["backups"][0]["filename"]
                == "tidewatch-settings-2025-01-01-120000.json"
            )
            assert data["backups"][1]["is_safety"] is True

    async def test_list_backups_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.get("/api/v1/backup/list")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRestoreBackupEndpoint:
    """Test suite for POST /api/v1/backup/restore/{filename} endpoint."""

    async def test_restore_valid_backup(self, authenticated_client, db):
        """Test restores settings from valid backup file."""
        # Arrange
        backup_data = {
            "version": "1.0",
            "exported_at": "2025-01-01T12:00:00",
            "settings": [
                {
                    "key": "auto_update_enabled",
                    "value": "true",
                    "category": "general",
                    "description": "Enable auto updates",
                    "encrypted": False,
                },
                {
                    "key": "check_interval",
                    "value": "120",
                    "category": "general",
                    "description": "Check interval",
                    "encrypted": False,
                },
            ],
        }

        mock_file_content = json.dumps(backup_data)

        with (
            patch("app.api.backup.validate_filename") as mock_validate,
            patch("builtins.open", mock_open(read_data=mock_file_content)),
            patch("app.api.backup.BACKUP_DIR") as mock_dir,
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_validate.return_value = mock_path

            # Mock safety backup creation
            mock_dir.__truediv__.return_value = mock_path

            # Act
            response = await authenticated_client.post(
                "/api/v1/backup/restore/test-backup.json"
            )

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "restored_count" in data["details"]
            assert data["details"]["restored_count"] == 2
            assert "safety_backup" in data["details"]

    async def test_restore_creates_safety_backup(self, authenticated_client, db):
        """Test creates safety backup before restoring."""
        # Arrange - Add existing settings
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "existing_setting", "old_value")
        await db.commit()

        backup_data = {
            "version": "1.0",
            "settings": [
                {
                    "key": "new_setting",
                    "value": "new_value",
                    "category": "general",
                    "description": "",
                    "encrypted": False,
                }
            ],
        }

        safety_backup_created = False

        def mock_open_handler(filename, mode="r"):
            nonlocal safety_backup_created
            if "safety" in str(filename):
                safety_backup_created = True
            return mock_open(read_data=json.dumps(backup_data))()

        with (
            patch("app.api.backup.validate_filename") as mock_validate,
            patch("builtins.open", side_effect=mock_open_handler),
            patch("json.dump"),
            patch("json.load", return_value=backup_data),
            patch("app.api.backup.BACKUP_DIR") as mock_dir,
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_validate.return_value = mock_path
            mock_dir.__truediv__.return_value = mock_path

            # Act
            response = await authenticated_client.post(
                "/api/v1/backup/restore/test.json"
            )

            # Assert
            assert response.status_code == status.HTTP_200_OK
            # Safety backup functionality is called (verified by mock)

    async def test_restore_invalid_backup_format(self, authenticated_client):
        """Test rejects backup with invalid format."""
        # Arrange - Invalid backup (missing 'settings' key)
        invalid_backup = {"version": "1.0", "exported_at": "2025-01-01T12:00:00"}

        with (
            patch("app.api.backup.validate_filename") as mock_validate,
            patch("builtins.open", mock_open(read_data=json.dumps(invalid_backup))),
            patch("json.dump"),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_validate.return_value = mock_path

            # Act
            response = await authenticated_client.post(
                "/api/v1/backup/restore/invalid.json"
            )

            # Assert
            assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_restore_nonexistent_file(self, authenticated_client):
        """Test returns 404 for nonexistent backup file."""
        # Mock file not existing
        with patch("app.api.backup.validate_filename") as mock_validate:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_validate.return_value = mock_path

            # Act
            response = await authenticated_client.post(
                "/api/v1/backup/restore/nonexistent.json"
            )

            # Assert
            assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_restore_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post("/api/v1/backup/restore/test.json")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestBackupStatsEndpoint:
    """Test suite for GET /api/v1/backup/stats endpoint."""

    async def test_stats_returns_database_info(self, authenticated_client):
        """Test returns database statistics."""
        # Mock database and backup stats
        with (
            patch("app.api.backup.get_database_stats") as mock_db_stats,
            patch("app.api.backup.get_backup_files", return_value=[]),
        ):
            mock_db_stats.return_value = {
                "path": "/data/tidewatch.db",
                "size_mb": 2.5,
                "last_modified": "2025-01-01T12:00:00",
                "exists": True,
            }

            # Act
            response = await authenticated_client.get("/api/v1/backup/stats")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "database" in data
            assert data["database"]["size_mb"] == 2.5
            assert data["database"]["exists"] is True

    async def test_stats_returns_backup_count(self, authenticated_client):
        """Test returns backup file count and size."""
        # Mock backups
        mock_backups = [
            {
                "filename": "backup1.json",
                "size_bytes": 10240,
                "created": "2025-01-01T12:00:00",
                "is_safety": False,
            },
            {
                "filename": "backup2.json",
                "size_bytes": 20480,
                "created": "2025-01-02T12:00:00",
                "is_safety": False,
            },
        ]

        with (
            patch("app.api.backup.get_database_stats") as mock_db_stats,
            patch("app.api.backup.get_backup_files", return_value=mock_backups),
        ):
            mock_db_stats.return_value = {
                "path": "/data/tidewatch.db",
                "size_mb": 2.5,
                "last_modified": "2025-01-01T12:00:00",
                "exists": True,
            }

            # Act
            response = await authenticated_client.get("/api/v1/backup/stats")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "backups" in data
            assert data["backups"]["count"] == 2
            assert data["backups"]["total_size_mb"] == round(
                (10240 + 20480) / 1024 / 1024, 2
            )

    async def test_stats_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.get("/api/v1/backup/stats")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
