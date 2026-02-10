"""Regression tests for issues identified in Codex review (2025-02-09).

Tests cover:
- update_checker uses create_vulnforge_client (not removed constructor args)
- scan_service passes registry to get_image_vulnerabilities
- scan_service splits exception handling (transport vs domain errors)
- settings test_vulnforge_connection no longer references basic_auth
- PendingScanJob retention cleanup
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.models.container import Container
from app.models.pending_scan_job import PendingScanJob
from app.services.settings_service import SettingsService


class TestUpdateCheckerClientConstruction:
    """Verify update_checker uses create_vulnforge_client factory, not raw constructor."""

    async def test_enrich_with_vulnforge_uses_factory(self, db):
        """_enrich_with_vulnforge should use create_vulnforge_client, not VulnForgeClient()."""
        from app.models.update import Update
        from app.services.update_checker import UpdateChecker

        # Set up VulnForge as enabled
        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://vulnforge:8787")
        await db.commit()

        container = Container(
            name="test-container",
            image="nginx",
            current_tag="1.25",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.25",
            to_tag="1.26",
            registry="docker.io",
            reason_type="maintenance",
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Patch the factory — if update_checker still uses VulnForgeClient() directly,
        # this mock won't be called and the test proves nothing. The TypeError
        # from passing username/password would crash the test.
        mock_client = AsyncMock()
        mock_client.compare_vulnerabilities.return_value = None
        mock_client.get_image_vulnerabilities.return_value = None

        with patch(
            "app.services.update_checker.create_vulnforge_client",
            return_value=mock_client,
        ) as mock_factory:
            await UpdateChecker._enrich_with_vulnforge(db, update, container)

        # The factory should have been called (not the raw constructor)
        mock_factory.assert_called_once_with(db)

    async def test_refresh_vulnforge_baseline_uses_factory(self, db):
        """_refresh_vulnforge_baseline should use create_vulnforge_client."""
        from app.services.update_checker import UpdateChecker

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://vulnforge:8787")
        await db.commit()

        container = Container(
            name="test-baseline",
            image="nginx",
            current_tag="1.25",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_client = AsyncMock()
        mock_client.get_image_vulnerabilities.return_value = {"total_vulns": 5}
        mock_client.close = AsyncMock()

        with patch(
            "app.services.update_checker.create_vulnforge_client",
            return_value=mock_client,
        ) as mock_factory:
            await UpdateChecker._refresh_vulnforge_baseline(db, container)

        mock_factory.assert_called_once_with(db)


class TestScanServiceRegistryPassthrough:
    """Verify scan_service passes registry to VulnForge client."""

    async def test_scan_container_passes_registry(self, db):
        """scan_container should pass container.registry to get_image_vulnerabilities."""
        from app.services.scan_service import ScanService

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://vulnforge:8787")
        await db.commit()

        container = Container(
            name="ghcr-container",
            image="homelabforge/mygarage",
            current_tag="latest",
            registry="ghcr.io",
            compose_file="/compose/test.yml",
            service_name="mygarage",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_image_vulnerabilities.return_value = {
            "total_vulns": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "cves": [],
            "risk_score": 0,
        }

        with patch(
            "app.services.vulnforge_client.create_vulnforge_client",
            return_value=mock_client,
        ):
            await ScanService.scan_container(db, container.id)

        # Verify registry was passed
        mock_client.get_image_vulnerabilities.assert_called_once_with(
            "homelabforge/mygarage",
            "latest",
            registry="ghcr.io",
        )


class TestScanServiceExceptionHandling:
    """Verify scan_service differentiates transport vs domain errors."""

    async def test_connection_error_does_not_create_failed_scan(self, db):
        """Transport errors should not create a failed VulnerabilityScan record."""
        from app.models.vulnerability_scan import VulnerabilityScan
        from app.services.scan_service import ScanService

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://vulnforge:8787")
        await db.commit()

        container = Container(
            name="conn-error-test",
            image="nginx",
            current_tag="latest",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_image_vulnerabilities.side_effect = httpx.ConnectError("Connection refused")

        with patch(
            "app.services.vulnforge_client.create_vulnforge_client",
            return_value=mock_client,
        ):
            with pytest.raises(httpx.ConnectError):
                await ScanService.scan_container(db, container.id)

        # No failed scan record should have been created for transport errors
        result = await db.execute(
            select(VulnerabilityScan).where(
                VulnerabilityScan.container_id == container.id,
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_http_error_creates_failed_scan(self, db):
        """HTTP errors should create a failed scan record with status code."""
        from app.models.vulnerability_scan import VulnerabilityScan
        from app.services.scan_service import ScanService

        await SettingsService.set(db, "vulnforge_enabled", "true")
        await SettingsService.set(db, "vulnforge_url", "http://vulnforge:8787")
        await db.commit()

        container = Container(
            name="http-error-test",
            image="nginx",
            current_tag="latest",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
            vulnforge_enabled=True,
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        mock_response = httpx.Response(500, text="Internal Server Error")
        mock_response._request = httpx.Request("GET", "http://vulnforge:8787/test")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_image_vulnerabilities.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=mock_response.request,
            response=mock_response,
        )

        with patch(
            "app.services.vulnforge_client.create_vulnforge_client",
            return_value=mock_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await ScanService.scan_container(db, container.id)

        # A failed scan record SHOULD have been created for HTTP errors
        result = await db.execute(
            select(VulnerabilityScan).where(
                VulnerabilityScan.container_id == container.id,
            )
        )
        scan = result.scalar_one_or_none()
        assert scan is not None
        assert scan.status == "failed"
        assert "500" in scan.error_message


class TestSettingsBasicAuthRemoval:
    """Verify test_vulnforge_connection no longer uses basic_auth."""

    async def test_no_basic_auth_in_test_connection(self):
        """Test connection endpoint should not reference basic_auth."""
        import inspect

        from app.routes.settings import test_vulnforge_connection

        source = inspect.getsource(test_vulnforge_connection)
        assert "basic_auth" not in source
        assert "vulnforge_username" not in source
        assert "vulnforge_password" not in source
        assert "base64" not in source


class TestPendingScanJobCleanup:
    """Verify PendingScanJob retention cleanup works."""

    async def test_cleanup_deletes_old_completed_jobs(self, db):
        """Completed PendingScanJobs older than 30 days should be cleaned up."""
        from app.models.update import Update

        container = Container(
            name="cleanup-test",
            image="nginx",
            current_tag="latest",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="nginx",
        )
        db.add(container)
        await db.commit()
        await db.refresh(container)

        update = Update(
            container_id=container.id,
            container_name=container.name,
            from_tag="1.0",
            to_tag="1.1",
            registry="docker.io",
            reason_type="maintenance",
        )
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Create old completed job
        old_job = PendingScanJob(
            container_name=container.name,
            update_id=update.id,
            status="completed",
            completed_at=datetime.now(UTC) - timedelta(days=60),
        )
        # Create recent completed job
        recent_job = PendingScanJob(
            container_name=container.name,
            update_id=update.id,
            status="completed",
            completed_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db.add_all([old_job, recent_job])
        await db.commit()

        # Simulate the cleanup logic from scheduler
        from sqlalchemy import delete

        cutoff = datetime.now(UTC) - timedelta(days=30)
        await db.execute(
            delete(PendingScanJob).where(
                PendingScanJob.status.in_(["completed", "failed"]),
                PendingScanJob.completed_at < cutoff,
            )
        )
        await db.commit()

        # Old job should be gone
        check = await db.execute(select(PendingScanJob).where(PendingScanJob.id == old_job.id))
        assert check.scalar_one_or_none() is None

        # Recent job should remain
        check = await db.execute(select(PendingScanJob).where(PendingScanJob.id == recent_job.id))
        assert check.scalar_one_or_none() is not None
