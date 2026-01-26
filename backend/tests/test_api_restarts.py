"""Tests for Restart API (app/api/restarts.py).

Tests container restart management endpoints:
- GET /api/v1/restarts/{container_id}/state - Get restart state
- POST /api/v1/restarts/{container_id}/manual-restart - Manual restart
- POST /api/v1/restarts/{container_id}/reset - Reset restart state
- POST /api/v1/restarts/{container_id}/pause - Pause restart
- POST /api/v1/restarts/{container_id}/resume - Resume restart
"""

from unittest.mock import patch, AsyncMock
from fastapi import status
from datetime import datetime, timezone


class TestGetRestartStateEndpoint:
    """Test suite for GET /api/v1/restarts/{container_id}/state endpoint."""

    async def test_get_restart_state_existing(
        self, authenticated_client, db, make_container
    ):
        """Test returns restart state for existing container."""
        # Arrange - Create container
        container = make_container(
            name="test-container", image="nginx", current_tag="1.20", policy="manual"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Act
        response = await authenticated_client.get(
            f"/api/v1/restarts/{container.id}/state"
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["container_id"] == container.id
        assert data["container_name"] == "test-container"
        assert "enabled" in data

    async def test_get_restart_state_nonexistent_container(self, authenticated_client):
        """Test returns 404 for nonexistent container."""
        # Act
        response = await authenticated_client.get("/api/v1/restarts/99999/state")

        # Assert
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_restart_state_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.get("/api/v1/restarts/1/state")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestManualRestartEndpoint:
    """Test suite for POST /api/v1/restarts/{container_id}/manual-restart endpoint."""

    async def test_manual_restart_success(
        self, authenticated_client, db, make_container
    ):
        """Test manually triggers container restart."""
        # Arrange - Create container
        container = make_container(
            name="test-container", image="nginx", current_tag="1.20", policy="manual"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Mock RestartService
        with patch(
            "app.routes.restarts.RestartService.execute_restart", new_callable=AsyncMock
        ) as mock_restart:
            mock_restart.return_value = {
                "success": True,
                "message": "Container restarted successfully",
            }

            # Act
            response = await authenticated_client.post(
                f"/api/v1/restarts/{container.id}/manual-restart",
                json={"reason": "Manual testing", "skip_backoff": False},
            )

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "restarted" in data["message"].lower()
            mock_restart.assert_called_once()

    async def test_manual_restart_with_skip_backoff(
        self, authenticated_client, db, make_container
    ):
        """Test manual restart can skip backoff."""
        # Arrange - Create container
        container = make_container(
            name="test-container", image="nginx", current_tag="1.20", policy="manual"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Mock RestartService
        with patch(
            "app.routes.restarts.RestartService.execute_restart", new_callable=AsyncMock
        ) as mock_restart:
            mock_restart.return_value = {
                "success": True,
                "message": "Container restarted successfully",
            }

            # Act
            response = await authenticated_client.post(
                f"/api/v1/restarts/{container.id}/manual-restart",
                json={"reason": "Skip backoff test", "skip_backoff": True},
            )

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True

    async def test_manual_restart_failure(
        self, authenticated_client, db, make_container
    ):
        """Test handles restart failure."""
        # Arrange - Create container
        container = make_container(
            name="test-container", image="nginx", current_tag="1.20", policy="manual"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Mock RestartService failure
        with patch(
            "app.routes.restarts.RestartService.execute_restart", new_callable=AsyncMock
        ) as mock_restart:
            mock_restart.return_value = {
                "success": False,
                "error": "Docker daemon not responding",
            }

            # Act
            response = await authenticated_client.post(
                f"/api/v1/restarts/{container.id}/manual-restart",
                json={"reason": "Test failure", "skip_backoff": False},
            )

            # Assert
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is False
            assert "failed" in data["message"].lower()

    async def test_manual_restart_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post(
            "/api/v1/restarts/1/manual-restart",
            json={"reason": "test", "skip_backoff": False},
        )

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestResetRestartStateEndpoint:
    """Test suite for POST /api/v1/restarts/{container_id}/reset endpoint."""

    async def test_reset_restart_state(self, authenticated_client, db, make_container):
        """Test resets restart state clearing failures."""
        # Arrange - Create container and restart state
        from app.models.restart_state import ContainerRestartState

        container = make_container(
            name="test-container",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            policy="manual",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        restart_state = ContainerRestartState(
            container_id=container.id,
            container_name=container.name,
            consecutive_failures=5,
            current_backoff_seconds=120.0,
            max_retries_reached=True,
        )
        db.add(restart_state)
        await db.commit()

        # Act
        response = await authenticated_client.post(
            f"/api/v1/restarts/{container.id}/reset", json={"reason": "Manual reset"}
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "reset" in data["message"].lower()
        assert data["state"]["consecutive_failures"] == 0
        assert data["state"]["current_backoff_seconds"] == 0.0
        assert data["state"]["max_retries_reached"] is False

    async def test_reset_restart_state_no_state(
        self, authenticated_client, db, make_container
    ):
        """Test returns 404 if restart state doesn't exist."""
        # Arrange - Create container without restart state
        container = make_container(
            name="test-container", image="nginx", current_tag="1.20", policy="manual"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Act
        response = await authenticated_client.post(
            f"/api/v1/restarts/{container.id}/reset", json={"reason": "Test"}
        )

        # Assert
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_reset_restart_state_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post(
            "/api/v1/restarts/1/reset", json={"reason": "test"}
        )

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestPauseRestartEndpoint:
    """Test suite for POST /api/v1/restarts/{container_id}/pause endpoint."""

    async def test_pause_restart(self, authenticated_client, db, make_container):
        """Test pauses auto-restart for duration."""
        # Arrange - Create container and restart state
        from app.models.restart_state import ContainerRestartState

        container = make_container(
            name="test-container",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            policy="manual",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        restart_state = ContainerRestartState(
            container_id=container.id, container_name=container.name, enabled=True
        )
        db.add(restart_state)
        await db.commit()

        # Act
        response = await authenticated_client.post(
            f"/api/v1/restarts/{container.id}/pause",
            json={"duration_seconds": 3600, "reason": "Maintenance"},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "paused" in data["message"].lower()
        assert data["state"]["pause_reason"] == "Maintenance"

    async def test_pause_restart_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post(
            "/api/v1/restarts/1/pause",
            json={"duration_seconds": 3600, "reason": "test"},
        )

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestResumeRestartEndpoint:
    """Test suite for POST /api/v1/restarts/{container_id}/resume endpoint."""

    async def test_resume_restart(self, authenticated_client, db, make_container):
        """Test resumes auto-restart after pause."""
        # Arrange - Create container and paused restart state
        from app.models.restart_state import ContainerRestartState
        from datetime import timedelta

        container = make_container(
            name="test-container",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            policy="manual",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        restart_state = ContainerRestartState(
            container_id=container.id,
            container_name=container.name,
            enabled=True,
            paused_until=datetime.now(timezone.utc) + timedelta(hours=1),
            pause_reason="Maintenance",
        )
        db.add(restart_state)
        await db.commit()

        # Act
        response = await authenticated_client.post(
            f"/api/v1/restarts/{container.id}/resume"
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "resumed" in data["message"].lower()
        assert data["state"]["paused_until"] is None
        assert data["state"]["pause_reason"] is None

    async def test_resume_restart_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.post("/api/v1/restarts/1/resume")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRestartStatsEndpoint:
    """Test suite for GET /api/v1/restarts/stats endpoint."""

    async def test_get_restart_stats(self, authenticated_client, db, make_container):
        """Test returns aggregate restart statistics."""
        # Arrange - Create some restart states
        from app.models.restart_state import ContainerRestartState

        for i in range(3):
            container = make_container(
                name=f"container-{i}",
                image="nginx",
                current_tag="1.20",
                registry="docker.io",
                policy="manual",
            )
            db.add(container)
            await db.commit()
            await db.refresh(container)

            restart_state = ContainerRestartState(
                container_id=container.id,
                container_name=container.name,
                consecutive_failures=i,
            )
            db.add(restart_state)

        await db.commit()

        # Act
        response = await authenticated_client.get("/api/v1/restarts/stats")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "total_containers" in data
        assert data["total_containers"] == 3
        assert "containers_with_failures" in data

    async def test_restart_stats_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.get("/api/v1/restarts/stats")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
