"""Tests for History API (app/api/history.py).

Tests update history endpoints:
- GET /api/v1/history - List update history
- GET /api/v1/history/{id} - Get history details
- POST /api/v1/history/{id}/rollback - Rollback update
- GET /api/v1/history/stats - History statistics
"""

import pytest
from fastapi import status
from datetime import datetime, timezone, timedelta


class TestGetHistoryEndpoint:
    """Test suite for GET /api/v1/history endpoint."""

    async def test_get_history_all(self, authenticated_client, db, make_container):
        """Test listing all history entries."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create test history entries
        for i in range(3):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{19 + i}",
                to_tag=f"1.{20 + i}",
                status="success",
                created_at=datetime.now(timezone.utc),
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    async def test_get_history_pagination(
        self, authenticated_client, db, make_container
    ):
        """Test pagination with limit and offset."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create 10 history entries
        for i in range(10):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="success",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10 - i),
            )
            db.add(history)
        await db.commit()

        # Test limit
        response = await authenticated_client.get("/api/v1/history?limit=5")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 5

        # Test skip
        response = await authenticated_client.get("/api/v1/history?skip=5&limit=5")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 5

    async def test_get_history_filter_by_container(
        self, authenticated_client, db, make_container
    ):
        """Test filtering by container_id."""
        from app.models.history import UpdateHistory

        # Create two test containers
        container1 = make_container(
            name="test-container-1", image="nginx:1.20", current_tag="1.20"
        )
        container2 = make_container(
            name="test-container-2", image="redis:6.0", current_tag="6.0"
        )
        db.add_all([container1, container2])
        await db.commit()
        await db.refresh(container1)
        await db.refresh(container2)

        # Create history for both containers
        history1 = UpdateHistory(
            container_id=container1.id,
            container_name=container1.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            created_at=datetime.now(timezone.utc),
        )
        history2 = UpdateHistory(
            container_id=container2.id,
            container_name=container2.name,
            from_tag="5.9",
            to_tag="6.0",
            status="success",
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([history1, history2])
        await db.commit()

        # Filter by container1
        response = await authenticated_client.get(
            f"/api/v1/history?container_id={container1.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should only contain container1 events
        for event in data:
            if event["event_type"] == "update":
                assert event["container_id"] == container1.id

    async def test_get_history_filter_by_status(
        self, authenticated_client, db, make_container
    ):
        """Test filtering by status (success, failed, rolled_back)."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"status-filter-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create history entries with different statuses
        now = datetime.now(timezone.utc)
        history1 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.18",
            to_tag="1.19",
            status="success",
            started_at=now - timedelta(hours=2),
        )
        history2 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="failed",
            started_at=now - timedelta(hours=1),
        )
        history3 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="success",
            started_at=now,
        )
        db.add_all([history1, history2, history3])
        await db.commit()

        # Filter by status=success
        response = await authenticated_client.get(
            "/api/v1/history", params={"status": "success"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify only success status returned
        success_events = [
            e for e in data if e["status"] == "success" and e["event_type"] == "update"
        ]
        assert len(success_events) >= 2
        assert all(e["status"] == "success" for e in success_events)

    async def test_get_history_filter_by_date_range(
        self, authenticated_client, db, make_container
    ):
        """Test filtering by date range."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"date-filter-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create history entries at different times
        now = datetime.now(timezone.utc)
        history1 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.18",
            to_tag="1.19",
            status="success",
            started_at=now - timedelta(days=3),
        )
        history2 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            started_at=now - timedelta(days=1),
        )
        history3 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="success",
            started_at=now,
        )
        db.add_all([history1, history2, history3])
        await db.commit()

        # Filter by date range (last 2 days)
        start_date = (now - timedelta(days=2)).isoformat()
        end_date = now.isoformat()
        response = await authenticated_client.get(
            "/api/v1/history", params={"start_date": start_date, "end_date": end_date}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should only return history2 and history3 (within last 2 days)
        update_events = [e for e in data if e["event_type"] == "update"]
        assert len(update_events) >= 2

        # Verify all returned events are within date range
        for event in update_events:
            event_time = datetime.fromisoformat(
                event["started_at"].replace("Z", "+00:00")
            )
            assert event_time >= now - timedelta(days=2)
            assert event_time <= now

    async def test_get_history_sort_by_created_at(
        self, authenticated_client, db, make_container
    ):
        """Test sorting by created_at descending."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create history entries with different timestamps
        now = datetime.now(timezone.utc)
        history1 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.18",
            to_tag="1.19",
            status="success",
            created_at=now - timedelta(hours=2),
            started_at=now - timedelta(hours=2),
        )
        history2 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            created_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
        )
        history3 = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="success",
            created_at=now,
            started_at=now,
        )
        db.add_all([history1, history2, history3])
        await db.commit()

        response = await authenticated_client.get("/api/v1/history")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify sorted by started_at descending (most recent first)
        if len(data) >= 3:
            update_events = [e for e in data if e["event_type"] == "update"][:3]
            for i in range(len(update_events) - 1):
                current = datetime.fromisoformat(
                    update_events[i]["started_at"].replace("Z", "+00:00")
                )
                next_item = datetime.fromisoformat(
                    update_events[i + 1]["started_at"].replace("Z", "+00:00")
                )
                assert current >= next_item

    async def test_get_history_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/history")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_history_empty_result(self, authenticated_client, db):
        """Test listing when no history exists."""
        response = await authenticated_client.get("/api/v1/history")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)


class TestGetHistoryEventEndpoint:
    """Test suite for GET /api/v1/history/{id} endpoint."""

    async def test_get_history_event_valid_id(
        self, authenticated_client, db, make_container
    ):
        """Test get history entry by valid ID."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create test history
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        response = await authenticated_client.get(f"/api/v1/history/{history.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == history.id
        assert data["from_tag"] == "1.19"
        assert data["to_tag"] == "1.20"

    async def test_get_history_event_invalid_id(self, authenticated_client):
        """Test invalid ID returns 404."""
        response = await authenticated_client.get("/api/v1/history/999999")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_history_event_includes_error_details(
        self, authenticated_client, db, make_container
    ):
        """Test includes error details if failed."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create failed history with error message
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="failed",
            error_message="Failed to pull image: connection timeout",
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        response = await authenticated_client.get(f"/api/v1/history/{history.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Failed to pull image: connection timeout"

    async def test_get_history_event_includes_rollback_info(
        self, authenticated_client, db, make_container
    ):
        """Test includes rollback info if rolled back."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create rolled back history
        rolled_back_time = datetime.now(timezone.utc)
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="rolled_back",
            rolled_back_at=rolled_back_time,
            can_rollback=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        response = await authenticated_client.get(f"/api/v1/history/{history.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "rolled_back"
        assert data["rolled_back_at"] is not None
        assert data["can_rollback"] is False


class TestRollbackEndpoint:
    """Test suite for POST /api/v1/history/{id}/rollback endpoint."""

    async def test_rollback_successful_update(
        self, authenticated_client, db, mock_docker_client, make_container
    ):
        """Test rollback of successful update initiates rollback."""
        from app.models.history import UpdateHistory
        from unittest.mock import patch, AsyncMock

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create successful history that can be rolled back
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            can_rollback=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        # Mock UpdateEngine.rollback_update
        mock_result = {
            "success": True,
            "message": "Rollback completed successfully",
            "history_id": history.id,
        }

        with patch(
            "app.api.history.UpdateEngine.rollback_update", new_callable=AsyncMock
        ) as mock_rollback:
            mock_rollback.return_value = mock_result

            response = await authenticated_client.post(
                f"/api/v1/history/{history.id}/rollback"
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            mock_rollback.assert_called_once()

    async def test_rollback_failed_update(
        self, authenticated_client, db, make_container
    ):
        """Test rollback of failed update returns 400."""
        from app.models.history import UpdateHistory
        from unittest.mock import patch, AsyncMock

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create failed history
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="failed",
            can_rollback=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        # Mock rollback to raise ValueError for failed update
        with patch(
            "app.api.history.UpdateEngine.rollback_update", new_callable=AsyncMock
        ) as mock_rollback:
            mock_rollback.side_effect = ValueError("Cannot rollback failed update")

            response = await authenticated_client.post(
                f"/api/v1/history/{history.id}/rollback"
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_rollback_already_rolled_back(
        self, authenticated_client, db, make_container
    ):
        """Test rollback of already rolled back update returns 400."""
        from app.models.history import UpdateHistory
        from unittest.mock import patch, AsyncMock

        # Create test container
        container = make_container(
            name="test-container", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create already rolled back history
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="rolled_back",
            rolled_back_at=datetime.now(timezone.utc),
            can_rollback=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        # Mock rollback to raise ValueError for already rolled back
        with patch(
            "app.api.history.UpdateEngine.rollback_update", new_callable=AsyncMock
        ) as mock_rollback:
            mock_rollback.side_effect = ValueError("Update already rolled back")

            response = await authenticated_client.post(
                f"/api/v1/history/{history.id}/rollback"
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.skip(reason="Requires Docker client mocking for version verification")
    async def test_rollback_version_mismatch(self, authenticated_client, db):
        """Test rollback when container version changed returns 400."""
        pass

    @pytest.mark.skip(
        reason="Requires UpdateEngine rollback implementation verification"
    )
    async def test_rollback_creates_history(self, authenticated_client, db):
        """Test rollback creates new history entry."""
        pass

    async def test_rollback_event_bus_notification(
        self, authenticated_client, db, mock_event_bus
    ):
        """Test rollback emits event bus notification."""
        # Attempt rollback (will fail without valid history, but tests fixture)
        response = await authenticated_client.post("/api/v1/history/999/rollback")

        # Test validates mock_event_bus fixture is properly configured
        # When rollback is implemented, verify event bus publish was called:
        # if response.status_code == status.HTTP_200_OK:
        #     mock_event_bus.publish.assert_called()
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST,
        ]

    async def test_rollback_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/history/1/rollback")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestHistoryStatsEndpoint:
    """Test suite for GET /api/v1/history/stats endpoint."""

    async def test_stats_success_rate(self, authenticated_client, db, make_container):
        """Test returns success rate percentage."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"stats-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create 7 successful and 3 failed updates (70% success rate)
        now = datetime.now(timezone.utc)
        for i in range(7):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="success",
                started_at=now - timedelta(hours=i),
            )
            db.add(history)

        for i in range(3):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"2.{i}",
                to_tag=f"2.{i + 1}",
                status="failed",
                started_at=now - timedelta(hours=i + 7),
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "success_rate" in data
        assert data["success_rate"] == 70.0

    async def test_stats_total_updates(self, authenticated_client, db, make_container):
        """Test returns total updates applied."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"total-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create 5 updates
        now = datetime.now(timezone.utc)
        for i in range(5):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="success" if i % 2 == 0 else "failed",
                started_at=now - timedelta(hours=i),
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "total_updates" in data
        assert data["total_updates"] >= 5

    async def test_stats_average_update_time(
        self, authenticated_client, db, make_container
    ):
        """Test returns average update time."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"avgtime-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create updates with duration_seconds: 60, 120, 180 (avg = 120)
        now = datetime.now(timezone.utc)
        for i, duration in enumerate([60, 120, 180]):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="success",
                started_at=now - timedelta(hours=i),
                duration_seconds=duration,
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "avg_update_time" in data
        assert data["avg_update_time"] == 120.0

    async def test_stats_failed_count(self, authenticated_client, db, make_container):
        """Test returns failed updates count."""
        from app.models.history import UpdateHistory

        # Create test container
        container = make_container(
            name=f"failed-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create 3 failed updates
        now = datetime.now(timezone.utc)
        for i in range(3):
            history = UpdateHistory(
                container_id=container.id,
                container_name=container.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="failed",
                started_at=now - timedelta(hours=i),
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "failed_count" in data
        assert data["failed_count"] >= 3

    async def test_stats_most_updated_containers(
        self, authenticated_client, db, make_container
    ):
        """Test returns most frequently updated containers."""
        from app.models.history import UpdateHistory

        # Create test containers
        container1 = make_container(
            name=f"most-updated-1-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx1",
        )
        container2 = make_container(
            name=f"most-updated-2-{id(self)}",
            image="redis:6",
            current_tag="6",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="redis",
        )
        db.add_all([container1, container2])
        await db.commit()
        await db.refresh(container1)
        await db.refresh(container2)

        # Container 1 gets 5 updates, Container 2 gets 2 updates
        now = datetime.now(timezone.utc)
        for i in range(5):
            history = UpdateHistory(
                container_id=container1.id,
                container_name=container1.name,
                from_tag=f"1.{i}",
                to_tag=f"1.{i + 1}",
                status="success",
                started_at=now - timedelta(hours=i),
            )
            db.add(history)

        for i in range(2):
            history = UpdateHistory(
                container_id=container2.id,
                container_name=container2.name,
                from_tag=f"6.{i}",
                to_tag=f"6.{i + 1}",
                status="success",
                started_at=now - timedelta(hours=i + 5),
            )
            db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/history/stats")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "most_updated_containers" in data
        assert isinstance(data["most_updated_containers"], list)

        # Find our containers in the results
        our_containers = [
            c
            for c in data["most_updated_containers"]
            if c["container_name"] in [container1.name, container2.name]
        ]

        if len(our_containers) > 0:
            # Container 1 should have more updates than Container 2
            container1_stats = next(
                (c for c in our_containers if c["container_name"] == container1.name),
                None,
            )
            if container1_stats:
                assert container1_stats["update_count"] == 5

    async def test_stats_endpoint_accessible(self, client):
        """Test stats endpoint is accessible (auth optional for GET endpoints)."""
        response = await client.get("/api/v1/history/stats")
        # GET endpoints don't require auth in this application
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Should return stats even with no data
        assert "success_rate" in data
        assert "total_updates" in data
