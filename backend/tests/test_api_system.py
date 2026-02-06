"""Tests for System API (app/api/system.py).

Tests system information and health endpoints:
- GET /api/v1/system/info - System information
- GET /api/v1/system/version - Version information
- GET /api/v1/system/health - Comprehensive health check
- GET /api/v1/system/ready - Readiness probe
- GET /api/v1/system/metrics - Prometheus metrics
"""

from fastapi import status

from app.models.container import Container


class TestSystemInfoEndpoint:
    """Test suite for GET /api/v1/system/info endpoint."""

    async def test_system_info_authenticated(self, authenticated_client, db):
        """Test getting system info with authentication."""
        # Create some test data
        container1 = Container(
            name="test-container-1",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            policy="auto",
        )
        container2 = Container(
            name="test-container-2",
            image="redis",
            current_tag="6.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="redis",
            policy="manual",
        )
        db.add_all([container1, container2])
        await db.commit()

        response = await authenticated_client.get("/api/v1/system/info")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "version" in data
        assert "docker_version" in data
        assert "total_containers" in data
        assert "monitored_containers" in data
        assert "pending_updates" in data
        assert "auto_update_enabled" in data
        assert data["total_containers"] == 2
        assert data["monitored_containers"] == 1  # Only auto policy

    async def test_system_info_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/system/info")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestVersionEndpoint:
    """Test suite for GET /api/v1/system/version endpoint."""

    async def test_version_info(self, authenticated_client):
        """Test getting version information."""
        response = await authenticated_client.get("/api/v1/system/version")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "version" in data
        assert "docker_version" in data
        assert data["version"] != ""

    async def test_version_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/system/version")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestHealthCheckEndpoint:
    """Test suite for GET /api/v1/system/health endpoint."""

    async def test_health_all_healthy(self, client, db):
        """Test health check when all components are healthy."""
        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "components" in data
        assert "timestamp" in data
        assert "database" in data["components"]
        assert "docker" in data["components"]
        assert "disk_space" in data["components"]

    async def test_health_component_details(self, client):
        """Test health check includes component details."""
        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        components = data["components"]

        # Check database component
        assert components["database"] in ["healthy", "unhealthy"]

        # Check Docker component
        assert components["docker"] in ["healthy", "unhealthy"]

        # Check disk space component
        assert components["disk_space"] in ["healthy", "warning", "unknown"]
        if "disk_free_percent" in components:
            assert isinstance(components["disk_free_percent"], (int, float))
            assert 0 <= components["disk_free_percent"] <= 100

    async def test_health_timestamp_format(self, client):
        """Test health check includes valid timestamp."""
        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "timestamp" in data
        # Timestamp should be in ISO format
        from datetime import datetime

        # Should not raise exception
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))

    async def test_health_public_endpoint(self, client, db):
        """Test health endpoint is public (no auth required)."""
        # Even with auth enabled, health should be accessible
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/system/health")

        # Should still work without auth
        assert response.status_code == status.HTTP_200_OK

    async def test_health_database_down(self, client, monkeypatch):
        """Test health check when database is down."""
        from sqlalchemy.ext.asyncio import AsyncSession

        async def failing_execute(self, *args, **kwargs):
            raise Exception("Connection refused")

        monkeypatch.setattr(AsyncSession, "execute", failing_execute)

        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["components"]["database"] == "unhealthy"

    async def test_health_docker_unreachable(self, client, monkeypatch):
        """Test health check when Docker is unreachable."""

        async def mock_docker_version():
            raise Exception("Docker daemon not running")

        monkeypatch.setattr("app.routes.system.get_docker_version", mock_docker_version)

        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["components"]["docker"] == "unhealthy"

    async def test_health_low_disk_space(self, client, monkeypatch):
        """Test health check warns on low disk space."""
        from collections import namedtuple

        DiskUsage = namedtuple("usage", ["total", "used", "free"])
        # 100GB total, 5GB free = 5% free (below 10% threshold)
        mock_usage = DiskUsage(
            total=100_000_000_000,
            used=95_000_000_000,
            free=5_000_000_000,
        )
        monkeypatch.setattr("app.routes.system.shutil.disk_usage", lambda _: mock_usage)

        response = await client.get("/api/v1/system/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["components"]["disk_space"] == "warning"


class TestReadinessProbeEndpoint:
    """Test suite for GET /api/v1/system/ready endpoint."""

    async def test_readiness_probe(self, client):
        """Test readiness probe always returns ready."""
        response = await client.get("/api/v1/system/ready")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["ready"] is True

    async def test_readiness_public_endpoint(self, client, db):
        """Test readiness endpoint is public (no auth required)."""
        # Even with auth enabled, readiness should be accessible
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/system/ready")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["ready"] is True


class TestPrometheusMetricsEndpoint:
    """Test suite for GET /api/v1/system/metrics endpoint."""

    async def test_metrics_format(self, client, db):
        """Test metrics returns Prometheus text format."""
        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"

        content = response.text
        assert "# HELP" in content
        assert "# TYPE" in content

    async def test_metrics_includes_container_count(self, client, db):
        """Test metrics includes container count gauge."""
        # Create test containers
        container = Container(
            name="metrics-test",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            policy="auto",
        )
        db.add(container)
        await db.commit()

        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK
        content = response.text
        assert "tidewatch_containers_total" in content
        assert "tidewatch_containers_monitored" in content

    async def test_metrics_includes_update_stats(self, client, db, make_update):
        """Test metrics includes update counters."""
        # Create test container and update
        container = Container(
            name="update-test",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
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
            status="pending",
        )
        db.add(update)
        await db.commit()

        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK
        content = response.text
        assert "tidewatch_updates_total" in content
        assert 'status="pending"' in content

    async def test_metrics_content_type(self, client):
        """Test metrics has correct Content-Type header."""
        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK
        assert "text/plain" in response.headers["content-type"]
        assert "version=0.0.4" in response.headers["content-type"]

    async def test_metrics_public_endpoint(self, client, db):
        """Test metrics endpoint is public (no auth required)."""
        # Even with auth enabled, metrics should be accessible for Prometheus
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK

    async def test_metrics_gauge_format(self, client, db):
        """Test metrics follow Prometheus gauge format."""
        response = await client.get("/api/v1/system/metrics")

        assert response.status_code == status.HTTP_200_OK
        content = response.text

        # Check for proper gauge format
        assert "# TYPE tidewatch_containers_total gauge" in content
        assert "# TYPE tidewatch_containers_monitored gauge" in content
        assert "# TYPE tidewatch_updates_total gauge" in content

        # Check metrics have numeric values
        import re

        # Match lines like: tidewatch_containers_total 5
        matches = re.findall(r"tidewatch_containers_total (\d+)", content)
        assert len(matches) > 0
        assert int(matches[0]) >= 0
