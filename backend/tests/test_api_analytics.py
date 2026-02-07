"""Tests for Analytics API (app/api/analytics.py).

Tests analytics and dashboard statistics endpoints:
- GET /api/v1/analytics/summary - Analytics summary with trends and distributions
"""

from datetime import UTC, datetime, timedelta

from fastapi import status

from app.models.container import Container
from app.models.history import UpdateHistory


class TestAnalyticsSummaryEndpoint:
    """Test suite for GET /api/v1/analytics/summary endpoint."""

    async def test_summary_basic_structure(self, authenticated_client, db):
        """Test returns summary with all required fields."""
        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Check all required fields exist
        assert "period_days" in data
        assert "total_updates" in data
        assert "successful_updates" in data
        assert "failed_updates" in data
        assert "update_frequency" in data
        assert "vulnerability_trends" in data
        assert "policy_distribution" in data
        assert "avg_update_duration_seconds" in data
        assert "total_cves_fixed" in data

    async def test_summary_with_no_data(self, authenticated_client, db):
        """Test returns empty summary when no data exists."""
        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_updates"] == 0
        assert data["successful_updates"] == 0
        assert data["failed_updates"] == 0
        assert data["total_cves_fixed"] == 0
        assert isinstance(data["update_frequency"], list)
        assert isinstance(data["vulnerability_trends"], list)

    async def test_summary_policy_distribution(self, authenticated_client, db):
        """Test includes policy distribution from containers."""
        # Create containers with different policies
        containers = [
            Container(
                name="auto-container",
                image="nginx",
                current_tag="1.20",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="nginx",
                policy="auto",
            ),
            Container(
                name="manual-container",
                image="redis",
                current_tag="6.0",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="redis",
                policy="monitor",
            ),
        ]
        db.add_all(containers)
        await db.commit()

        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        policy_dist = data["policy_distribution"]
        assert isinstance(policy_dist, list)
        assert len(policy_dist) >= 1

        # Should have at least auto and manual policies
        policies = {item["label"] for item in policy_dist}
        assert "auto" in policies or "manual" in policies

    async def test_summary_update_frequency(self, authenticated_client, db):
        """Test update frequency includes successful updates."""
        # Create container
        container = Container(
            name="test-container",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create successful update history
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.19",
            to_tag="1.20",
            status="success",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_updates"] >= 1
        assert data["successful_updates"] >= 1

    async def test_summary_failed_updates(self, authenticated_client, db):
        """Test counts failed updates correctly."""
        # Create container
        container = Container(
            name="fail-container",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create failed update history
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="failed",
            started_at=datetime.now(UTC),
            error_message="Test failure",
        )
        db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_updates"] >= 1
        assert data["failed_updates"] >= 1

    async def test_summary_cves_fixed(self, authenticated_client, db):
        """Test counts CVEs fixed from update history."""
        # Create container
        container = Container(
            name="cve-container",
            image="nginx",
            current_tag="1.21",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create update history with CVEs fixed
        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="success",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            cves_fixed=["CVE-2023-1234", "CVE-2023-5678"],
        )
        db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_cves_fixed"] >= 2

    async def test_summary_period_30_days(self, authenticated_client, db):
        """Test summary covers 30-day period."""
        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["period_days"] == 30

    async def test_summary_avg_duration(self, authenticated_client, db):
        """Test calculates average update duration."""
        # Create container
        container = Container(
            name="duration-test",
            image="nginx",
            current_tag="1.21",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create update with duration
        started = datetime.now(UTC) - timedelta(seconds=120)
        completed = datetime.now(UTC)

        history = UpdateHistory(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.20",
            to_tag="1.21",
            status="success",
            started_at=started,
            completed_at=completed,
        )
        db.add(history)
        await db.commit()

        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "avg_update_duration_seconds" in data
        assert isinstance(data["avg_update_duration_seconds"], (int, float))

    async def test_summary_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_summary_vulnerability_trends_structure(self, authenticated_client, db):
        """Test vulnerability trends have correct structure."""
        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        vuln_trends = data["vulnerability_trends"]
        assert isinstance(vuln_trends, list)

        # If there are trends, check structure
        if len(vuln_trends) > 0:
            trend = vuln_trends[0]
            assert "date" in trend
            assert "cves_fixed" in trend

    async def test_summary_update_frequency_structure(self, authenticated_client, db):
        """Test update frequency has correct structure."""
        response = await authenticated_client.get("/api/v1/analytics/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        frequency = data["update_frequency"]
        assert isinstance(frequency, list)

        # If there's frequency data, check structure
        if len(frequency) > 0:
            point = frequency[0]
            assert "date" in point
            assert "count" in point
