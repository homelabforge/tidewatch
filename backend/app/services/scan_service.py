"""Service layer for vulnerability scanning operations."""

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.vulnerability_scan import VulnerabilityScan
from app.schemas.scan import ScanResultSchema, ScanSummarySchema

logger = logging.getLogger(__name__)


class ScanService:
    """Service for managing vulnerability scans using VulnForge."""

    @staticmethod
    async def scan_container(db: AsyncSession, container_id: int) -> ScanResultSchema:
        """Scan a single container for vulnerabilities.

        Args:
            db: Database session
            container_id: Container ID to scan

        Returns:
            ScanResultSchema with scan results

        Raises:
            ValueError: If container not found or VulnForge disabled for container
            Exception: If scan fails
        """
        # Get container
        result = await db.execute(select(Container).where(Container.id == container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise ValueError(f"Container with ID {container_id} not found")

        # Check global VulnForge setting first
        from app.services.settings_service import SettingsService

        vulnforge_global = await SettingsService.get_bool(db, "vulnforge_enabled")
        if not vulnforge_global:
            raise ValueError("VulnForge integration is globally disabled")

        logger.info(f"Container {container.name}: vulnforge_enabled={container.vulnforge_enabled}")
        if not container.vulnforge_enabled:
            error_msg = f"VulnForge scanning is disabled for container '{container.name}'"
            logger.error(f"Raising ValueError: {error_msg}")
            raise ValueError(error_msg)

        # Get VulnForge client (handles URL, auth, and enabled checks)
        from app.services.vulnforge_client import create_vulnforge_client

        client = await create_vulnforge_client(db)
        if not client:
            raise ValueError("VulnForge URL not configured")

        async with client:
            try:
                # Get vulnerability data from VulnForge
                vuln_data = await client.get_image_vulnerabilities(
                    str(container.image),
                    str(container.current_tag),
                    registry=str(container.registry),
                )

                # Parse vulnerability data (matches vulnforge_client.py return format)
                vuln_dict = vuln_data or {}

                # Create scan record
                scan = VulnerabilityScan(
                    container_id=container_id,
                    scanned_at=datetime.now(UTC),
                    status="completed",
                    total_vulns=vuln_dict.get("total_vulns", 0),
                    critical_count=vuln_dict.get("critical", 0),
                    high_count=vuln_dict.get("high", 0),
                    medium_count=vuln_dict.get("medium", 0),
                    low_count=vuln_dict.get("low", 0),
                    cves=vuln_dict.get("cves", []),
                    risk_score=vuln_dict.get("risk_score"),
                )

                db.add(scan)
                await db.commit()
                await db.refresh(scan)

                # Return scan result
                return ScanResultSchema(
                    id=scan.id,
                    container_id=scan.container_id,
                    container_name=container.name,
                    scanned_at=scan.scanned_at,
                    total_vulns=scan.total_vulns,
                    critical=scan.critical_count,
                    high=scan.high_count,
                    medium=scan.medium_count,
                    low=scan.low_count,
                    cves=scan.cves,
                    risk_score=scan.risk_score,
                    status=scan.status,
                )

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Transport/infra errors — VulnForge unreachable, don't create noisy
                # "failed scan" records for transient connectivity issues
                logger.error(f"VulnForge connection error scanning {container.name}: {e}")
                raise
            except httpx.HTTPStatusError as e:
                # VulnForge returned an error response (auth failure, 500, etc.)
                logger.error(
                    f"VulnForge HTTP error scanning {container.name}: "
                    f"{e.response.status_code} {e.response.text[:200]}"
                )
                scan = VulnerabilityScan(
                    container_id=container_id,
                    scanned_at=datetime.now(UTC),
                    status="failed",
                    error_message=f"VulnForge HTTP {e.response.status_code}",
                )
                db.add(scan)
                await db.commit()
                raise
            except Exception as e:
                # Actual scan-domain failures (parsing, data issues)
                logger.error(f"Failed to scan container {container.name}: {e}")
                scan = VulnerabilityScan(
                    container_id=container_id,
                    scanned_at=datetime.now(UTC),
                    status="failed",
                    error_message=str(e),
                )
                db.add(scan)
                await db.commit()
                raise

    @staticmethod
    async def scan_all_containers(db: AsyncSession) -> list[ScanResultSchema]:
        """Scan all VulnForge-enabled containers.

        Args:
            db: Database session

        Returns:
            List of scan results
        """
        # Get all containers with VulnForge enabled
        result = await db.execute(select(Container).where(Container.vulnforge_enabled))
        containers = result.scalars().all()

        scan_results = []
        for container in containers:
            try:
                scan_result = await ScanService.scan_container(db, container.id)
                scan_results.append(scan_result)
            except Exception as e:
                logger.error(f"Failed to scan container {container.name}: {e}")
                continue

        return scan_results

    @staticmethod
    async def get_scan_results(db: AsyncSession, container_id: int) -> ScanResultSchema:
        """Get cached scan results for a container.

        Args:
            db: Database session
            container_id: Container ID

        Returns:
            Most recent scan result

        Raises:
            ValueError: If no scan results found
        """
        # Get container
        container_result = await db.execute(select(Container).where(Container.id == container_id))
        container = container_result.scalar_one_or_none()

        if not container:
            raise ValueError(f"Container with ID {container_id} not found")

        # Get most recent scan
        scan_result = await db.execute(
            select(VulnerabilityScan)
            .where(VulnerabilityScan.container_id == container_id)
            .order_by(VulnerabilityScan.scanned_at.desc())
            .limit(1)
        )
        scan = scan_result.scalar_one_or_none()

        if not scan:
            raise ValueError(f"No scan results found for container '{container.name}'")

        return ScanResultSchema(
            id=scan.id,
            container_id=scan.container_id,
            container_name=container.name,
            scanned_at=scan.scanned_at,
            total_vulns=scan.total_vulns,
            critical=scan.critical_count,
            high=scan.high_count,
            medium=scan.medium_count,
            low=scan.low_count,
            cves=scan.cves,
            risk_score=scan.risk_score,
            status=scan.status,
        )

    @staticmethod
    async def get_scan_summary(db: AsyncSession) -> ScanSummarySchema:
        """Get scan summary statistics across all containers.

        Args:
            db: Database session

        Returns:
            ScanSummarySchema with aggregate statistics
        """
        # Get total containers scanned (distinct container_ids)
        total_scanned_result = await db.execute(
            select(func.count(func.distinct(VulnerabilityScan.container_id)))
        )
        total_containers_scanned = total_scanned_result.scalar() or 0

        # Get total vulnerabilities from most recent scans
        subquery = (
            select(
                VulnerabilityScan.container_id,
                func.max(VulnerabilityScan.scanned_at).label("latest_scan"),
            )
            .group_by(VulnerabilityScan.container_id)
            .subquery()
        )

        latest_scans_result = await db.execute(
            select(VulnerabilityScan).join(
                subquery,
                and_(
                    VulnerabilityScan.container_id == subquery.c.container_id,
                    VulnerabilityScan.scanned_at == subquery.c.latest_scan,
                ),
            )
        )
        latest_scans = latest_scans_result.scalars().all()

        # Calculate aggregates
        total_vulnerabilities = sum(scan.total_vulns for scan in latest_scans)
        critical_total = sum(scan.critical_count for scan in latest_scans)
        high_total = sum(scan.high_count for scan in latest_scans)
        medium_total = sum(scan.medium_count for scan in latest_scans)
        low_total = sum(scan.low_count for scan in latest_scans)

        # Containers at risk (critical or high vulnerabilities)
        containers_at_risk = sum(
            1 for scan in latest_scans if scan.critical_count > 0 or scan.high_count > 0
        )

        # Get last scan timestamp
        last_scan_result = await db.execute(select(func.max(VulnerabilityScan.scanned_at)))
        last_scan = last_scan_result.scalar()

        return ScanSummarySchema(
            total_containers_scanned=total_containers_scanned,
            total_vulnerabilities=total_vulnerabilities,
            severity_breakdown={
                "critical": critical_total,
                "high": high_total,
                "medium": medium_total,
                "low": low_total,
            },
            last_scan=last_scan,
            containers_at_risk=containers_at_risk,
        )
