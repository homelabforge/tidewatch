"""System information API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from datetime import datetime, UTC
import tomllib
import asyncio
import shutil
import logging
from app.db import get_db
from app.services.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


def get_version() -> str:
    """Get version from pyproject.toml."""
    try:
        # Prefer the pyproject.toml that is copied into the app image
        candidates = [
            Path("/app/pyproject.toml"),
            Path(__file__).resolve().parent.parent.parent / "pyproject.toml",
            Path("pyproject.toml"),
        ]

        for pyproject_path in candidates:
            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "unknown")
    except Exception:
        # Fall through to "unknown" on any parsing/IO error
        pass
    return "unknown"


async def get_docker_version() -> str:
    """Get Docker version."""
    try:
        # Use async subprocess to avoid blocking the event loop
        process = await asyncio.create_subprocess_exec(
            "docker",
            "version",
            "--format",
            "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode == 0:
                return stdout_bytes.decode("utf-8").strip()
        except asyncio.TimeoutError:
            pass
    except Exception:
        pass
    return "unknown"


@router.get("/info")
async def get_system_info(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
):
    """Get system information."""
    from app.models import Container, Update
    from app.services.settings_service import SettingsService
    from sqlalchemy import select, func

    total_containers = await db.scalar(select(func.count()).select_from(Container))
    monitored = await db.scalar(
        select(func.count()).select_from(Container).where(Container.policy == "auto")
    )
    pending_updates = await db.scalar(
        select(func.count()).select_from(Update).where(Update.status == "pending")
    )

    return {
        "version": get_version(),
        "docker_version": await get_docker_version(),
        "total_containers": total_containers or 0,
        "monitored_containers": monitored or 0,
        "pending_updates": pending_updates or 0,
        "auto_update_enabled": await SettingsService.get_bool(
            db, "auto_update_enabled", default=False
        ),
    }


@router.get("/version")
async def get_version_info(admin: Optional[dict] = Depends(require_auth)):
    """Get version information."""
    return {
        "version": get_version(),
        "docker_version": await get_docker_version(),
    }


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check for monitoring.

    Checks:
    - Database connectivity
    - Docker daemon availability
    - Disk space

    Returns:
        Health status with component details

    Note: This endpoint is public (no authentication required) for health monitoring
    """
    components = {}

    # Database check
    try:
        await db.execute(select(1))
        components["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        components["database"] = "unhealthy"

    # Docker check
    try:
        docker_version = await get_docker_version()
        components["docker"] = "healthy" if docker_version != "unknown" else "unhealthy"
    except Exception as e:
        logger.error(f"Docker health check failed: {e}")
        components["docker"] = "unhealthy"

    # Disk space check
    try:
        disk_usage = shutil.disk_usage("/")
        free_pct = (disk_usage.free / disk_usage.total) * 100
        components["disk_space"] = "healthy" if free_pct > 10 else "warning"
        components["disk_free_percent"] = round(free_pct, 2)
    except Exception as e:
        logger.error(f"Disk health check failed: {e}")
        components["disk_space"] = "unknown"

    # Overall status
    if all(
        c in ["healthy", "warning"] for c in components.values() if isinstance(c, str)
    ):
        overall = "healthy"
    elif any(c == "unhealthy" for c in components.values()):
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "components": components,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
async def readiness_check():
    """Kubernetes readiness probe.

    Simple endpoint that returns ready=true when the application is running.
    This is useful for Kubernetes readiness probes.

    Note: This endpoint is public (no authentication required) for K8s probes
    """
    return {"ready": True}


@router.get("/metrics")
async def prometheus_metrics(db: AsyncSession = Depends(get_db)):
    """Prometheus metrics endpoint.

    Provides metrics in Prometheus text format for scraping.

    Metrics exposed:
    - tidewatch_containers_total: Total containers monitored
    - tidewatch_containers_monitored: Containers with auto-update enabled
    - tidewatch_updates_pending: Pending updates
    - tidewatch_updates_total: Total updates by status

    Note: This endpoint is public (no authentication required) for Prometheus scraping
    """
    from app.models import Container, Update
    from sqlalchemy import func

    try:
        # Get container counts
        total_containers = (
            await db.scalar(select(func.count()).select_from(Container)) or 0
        )
        monitored_containers = (
            await db.scalar(
                select(func.count())
                .select_from(Container)
                .where(Container.policy == "auto")
            )
            or 0
        )

        # Get update counts by status
        pending_updates = (
            await db.scalar(
                select(func.count())
                .select_from(Update)
                .where(Update.status == "pending")
            )
            or 0
        )
        approved_updates = (
            await db.scalar(
                select(func.count())
                .select_from(Update)
                .where(Update.status == "approved")
            )
            or 0
        )
        applied_updates = (
            await db.scalar(
                select(func.count())
                .select_from(Update)
                .where(Update.status == "applied")
            )
            or 0
        )
        rejected_updates = (
            await db.scalar(
                select(func.count())
                .select_from(Update)
                .where(Update.status == "rejected")
            )
            or 0
        )

        # Build Prometheus text format
        metrics = []
        metrics.append("# HELP tidewatch_containers_total Total containers monitored")
        metrics.append("# TYPE tidewatch_containers_total gauge")
        metrics.append(f"tidewatch_containers_total {total_containers}")
        metrics.append("")

        metrics.append(
            "# HELP tidewatch_containers_monitored Containers with auto-update enabled"
        )
        metrics.append("# TYPE tidewatch_containers_monitored gauge")
        metrics.append(f"tidewatch_containers_monitored {monitored_containers}")
        metrics.append("")

        metrics.append("# HELP tidewatch_updates_total Total updates by status")
        metrics.append("# TYPE tidewatch_updates_total gauge")
        metrics.append(f'tidewatch_updates_total{{status="pending"}} {pending_updates}')
        metrics.append(
            f'tidewatch_updates_total{{status="approved"}} {approved_updates}'
        )
        metrics.append(f'tidewatch_updates_total{{status="applied"}} {applied_updates}')
        metrics.append(
            f'tidewatch_updates_total{{status="rejected"}} {rejected_updates}'
        )
        metrics.append("")

        content = "\n".join(metrics)
        return Response(content=content, media_type="text/plain; version=0.0.4")

    except Exception as e:
        logger.error(f"Failed to generate metrics: {e}")
        # Return minimal metrics on error
        return Response(
            content="# Error generating metrics\n",
            media_type="text/plain; version=0.0.4",
        )
