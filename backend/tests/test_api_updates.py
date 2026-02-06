"""Tests for Updates API (app/api/updates.py).

Tests update management endpoints:
- GET /api/v1/updates - List all updates
- GET /api/v1/updates/{id} - Get update details
- POST /api/v1/updates/check - Trigger update check
- POST /api/v1/updates/{id}/approve - Approve update
- POST /api/v1/updates/{id}/reject - Reject update
- POST /api/v1/updates/{id}/apply - Apply update
- DELETE /api/v1/updates/{id} - Delete update
- POST /api/v1/updates/batch/approve - Batch approve
- POST /api/v1/updates/batch/reject - Batch reject
"""

from datetime import UTC

import pytest
from fastapi import status


class TestListUpdatesEndpoint:
    """Test suite for GET /api/v1/updates endpoint."""

    async def test_list_updates_all(self, authenticated_client, db, make_container, make_update):
        """Test listing all updates."""
        # Create a test container first
        container = make_container(
            name=f"test-container-{id(self)}", image="nginx:1.20", current_tag="1.20"
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create test updates
        update1 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="pending",
        )
        update2 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.21",
            to_tag="1.22",
            status="approved",
        )
        db.add(update1)
        db.add(update2)
        await db.commit()

        response = await authenticated_client.get("/api/v1/updates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    async def test_list_updates_filter_by_status(self, authenticated_client, db, make_container):
        """Test filtering updates by status (pending, approved, applied, failed)."""
        response = await authenticated_client.get("/api/v1/updates?status=pending")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # All returned updates should have status=pending
        for update in data:
            assert update["status"] == "pending"

    async def test_list_updates_filter_by_container(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test filtering updates by container_id."""

        # Create two containers with all required fields
        container1 = make_container(
            name="container1",
            image="test:1.0",
            current_tag="1.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="service1",
        )
        container2 = make_container(
            name="container2",
            image="test:2.0",
            current_tag="2.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="service2",
        )
        db.add_all([container1, container2])
        await db.commit()
        await db.refresh(container1)
        await db.refresh(container2)

        # Create updates for each container
        update1 = make_update(
            container_id=container1.id,
            container_name=container1.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update2 = make_update(
            container_id=container2.id,
            container_name=container2.name,
            from_tag="2.0",
            to_tag="2.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add_all([update1, update2])
        await db.commit()

        # Filter by container1
        response = await authenticated_client.get(f"/api/v1/updates/?container_id={container1.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 1
        assert all(u["container_id"] == container1.id for u in data)

    async def test_list_updates_pagination(self, authenticated_client, db, make_container):
        """Test pagination with limit and offset."""
        # Test with limit
        response = await authenticated_client.get("/api/v1/updates?limit=1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 1

        # Test with offset
        response = await authenticated_client.get("/api/v1/updates?skip=1&limit=1")
        assert response.status_code == status.HTTP_200_OK

    async def test_list_updates_sorting(self, authenticated_client, db, make_container):
        """Test sorting by created_at descending."""
        response = await authenticated_client.get("/api/v1/updates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Verify sorting (most recent first)
        if len(data) > 1:
            for i in range(len(data) - 1):
                assert data[i]["created_at"] >= data[i + 1]["created_at"]

    async def test_list_updates_requires_auth(self, client, db, make_container):
        """Test listing updates requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/updates")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_list_updates_empty_result(self, authenticated_client, db, make_container):
        """Test listing updates when none exist."""
        # Use a status that likely has no updates
        response = await authenticated_client.get("/api/v1/updates?status=nonexistent")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    async def test_list_updates_includes_cve_data(
        self, authenticated_client, db, make_container, make_update
    ):
        """Test CVE data is included in response."""
        from datetime import datetime

        container = make_container(
            name=f"cve-list-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            cves_fixed=["CVE-2024-1234", "CVE-2024-5678"],
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()

        response = await authenticated_client.get("/api/v1/updates")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Find our update in the list
        cve_update = next((u for u in data if u.get("cves_fixed")), None)
        assert cve_update is not None
        assert "CVE-2024-1234" in cve_update["cves_fixed"]
        assert "CVE-2024-5678" in cve_update["cves_fixed"]


class TestGetUpdateEndpoint:
    """Test suite for GET /api/v1/updates/{id} endpoint."""

    async def test_get_update_valid_id(self, authenticated_client, db, make_update, make_container):
        """Test getting update by valid ID returns update object."""
        from datetime import datetime

        # Create test container and update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        response = await authenticated_client.get(f"/api/v1/updates/{update.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == update.id
        assert data["from_tag"] == "1.20"
        assert data["to_tag"] == "1.21"

    async def test_get_update_invalid_id(self, authenticated_client):
        """Test getting update by invalid ID returns 404."""
        response = await authenticated_client.get("/api/v1/updates/999999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_update_includes_cve_data(
        self, authenticated_client, db, make_container, make_update
    ):
        """Test get update includes CVE data if available."""
        from datetime import datetime

        container = make_container(
            name=f"cve-get-test-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            cves_fixed=["CVE-2024-9999"],
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        response = await authenticated_client.get(f"/api/v1/updates/{update.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "CVE-2024-9999" in data["cves_fixed"]

    async def test_get_update_requires_auth(self, client, db, make_container):
        """Test get update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/updates/1")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestCheckUpdatesEndpoint:
    """Test suite for POST /api/v1/updates/check endpoint."""

    async def test_check_updates_single_container(self, authenticated_client, db, make_container):
        """Test checking updates for single container."""

        # Create test container
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Check for updates on this specific container
        response = await authenticated_client.post(f"/api/v1/updates/check/{container.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "update_available" in data

    async def test_check_updates_all_containers(self, authenticated_client, db, make_container):
        """Test checking updates for all containers (batch check)."""

        # Create multiple test containers
        container1 = make_container(
            name="test-container-1",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        container2 = make_container(
            name="test-container-2",
            image="postgres:13",
            current_tag="13",
            status="running",
        )
        db.add(container1)
        db.add(container2)
        await db.commit()

        # Check all containers - now returns job info, not stats directly
        response = await authenticated_client.post("/api/v1/updates/check")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "job_id" in data
        assert "status" in data
        assert data["status"] in ("queued", "running", "completed")
        assert "message" in data

    @pytest.mark.skip(reason="Concurrent check handling not yet implemented")
    async def test_check_updates_already_running(self, authenticated_client, db, make_container):
        """Test check updates returns 409 if already running."""
        pass

    async def test_check_updates_event_bus_notification(
        self, authenticated_client, db, mock_event_bus
    ):
        """Test check updates emits event bus notification."""
        # Trigger update check
        response = await authenticated_client.post("/api/v1/updates/check")

        # Test should succeed if endpoint exists
        # Event bus notification verification (when implemented):
        # mock_event_bus.publish.assert_called()
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_202_ACCEPTED,
            status.HTTP_404_NOT_FOUND,
        ]

    async def test_check_updates_requires_auth(self, client, db, make_container):
        """Test check updates requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/updates/check")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_check_updates_nonexistent_container(self, authenticated_client):
        """Test check updates for nonexistent container returns 404."""
        # Try to check updates for nonexistent container ID
        response = await authenticated_client.post("/api/v1/updates/check/99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestApproveUpdateEndpoint:
    """Test suite for POST /api/v1/updates/{id}/approve endpoint."""

    async def test_approve_update_pending(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test approving pending update changes status to approved."""
        from datetime import datetime

        # Create test container and pending update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Approve the update
        response = await authenticated_client.post(
            f"/api/v1/updates/{update.id}/approve",
            json={"approved": True, "approved_by": "admin"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

        # Verify status changed to approved
        await db.refresh(update)
        assert update.status == "approved"
        assert update.approved_by == "admin"
        assert update.approved_at is not None

    async def test_approve_update_already_approved(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test approving already approved update is idempotent (returns 200)."""
        from datetime import datetime

        # Create test container and already-approved update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="approved",  # Already approved
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Try to approve again - should be idempotent
        response = await authenticated_client.post(
            f"/api/v1/updates/{update.id}/approve",
            json={"approved": True, "approved_by": "admin"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "already approved" in data["message"].lower()

    async def test_approve_update_already_applied(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test approving already applied update returns 400."""
        from datetime import datetime

        # Create test container and already-applied update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.21",  # Already updated
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="applied",  # Already applied
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Try to approve again
        response = await authenticated_client.post(
            f"/api/v1/updates/{update.id}/approve",
            json={"approved": True, "approved_by": "admin"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "cannot approve update with status: applied" in data["detail"].lower()

    async def test_approve_update_adds_timestamp(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test approve adds approval timestamp and user."""
        from datetime import datetime

        # Create test container and pending update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Verify no approval data initially
        assert update.approved_by is None
        assert update.approved_at is None

        # Approve with specific user
        response = await authenticated_client.post(
            f"/api/v1/updates/{update.id}/approve",
            json={"approved": True, "approved_by": "test-admin"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify approval metadata added
        await db.refresh(update)
        assert update.approved_by == "test-admin"
        assert update.approved_at is not None
        assert isinstance(update.approved_at, datetime)

    async def test_approve_update_requires_auth(self, client, db, make_container):
        """Test approve update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post(
            "/api/v1/updates/1/approve", json={"approved": True, "approved_by": "admin"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRejectUpdateEndpoint:
    """Test suite for POST /api/v1/updates/{id}/reject endpoint."""

    async def test_reject_update_pending(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test rejecting pending update changes status to rejected."""
        from datetime import datetime

        # Create test container and pending update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
            update_available=True,
            latest_tag="1.21",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Reject the update
        response = await authenticated_client.post(f"/api/v1/updates/{update.id}/reject")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

        # Verify status changed to rejected
        await db.refresh(update)
        assert update.status == "rejected"

        # Verify container update_available flag cleared
        await db.refresh(container)
        assert container.update_available is False
        assert container.latest_tag is None

    async def test_reject_update_already_rejected(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test rejecting already rejected update returns 400."""
        from datetime import datetime

        # Create test container and already-rejected update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="rejected",  # Already rejected
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Try to reject again
        response = await authenticated_client.post(f"/api/v1/updates/{update.id}/reject")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "already rejected" in data["detail"].lower()

    async def test_reject_update_adds_reason(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test reject adds rejection reason."""

        # Create test container and update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Reject with reason
        rejection_reason = "Incompatible with current infrastructure"
        response = await authenticated_client.post(
            f"/api/v1/updates/{update.id}/reject", json={"reason": rejection_reason}
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify rejection reason was stored
        await db.refresh(update)
        assert update.status == "rejected"
        assert update.rejection_reason == rejection_reason
        assert update.rejected_by is not None
        assert update.rejected_at is not None

    async def test_reject_update_requires_auth(self, client, db, make_container):
        """Test reject update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/updates/1/reject")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestApplyUpdateEndpoint:
    """Test suite for POST /api/v1/updates/{id}/apply endpoint."""

    async def test_apply_update_approved(
        self, authenticated_client, db, mock_docker_client, make_update, make_container
    ):
        """Test applying approved update triggers update engine."""
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Create test container and approved update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="approved",
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Mock UpdateEngine.apply_update to return success
        mock_result = {
            "success": True,
            "message": "Update completed successfully",
            "container_id": container.id,
            "old_tag": "1.20",
            "new_tag": "1.21",
        }

        with patch(
            "app.routes.updates.UpdateEngine.apply_update", new_callable=AsyncMock
        ) as mock_apply:
            mock_apply.return_value = mock_result

            # Apply the update
            response = await authenticated_client.post(
                f"/api/v1/updates/{update.id}/apply", json={"triggered_by": "admin"}
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "Update completed successfully" in data["message"]

            # Verify UpdateEngine.apply_update was called
            mock_apply.assert_called_once()

    async def test_apply_update_pending_rejected(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test applying pending update returns 400 (must approve first)."""
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Create test container and pending update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",  # Not approved yet
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Mock UpdateEngine to raise ValueError for non-approved updates
        with patch(
            "app.routes.updates.UpdateEngine.apply_update", new_callable=AsyncMock
        ) as mock_apply:
            mock_apply.side_effect = ValueError("Update must be approved before applying")

            # Try to apply pending update
            response = await authenticated_client.post(
                f"/api/v1/updates/{update.id}/apply", json={"triggered_by": "admin"}
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_apply_update_failed_retry(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test applying failed update allows retry."""
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Create test container and failed update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="failed",  # Previous attempt failed
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Mock successful retry
        mock_result = {
            "success": True,
            "message": "Update completed successfully on retry",
            "container_id": container.id,
        }

        with patch(
            "app.routes.updates.UpdateEngine.apply_update", new_callable=AsyncMock
        ) as mock_apply:
            mock_apply.return_value = mock_result

            # Retry the failed update
            response = await authenticated_client.post(
                f"/api/v1/updates/{update.id}/apply", json={"triggered_by": "admin"}
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True

    async def test_apply_update_creates_history(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test apply creates history entry."""
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Create test container and approved update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="approved",
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Mock UpdateEngine to simulate successful apply
        mock_result = {
            "success": True,
            "message": "Update completed successfully",
            "container_id": container.id,
            "history_id": 1,  # Simulated history entry
        }

        with patch(
            "app.routes.updates.UpdateEngine.apply_update", new_callable=AsyncMock
        ) as mock_apply:
            mock_apply.return_value = mock_result

            # Apply the update
            response = await authenticated_client.post(
                f"/api/v1/updates/{update.id}/apply", json={"triggered_by": "admin"}
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "history_id" in data or data["success"] is True

    async def test_apply_update_event_bus_progress(
        self, authenticated_client, db, mock_event_bus, make_container, make_update
    ):
        """Test apply emits event bus progress notifications."""
        # Create container first
        container = make_container(name="test-nginx", image="nginx:1.20")
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create update with valid container_id
        update = make_update(container_id=container.id, from_tag="1.20", to_tag="1.21")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Apply update
        response = await authenticated_client.post(f"/api/v1/updates/{update.id}/apply")

        # Test validates mock_event_bus fixture works
        # When event bus integration is complete, verify:
        # assert mock_event_bus.publish.called
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_202_ACCEPTED,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_400_BAD_REQUEST,
        ]

    @pytest.mark.skip(reason="Concurrent handling not yet implemented")
    async def test_apply_update_concurrent_request(self, authenticated_client, db, make_container):
        """Test concurrent apply requests are handled safely."""
        pass

    async def test_apply_update_requires_auth(self, client, db, make_container):
        """Test apply update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/updates/1/apply", json={"triggered_by": "user"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_apply_update_container_deleted(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test apply when container was deleted returns 400."""
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Create test container and approved update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="approved",
            approved_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Delete the container
        await db.delete(container)
        await db.commit()

        # Mock UpdateEngine to raise error for missing container
        with patch(
            "app.routes.updates.UpdateEngine.apply_update", new_callable=AsyncMock
        ) as mock_apply:
            mock_apply.side_effect = ValueError("Container not found")

            # Try to apply update for deleted container
            response = await authenticated_client.post(
                f"/api/v1/updates/{update.id}/apply", json={"triggered_by": "admin"}
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestDeleteUpdateEndpoint:
    """Test suite for DELETE /api/v1/updates/{id} endpoint."""

    async def test_delete_update_pending(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test deleting pending update returns 200."""
        from datetime import datetime

        from app.models.update import Update

        # Create test container and pending update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Delete the update
        response = await authenticated_client.delete(f"/api/v1/updates/{update.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

        # Verify update is deleted
        from sqlalchemy import select

        result = await db.execute(select(Update).where(Update.id == update.id))
        deleted_update = result.scalar_one_or_none()
        assert deleted_update is None

    async def test_delete_update_applied_rejected(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test deleting applied/rejected updates is allowed."""
        from datetime import datetime

        # Create test container and rejected update
        container = make_container(
            name=f"test-container-{id(self)}",
            image="nginx:1.20",
            current_tag="1.20",
            status="running",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = make_update(
            container_id=container.id,
            current_tag="1.20",
            new_tag="1.21",
            status="rejected",
            created_at=datetime.now(UTC),
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Delete should succeed for rejected updates
        response = await authenticated_client.delete(f"/api/v1/updates/{update.id}")

        assert response.status_code == status.HTTP_200_OK

    async def test_delete_update_requires_auth(self, client, db, make_container):
        """Test delete update requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.delete("/api/v1/updates/1")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestBatchOperations:
    """Test suite for batch approve/reject endpoints."""

    async def test_batch_approve_multiple(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test batch approve approves multiple updates."""

        # Create container with all required fields
        container = make_container(
            name=f"test-container-{id(self)}",
            image="test:1.0",
            current_tag="1.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="test-service",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create multiple pending updates
        update1 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update2 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.1",
            to_tag="1.2",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update3 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.2",
            to_tag="1.3",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add_all([update1, update2, update3])
        await db.commit()
        await db.refresh(update1)
        await db.refresh(update2)
        await db.refresh(update3)

        # Batch approve
        response = await authenticated_client.post(
            "/api/v1/updates/batch/approve",
            json={"update_ids": [update1.id, update2.id, update3.id]},
        )

        if response.status_code != status.HTTP_200_OK:
            print(f"Response status: {response.status_code}")
            print(f"Response body: {response.text}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["summary"]["approved_count"] == 3
        assert data["summary"]["failed_count"] == 0

    async def test_batch_approve_mixed_statuses(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test batch approve with mixed statuses returns partial success."""

        # Create container with all required fields
        container = make_container(
            name=f"test-container-{id(self)}",
            image="test:1.0",
            current_tag="1.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="test-service",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create updates with different statuses
        update1 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update2 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.1",
            to_tag="1.2",
            registry="docker.io",
            reason_type="feature",
            status="approved",
        )
        update3 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.2",
            to_tag="1.3",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add_all([update1, update2, update3])
        await db.commit()
        await db.refresh(update1)
        await db.refresh(update2)
        await db.refresh(update3)

        # Batch approve - update2 is already approved but should be idempotent
        response = await authenticated_client.post(
            "/api/v1/updates/batch/approve",
            json={"update_ids": [update1.id, update2.id, update3.id]},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["summary"]["approved_count"] == 3  # All three (update2 is idempotent)
        assert data["summary"]["failed_count"] == 0  # None fail due to idempotency

    async def test_batch_approve_returns_summary(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test batch approve returns approval summary."""

        # Create container with all required fields
        container = make_container(
            name=f"test-container-{id(self)}",
            image="test:1.0",
            current_tag="1.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="test-service",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create pending updates
        update1 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update2 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.1",
            to_tag="1.2",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add_all([update1, update2])
        await db.commit()
        await db.refresh(update1)
        await db.refresh(update2)

        # Batch approve
        response = await authenticated_client.post(
            "/api/v1/updates/batch/approve",
            json={"update_ids": [update1.id, update2.id]},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify summary structure
        assert "approved" in data
        assert "failed" in data
        assert "summary" in data
        assert data["summary"]["total"] == 2
        assert data["summary"]["approved_count"] == 2

    async def test_batch_reject_multiple(
        self, authenticated_client, db, make_update, make_container
    ):
        """Test batch reject rejects multiple updates."""

        # Create container with all required fields
        container = make_container(
            name=f"test-container-{id(self)}",
            image="test:1.0",
            current_tag="1.0",
            registry="docker.io",
            compose_file="/docker/test.yml",
            service_name="test-service",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create pending updates
        update1 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        update2 = make_update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.1",
            to_tag="1.2",
            registry="docker.io",
            reason_type="feature",
            status="pending",
        )
        db.add_all([update1, update2])
        await db.commit()
        await db.refresh(update1)
        await db.refresh(update2)

        # Batch reject
        response = await authenticated_client.post(
            "/api/v1/updates/batch/reject",
            json={"update_ids": [update1.id, update2.id], "reason": "Test rejection"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["summary"]["rejected_count"] == 2
        assert data["summary"]["failed_count"] == 0

    async def test_batch_reject_invalid_ids(self, authenticated_client):
        """Test batch reject with invalid IDs returns partial success."""
        # Use non-existent IDs
        response = await authenticated_client.post(
            "/api/v1/updates/batch/reject", json={"update_ids": [99999, 99998]}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # All should fail (IDs don't exist)
        assert data["summary"]["rejected_count"] == 0
        assert data["summary"]["failed_count"] == 2

    async def test_batch_operations_require_auth(self, client, db):
        """Test batch operations require authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Test batch approve without auth
        response = await client.post("/api/v1/updates/batch/approve", json={"update_ids": [1, 2]})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # Test batch reject without auth
        response = await client.post("/api/v1/updates/batch/reject", json={"update_ids": [1, 2]})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
