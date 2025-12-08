"""API endpoints for vulnerability scanning."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth import require_auth
from app.services.scan_service import ScanService
from app.schemas.scan import ScanResultSchema, ScanSummarySchema
from app.utils.error_handling import safe_error_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/container/{container_id}", response_model=ScanResultSchema, status_code=status.HTTP_200_OK)
async def scan_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> ScanResultSchema:
    """Scan a single container for vulnerabilities.

    Args:
        container_id: ID of container to scan
        admin: Authenticated admin user
        db: Database session

    Returns:
        Scan result with vulnerability counts and CVE list

    Raises:
        404: Container not found
        400: VulnForge disabled for container or not configured
        500: Scan failed
    """
    logger.info(f"scan_container called with container_id={container_id}")
    try:
        result = await ScanService.scan_container(db, container_id)
        logger.info(f"scan_container succeeded for container_id={container_id}")
        return result
    except ValueError as e:
        logger.error(f"ValueError in scan_container: {e}")
        error_detail = str(e)
        logger.error(f"Raising HTTPException 404 with detail: {error_detail}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_detail)
    except Exception as e:
        logger.error(f"Unexpected exception in scan_container: {type(e).__name__}: {e}")
        safe_error_response(logger, e, "Failed to scan container")


@router.post("/all", response_model=List[ScanResultSchema], status_code=status.HTTP_200_OK)
async def scan_all_containers(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> List[ScanResultSchema]:
    """Scan all VulnForge-enabled containers.

    Args:
        admin: Authenticated admin user
        db: Database session

    Returns:
        List of scan results for all scanned containers

    Raises:
        500: Scan failed
    """
    try:
        results = await ScanService.scan_all_containers(db)
        return results
    except Exception as e:
        safe_error_response(logger, e, "Failed to scan all containers")


@router.get("/results/{container_id}", response_model=ScanResultSchema, status_code=status.HTTP_200_OK)
async def get_scan_results(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> ScanResultSchema:
    """Get cached vulnerability scan results for a container.

    Args:
        container_id: Container ID
        admin: Authenticated admin user
        db: Database session

    Returns:
        Most recent scan result

    Raises:
        404: Container not found or no scan results
    """
    try:
        result = await ScanService.get_scan_results(db, container_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        safe_error_response(logger, e, "Failed to get scan results")


@router.get("/summary", response_model=ScanSummarySchema, status_code=status.HTTP_200_OK)
async def get_scan_summary(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> ScanSummarySchema:
    """Get vulnerability scan summary statistics.

    Args:
        admin: Authenticated admin user
        db: Database session

    Returns:
        Aggregate scan statistics including severity breakdown

    Raises:
        500: Failed to retrieve summary
    """
    try:
        summary = await ScanService.get_scan_summary(db)
        return summary
    except Exception as e:
        safe_error_response(logger, e, "Failed to get scan summary")
