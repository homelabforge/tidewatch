"""Tests for Vulnerability Scan API (app/api/scan.py).

Tests vulnerability scanning endpoints:
- POST /api/v1/scan/container/{id} - Scan single container
- POST /api/v1/scan/all - Scan all containers
- GET /api/v1/scan/results/{id} - Get scan results
- GET /api/v1/scan/summary - Scan summary statistics
"""

from unittest.mock import AsyncMock, patch

from fastapi import status

from app.models.container import Container
from app.models.vulnerability_scan import VulnerabilityScan
from app.services.settings_service import SettingsService


class TestScanContainerEndpoint:
    """Test suite for POST /api/v1/scan/container/{id} endpoint."""

    async def test_scan_container_valid_id(self, authenticated_client, db):
        """Test scanning container by valid ID."""
        # Create container with VulnForge enabled
        container = Container(
            name=f"scan-test-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Set VulnForge URL in settings
        await SettingsService.set(db, "vulnforge_api_url", "http://vulnforge:8080")
        await db.commit()

        # Mock VulnForge client response
        mock_vuln_data = {
            "total_vulnerabilities": 15,
            "severity_counts": {"CRITICAL": 2, "HIGH": 5, "MEDIUM": 6, "LOW": 2},
            "cve_list": ["CVE-2023-1234", "CVE-2023-5678"],
            "risk_score": 7.5,
        }

        with patch("app.services.scan_service.VulnForgeClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get_image_vulnerabilities.return_value = mock_vuln_data
            mock_client.return_value = mock_instance

            response = await authenticated_client.post(
                f"/api/v1/scan/container/{container.id}"
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["container_id"] == container.id
        assert data["total_vulns"] == 15
        assert data["critical"] == 2
        assert data["high"] == 5
        assert len(data["cves"]) == 2

    async def test_scan_container_nonexistent(self, authenticated_client):
        """Test scanning nonexistent container returns 404."""
        response = await authenticated_client.post("/api/v1/scan/container/99999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_scan_container_vulnforge_disabled(self, authenticated_client, db):
        """Test scanning container with VulnForge disabled returns 404."""
        # Create container with VulnForge disabled
        container = Container(
            name=f"no-scan-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=False,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        response = await authenticated_client.post(
            f"/api/v1/scan/container/{container.id}"
        )

        print(f"Response status: {response.status_code}")
        print(f"Response JSON: {response.json()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "disabled" in response.json()["detail"].lower()

    async def test_scan_container_requires_auth(self, client, db):
        """Test requires authentication."""
        # Enable auth mode
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Create container
        container = Container(
            name=f"auth-test-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        response = await client.post(f"/api/v1/scan/container/{container.id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestScanAllContainersEndpoint:
    """Test suite for POST /api/v1/scan/all endpoint."""

    async def test_scan_all_containers(self, authenticated_client, db):
        """Test scans all containers."""
        # Create multiple containers
        containers = [
            Container(
                name=f"scan-all-1-{id(self)}",
                image="nginx",
                current_tag="1.20",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="nginx",
                vulnforge_enabled=True,
            ),
            Container(
                name=f"scan-all-2-{id(self)}",
                image="redis",
                current_tag="6.0",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="redis",
                vulnforge_enabled=True,
            ),
        ]
        db.add_all(containers)
        await db.commit()

        # Set VulnForge URL
        await SettingsService.set(db, "vulnforge_api_url", "http://vulnforge:8080")
        await db.commit()

        # Mock VulnForge client
        mock_vuln_data = {
            "total_vulnerabilities": 5,
            "severity_counts": {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 2, "LOW": 0},
            "cve_list": ["CVE-2023-9999"],
            "risk_score": 6.0,
        }

        with patch("app.services.scan_service.VulnForgeClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get_image_vulnerabilities.return_value = mock_vuln_data
            mock_client.return_value = mock_instance

            response = await authenticated_client.post("/api/v1/scan/all")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2

    async def test_scan_all_filters_excluded(self, authenticated_client, db):
        """Test filters excluded containers from scan."""
        # Create containers with different VulnForge settings
        containers = [
            Container(
                name=f"enabled-{id(self)}",
                image="nginx",
                current_tag="1.20",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="nginx",
                vulnforge_enabled=True,
            ),
            Container(
                name=f"disabled-{id(self)}",
                image="redis",
                current_tag="6.0",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="redis",
                vulnforge_enabled=False,
            ),
        ]
        db.add_all(containers)
        await db.commit()

        # Set VulnForge URL
        await SettingsService.set(db, "vulnforge_api_url", "http://vulnforge:8080")
        await db.commit()

        # Mock VulnForge client
        mock_vuln_data = {
            "total_vulnerabilities": 3,
            "severity_counts": {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 0},
            "cve_list": [],
            "risk_score": 4.0,
        }

        with patch("app.services.scan_service.VulnForgeClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get_image_vulnerabilities.return_value = mock_vuln_data
            mock_client.return_value = mock_instance

            response = await authenticated_client.post("/api/v1/scan/all")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Only VulnForge-enabled container should be scanned
        assert len(data) == 1

    async def test_scan_all_requires_auth(self, client, db):
        """Test requires authentication."""
        # Enable auth mode
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.post("/api/v1/scan/all")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetScanResultsEndpoint:
    """Test suite for GET /api/v1/scan/results/{id} endpoint."""

    async def test_get_scan_results_valid_id(self, authenticated_client, db):
        """Test returns scan results for valid container ID."""
        # Create container
        container = Container(
            name=f"results-test-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create scan result
        scan = VulnerabilityScan(
            container_id=container.id,
            total_vulns=10,
            critical_count=1,
            high_count=3,
            medium_count=4,
            low_count=2,
            cves=["CVE-2023-1111", "CVE-2023-2222"],
            risk_score=6.5,
            status="completed",
        )
        db.add(scan)
        await db.commit()

        response = await authenticated_client.get(
            f"/api/v1/scan/results/{container.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["container_id"] == container.id
        assert data["total_vulns"] == 10
        assert data["critical"] == 1

    async def test_get_scan_results_no_scan(self, authenticated_client, db):
        """Test returns 404 when no scan results exist."""
        # Create container without scan results
        container = Container(
            name=f"no-results-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        response = await authenticated_client.get(
            f"/api/v1/scan/results/{container.id}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "no scan results" in response.json()["detail"].lower()

    async def test_get_scan_results_includes_cves(self, authenticated_client, db):
        """Test includes CVE details in results."""
        # Create container
        container = Container(
            name=f"cve-test-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        # Create scan with CVEs
        cve_list = ["CVE-2023-1234", "CVE-2023-5678", "CVE-2024-0001"]
        scan = VulnerabilityScan(
            container_id=container.id,
            total_vulns=3,
            critical_count=1,
            high_count=1,
            medium_count=1,
            low_count=0,
            cves=cve_list,
            status="completed",
        )
        db.add(scan)
        await db.commit()

        response = await authenticated_client.get(
            f"/api/v1/scan/results/{container.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "cves" in data
        assert len(data["cves"]) == 3
        assert "CVE-2023-1234" in data["cves"]

    async def test_get_scan_results_requires_auth(self, client, db):
        """Test requires authentication."""
        # Enable auth mode
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Create container
        container = Container(
            name=f"auth-results-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        response = await client.get(f"/api/v1/scan/results/{container.id}")

        # GET requests return 401 (no CSRF on GET)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestScanSummaryEndpoint:
    """Test suite for GET /api/v1/scan/summary endpoint."""

    async def test_scan_summary_statistics(self, authenticated_client, db):
        """Test returns scan summary statistics."""
        # Create containers
        containers = [
            Container(
                name=f"summary-1-{id(self)}",
                image="nginx",
                current_tag="1.20",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="nginx",
                vulnforge_enabled=True,
            ),
            Container(
                name=f"summary-2-{id(self)}",
                image="redis",
                current_tag="6.0",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name="redis",
                vulnforge_enabled=True,
            ),
        ]
        db.add_all(containers)
        await db.commit()
        for c in containers:
            await db.refresh(c)

        # Create scan results
        scans = [
            VulnerabilityScan(
                container_id=containers[0].id,
                total_vulns=10,
                critical_count=2,
                high_count=3,
                medium_count=3,
                low_count=2,
                status="completed",
            ),
            VulnerabilityScan(
                container_id=containers[1].id,
                total_vulns=5,
                critical_count=0,
                high_count=1,
                medium_count=3,
                low_count=1,
                status="completed",
            ),
        ]
        db.add_all(scans)
        await db.commit()

        response = await authenticated_client.get("/api/v1/scan/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_containers_scanned"] == 2
        assert data["total_vulnerabilities"] == 15
        assert "severity_breakdown" in data

    async def test_scan_summary_severity_breakdown(self, authenticated_client, db):
        """Test includes vulnerability severity breakdown."""
        # Create container and scan
        container = Container(
            name=f"severity-{id(self)}",
            image="nginx",
            current_tag="1.20",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        scan = VulnerabilityScan(
            container_id=container.id,
            total_vulns=20,
            critical_count=3,
            high_count=7,
            medium_count=8,
            low_count=2,
            status="completed",
        )
        db.add(scan)
        await db.commit()

        response = await authenticated_client.get("/api/v1/scan/summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "severity_breakdown" in data
        breakdown = data["severity_breakdown"]
        assert breakdown["critical"] == 3
        assert breakdown["high"] == 7
        assert breakdown["medium"] == 8
        assert breakdown["low"] == 2
        # Containers at risk (has critical or high vulns)
        assert data["containers_at_risk"] == 1

    async def test_scan_summary_requires_auth(self, client, db):
        """Test requires authentication."""
        # Enable auth mode
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        response = await client.get("/api/v1/scan/summary")

        # GET requests return 401 (no CSRF on GET)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
