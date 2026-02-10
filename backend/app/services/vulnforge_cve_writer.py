"""Shared helper for writing VulnForge CVE delta data to update records."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.history import UpdateHistory
from app.models.update import Update

logger = logging.getLogger(__name__)


async def write_cve_delta(
    db: AsyncSession,
    update_id: int,
    container_name: str,
    cves_fixed: list[str],
    cves_introduced: list[str],
    total_vulns: int,
    scan_id: int | None = None,
) -> bool:
    """Write CVE delta data to an Update and its UpdateHistory record.

    Args:
        db: Database session (caller manages commit)
        update_id: ID of the Update record to update
        container_name: Container name (for logging)
        cves_fixed: List of CVE IDs that were fixed
        cves_introduced: List of CVE IDs that were introduced
        total_vulns: Total vulnerability count from the scan
        scan_id: VulnForge scan ID (for logging)

    Returns:
        True if update record was found and updated, False otherwise
    """
    result = await db.execute(select(Update).where(Update.id == update_id))
    update_record = result.scalar_one_or_none()

    if not update_record:
        logger.warning(f"Update record {update_id} not found for CVE backfill")
        return False

    update_record.cves_fixed = cves_fixed
    update_record.new_vulns = total_vulns
    update_record.vuln_delta = len(cves_introduced) - len(cves_fixed)

    history_result = await db.execute(
        select(UpdateHistory).where(UpdateHistory.update_id == update_id)
    )
    history_record = history_result.scalar_one_or_none()

    if history_record:
        history_record.cves_fixed = cves_fixed
        logger.info(
            f"Backfilled UpdateHistory {history_record.id} with "
            f"{len(cves_fixed)} CVEs for {container_name}"
        )

    logger.info(
        f"Updated CVE data for {container_name}: "
        f"{len(cves_fixed)} fixed, {len(cves_introduced)} introduced, "
        f"{total_vulns} total vulns" + (f" (scan_id={scan_id})" if scan_id else "")
    )
    return True
