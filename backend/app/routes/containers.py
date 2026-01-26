"""Containers API endpoints."""

import logging
import subprocess
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import undefer

from app.database import get_db
from app.services.auth import require_auth
from app.utils.security import sanitize_log_message
from app.models.container import Container
from app.models.update import Update
from app.models.history import UpdateHistory
from app.schemas.container import (
    ContainerSchema,
    ContainerUpdate,
    ContainerDetailsSchema,
    HistoryItemSchema,
    UpdateInfoSchema,
    PolicyUpdate,
    UpdateWindowUpdate,
    AppDependenciesResponse,
    DockerfileDependenciesResponse,
    HttpServersResponse,
)
from app.schemas.dependency import (
    DockerfileDependencySchema,
    AppDependencySchema,
    HttpServerSchema,
)
from app.services.compose_parser import ComposeParser
from app.services.dependency_manager import DependencyManager
from app.services.update_window import UpdateWindow
from app.services.docker_stats import docker_stats_service
from app.utils.error_handling import safe_error_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ContainerSchema])
async def list_containers(
    admin: Optional[dict] = Depends(require_auth),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of records to return"
    ),
    policy: Optional[str] = Query(
        None, description="Filter by update policy (auto, manual, disabled, security)"
    ),
    name: Optional[str] = Query(
        None, description="Search by container name (partial match)"
    ),
    image: Optional[str] = Query(
        None, description="Search by image name (partial match)"
    ),
    db: AsyncSession = Depends(get_db),
) -> List[ContainerSchema]:
    """List all tracked containers with pagination and filtering.

    Args:
        skip: Number of records to skip (default: 0)
        limit: Maximum number of records to return (default: 100, max: 1000)
        policy: Filter by update policy
        name: Search by container name (partial match)
        image: Search by image name (partial match)

    Returns:
        List of containers with their current status
    """
    # Build query with filters
    query = select(Container)

    # Apply filters
    if policy:
        query = query.where(Container.policy == policy)
    if name:
        query = query.where(Container.name.contains(name))
    if image:
        query = query.where(Container.image.contains(image))

    # Add ordering and pagination
    query = query.order_by(Container.name).offset(skip).limit(limit)

    result = await db.execute(query)
    containers = result.scalars().all()
    return containers


@router.get("/{container_id}", response_model=ContainerSchema)
async def get_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ContainerSchema:
    """Get basic container details by ID.

    Args:
        container_id: Container ID

    Returns:
        Container details
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    response = ContainerSchema.model_validate(container)
    if hasattr(response, "health_check_has_auth"):
        response.health_check_has_auth = bool(container.health_check_auth)
    return response


@router.get("/{container_id}/details", response_model=ContainerDetailsSchema)
async def get_container_details(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ContainerDetailsSchema:
    """Get comprehensive container details including history and updates.

    Args:
        container_id: Container ID

    Returns:
        Detailed container information with history timeline and available updates
    """
    # Get container
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Get current pending/approved update
    update_result = await db.execute(
        select(Update)
        .where(
            and_(
                Update.container_id == container_id,
                Update.status.in_(["pending", "approved"]),
            )
        )
        .order_by(desc(Update.created_at))
        .limit(1)
    )
    current_update = update_result.scalar_one_or_none()

    # Get update history (last 20 entries) with deferred fields loaded
    history_result = await db.execute(
        select(UpdateHistory)
        .options(
            undefer(UpdateHistory.event_type),
            undefer(UpdateHistory.dependency_type),
            undefer(UpdateHistory.dependency_id),
            undefer(UpdateHistory.dependency_name),
            undefer(UpdateHistory.file_path),
        )
        .where(UpdateHistory.container_id == container_id)
        .order_by(desc(UpdateHistory.started_at))
        .limit(20)
    )
    history = history_result.scalars().all()

    # Check container health status
    from app.services.container_monitor import ContainerMonitorService
    from datetime import datetime, timezone

    monitor = ContainerMonitorService()
    health_check_result = await monitor.check_health_status(container.name)

    # Determine health status based on check result
    health_status = "unknown"
    if health_check_result.get("healthy"):
        health_status = "healthy"
    elif health_check_result.get("running") is False:
        health_status = "stopped"
    else:
        health_status = "unhealthy"

    # Build response
    details = ContainerDetailsSchema(
        container=ContainerSchema.model_validate(container),
        current_update=UpdateInfoSchema.model_validate(current_update)
        if current_update
        else None,
        history=[HistoryItemSchema.model_validate(h) for h in history],
        health_status=health_status,
        last_health_check=datetime.now(timezone.utc),
    )
    if hasattr(details.container, "health_check_has_auth"):
        details.container.health_check_has_auth = bool(container.health_check_auth)
    return details


@router.get("/{container_id}/history", response_model=List[HistoryItemSchema])
async def get_container_history(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        50, ge=1, le=500, description="Maximum number of records to return"
    ),
    db: AsyncSession = Depends(get_db),
) -> List[HistoryItemSchema]:
    """Get update history for a specific container.

    Args:
        container_id: Container ID
        skip: Number of records to skip (default: 0)
        limit: Maximum number of records to return (default: 50, max: 500)

    Returns:
        List of update history entries for the container
    """
    # Verify container exists
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(
            status_code=404, detail=f"Container with ID {container_id} not found"
        )

    # Get update history (undefer deferred columns for Pydantic validation)
    history_result = await db.execute(
        select(UpdateHistory)
        .where(UpdateHistory.container_id == container_id)
        .options(
            undefer(UpdateHistory.event_type),
            undefer(UpdateHistory.dependency_type),
            undefer(UpdateHistory.dependency_id),
            undefer(UpdateHistory.dependency_name),
            undefer(UpdateHistory.file_path),
        )
        .order_by(desc(UpdateHistory.created_at))
        .offset(skip)
        .limit(limit)
    )
    history = history_result.scalars().all()

    return [HistoryItemSchema.model_validate(h) for h in history]


@router.put("/{container_id}", response_model=ContainerSchema)
async def update_container(
    container_id: int,
    update: ContainerUpdate,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ContainerSchema:
    """Update container policy and settings.

    Args:
        container_id: Container ID
        update: Update data

    Returns:
        Updated container
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Update fields if provided
    if update.policy is not None:
        container.policy = update.policy
    if update.scope is not None:
        container.scope = update.scope
    if update.include_prereleases is not None:
        container.include_prereleases = update.include_prereleases
    if update.vulnforge_enabled is not None:
        container.vulnforge_enabled = update.vulnforge_enabled
    if update.health_check_url is not None:
        # Empty string should be stored as None
        container.health_check_url = (
            update.health_check_url if update.health_check_url else None
        )
    if update.health_check_method is not None:
        if update.health_check_method not in ["auto", "http", "docker"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid health_check_method. Must be one of: auto, http, docker",
            )
        container.health_check_method = update.health_check_method
    if update.health_check_auth is not None:
        # Empty string should be stored as None (clears auth)
        container.health_check_auth = (
            update.health_check_auth if update.health_check_auth else None
        )
    if update.release_source is not None:
        # Empty string should be stored as None
        container.release_source = (
            update.release_source if update.release_source else None
        )
    if update.is_my_project is not None:
        container.is_my_project = update.is_my_project

    await db.commit()
    await db.refresh(container)

    return container


@router.put("/{container_id}/policy", response_model=ContainerSchema)
async def update_container_policy(
    container_id: int,
    policy_update: PolicyUpdate,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ContainerSchema:
    """Quick update for container policy.

    Args:
        container_id: Container ID
        policy_update: Policy update data

    Returns:
        Updated container
    """
    if policy_update.policy not in ["auto", "manual", "disabled", "security"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid policy. Must be one of: auto, manual, disabled, security",
        )

    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    container.policy = policy_update.policy
    await db.commit()
    await db.refresh(container)

    return container


@router.post("/sync")
async def sync_containers(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Sync containers from compose files.

    Discovers containers from docker-compose.yml files and adds/updates them
    in the database.

    Returns:
        Sync statistics
    """
    stats = await ComposeParser.sync_containers(db)
    return {
        "success": True,
        "stats": stats,
        "containers_found": stats["total"],
        "message": f"Synced {stats['total']} containers: "
        f"{stats['added']} added, {stats['updated']} updated",
    }


@router.delete("/{container_id}")
async def delete_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a container from tracking.

    Args:
        container_id: Container ID

    Returns:
        Success message
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    await db.delete(container)
    await db.commit()

    return {"success": True, "message": f"Container {container.name} deleted"}


@router.post("/{container_id}/exclude")
async def exclude_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Exclude container from automatic updates by setting policy to 'disabled'.

    Args:
        container_id: Container ID

    Returns:
        Updated container
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Store previous policy if not already disabled
    if container.policy != "disabled":
        # We don't have a field to store previous policy, so we'll just set to disabled
        container.policy = "disabled"
        await db.commit()
        await db.refresh(container)

    return {
        "success": True,
        "message": f"Container {container.name} excluded from updates",
        "container": ContainerSchema.model_validate(container),
    }


@router.post("/{container_id}/include")
async def include_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Include previously excluded container by setting policy to 'manual'.

    Args:
        container_id: Container ID

    Returns:
        Updated container
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Set to manual policy (conservative default)
    if container.policy == "disabled":
        container.policy = "manual"
        await db.commit()
        await db.refresh(container)

    return {
        "success": True,
        "message": f"Container {container.name} included in updates",
        "container": ContainerSchema.model_validate(container),
    }


@router.get("/excluded/list")
async def list_excluded_containers(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> List[ContainerSchema]:
    """List all excluded containers (policy='disabled').

    Returns:
        List of excluded containers
    """
    result = await db.execute(
        select(Container).where(Container.policy == "disabled").order_by(Container.name)
    )
    containers = result.scalars().all()
    return containers


@router.get("/{container_id}/dependencies")
async def get_container_dependencies(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get container dependencies and dependents.

    Args:
        container_id: Container ID

    Returns:
        Dict with dependencies and dependents arrays
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    import json

    dependencies = []
    if container.dependencies:
        try:
            dependencies = json.loads(container.dependencies)
        except json.JSONDecodeError:
            dependencies = []

    dependents = []
    if container.dependents:
        try:
            dependents = json.loads(container.dependents)
        except json.JSONDecodeError:
            dependents = []

    return {
        "container_id": container.id,
        "container_name": container.name,
        "dependencies": dependencies,
        "dependents": dependents,
    }


@router.put("/{container_id}/dependencies")
async def update_container_dependencies(
    container_id: int,
    dependencies: List[str],
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update container dependencies.

    Args:
        container_id: Container ID
        dependencies: List of container names this container depends on

    Returns:
        Success message with updated dependencies
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Validate dependencies
    valid, error = await DependencyManager.validate_dependencies(
        db, container.name, dependencies
    )

    if not valid:
        raise HTTPException(status_code=400, detail=error)

    # Update dependencies and reverse links
    await DependencyManager.update_container_dependencies(
        db, container.name, dependencies
    )

    return {
        "success": True,
        "message": f"Updated dependencies for {container.name}",
        "dependencies": dependencies,
    }


@router.get("/{container_id}/update-window")
async def get_container_update_window(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get container update window configuration.

    Args:
        container_id: Container ID

    Returns:
        Dict with update window configuration
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Validate format if set
    valid = True
    error = None
    if container.update_window:
        valid, error = UpdateWindow.validate_format(container.update_window)

    return {
        "container_id": container.id,
        "container_name": container.name,
        "update_window": container.update_window or "",
        "valid": valid,
        "error": error,
        "examples": ["02:00-06:00", "Sat,Sun:00:00-23:59", "Mon-Fri:22:00-06:00"],
    }


@router.put("/{container_id}/update-window")
async def update_container_update_window(
    container_id: int,
    window_update: UpdateWindowUpdate,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update container update window.

    Args:
        container_id: Container ID
        window_update: Update window configuration

    Returns:
        Success message with updated window
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    update_window = window_update.update_window

    # Validate format if not empty
    if update_window:
        valid, error = UpdateWindow.validate_format(update_window)
        if not valid:
            raise HTTPException(
                status_code=400, detail=f"Invalid window format: {error}"
            )

    container.update_window = update_window if update_window else None
    await db.commit()
    await db.refresh(container)

    return {
        "success": True,
        "message": f"Updated update window for {container.name}",
        "update_window": container.update_window,
    }


@router.get("/{container_id}/metrics")
async def get_container_metrics(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get container resource metrics (CPU, memory, network, disk I/O).

    Args:
        container_id: Container ID

    Returns:
        Dict with container metrics
    """
    # Get container from database
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Check if container is running
    is_running = await docker_stats_service.check_container_running(container.name)

    if not is_running:
        raise HTTPException(
            status_code=503,
            detail=f"Container {container.name} is not currently running",
        )

    # Get stats from Docker
    stats = await docker_stats_service.get_container_stats(container.name)

    if not stats:
        raise HTTPException(
            status_code=500, detail="Failed to retrieve container metrics"
        )

    return stats


@router.get("/{container_id}/metrics/history")
async def get_container_metrics_history(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    period: str = Query(default="24h", pattern="^(1h|6h|24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get historical metrics for a container.

    Args:
        container_id: Container ID
        period: Time period (1h, 6h, 24h, 7d, 30d)

    Returns:
        List of historical metrics data points
    """
    from datetime import datetime, timedelta, timezone
    from app.models.metrics_history import MetricsHistory

    # Get container
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Calculate time range based on period
    now = datetime.now(timezone.utc)
    period_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    start_time = now - period_map[period]

    # Query metrics history
    from sqlalchemy import and_

    result = await db.execute(
        select(MetricsHistory)
        .where(
            and_(
                MetricsHistory.container_id == container_id,
                MetricsHistory.collected_at >= start_time,
            )
        )
        .order_by(MetricsHistory.collected_at)
    )
    metrics = result.scalars().all()

    # Convert to list of dicts for JSON response
    return [
        {
            "timestamp": m.collected_at.isoformat(),
            "cpu_percent": m.cpu_percent,
            "memory_usage": m.memory_usage,
            "memory_limit": m.memory_limit,
            "memory_percent": m.memory_percent,
            "network_rx": m.network_rx,
            "network_tx": m.network_tx,
            "block_read": m.block_read,
            "block_write": m.block_write,
            "pids": m.pids,
        }
        for m in metrics
    ]


@router.get("/{container_id}/detect-health-check")
async def detect_health_check(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Detect health check URL from compose file.

    Parses the container's compose file to extract:
    - Health check path from healthcheck.test
    - Host from traefik labels
    - Combines them into a full URL
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Extract health check URL from compose file
    detected_url = ComposeParser.extract_health_check_url(
        container.compose_file, container.service_name
    )

    return {
        "health_check_url": detected_url,
        "method": "http" if detected_url else "docker",
        "confidence": "high" if detected_url else "none",
        "success": detected_url is not None,
        "message": "Health check URL detected"
        if detected_url
        else "No health check found in compose file",
    }


@router.get("/{container_id}/detect-release-source")
async def detect_release_source(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Detect release source from image registry.

    Extracts GitHub repository from image string.
    Currently supports ghcr.io images.
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Extract release source from image
    detected_source = ComposeParser.extract_release_source(container.image)

    return {
        "release_source": detected_source,
        "confidence": "high" if detected_source else "none",
        "source_type": "github"
        if detected_source and "github" in detected_source.lower()
        else ("dockerhub" if detected_source else "unknown"),
        "success": detected_source is not None,
        "message": "Release source detected"
        if detected_source
        else "Could not detect release source from image",
    }


@router.post("/{container_id}/restart")
async def restart_container(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Restart a container using docker compose.

    Args:
        container_id: Container ID

    Returns:
        Success message
    """
    from app.utils.validators import (
        validate_container_name,
        validate_compose_file_path,
        build_docker_compose_command,
        ValidationError,
    )

    # Get container
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Validate container name to prevent command injection
    try:
        validated_name = validate_container_name(container.name)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid container name")

    # Get compose file path
    compose_file = container.compose_file
    if not compose_file:
        raise HTTPException(
            status_code=400, detail="Container has no associated compose file"
        )

    # Validate compose file path to prevent path traversal
    try:
        compose_path = validate_compose_file_path(compose_file, allowed_base="/compose")
    except ValidationError as e:
        safe_error_response(logger, e, "Invalid compose file path", status_code=400)

    try:
        # Build safe command using list-based construction
        # For restart action via docker compose
        cmd = build_docker_compose_command(
            compose_file=compose_path, service_name=validated_name, action="restart"
        )

        # Execute restart
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise HTTPException(
                status_code=500, detail=f"Failed to restart container: {result.stderr}"
            )

        return {"message": f"Container {container.name} restarted successfully"}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Restart command timed out")
    except subprocess.CalledProcessError as e:
        safe_error_response(logger, e, "Docker compose command failed", status_code=500)
    except (OSError, PermissionError) as e:
        safe_error_response(logger, e, "File system error", status_code=500)
    except (ValueError, ValidationError) as e:
        safe_error_response(logger, e, "Invalid input", status_code=400)


@router.post("/{container_id}/recheck-updates")
async def recheck_updates(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Re-check updates for a single container.

    Triggered when scope/policy changes to immediately refresh update availability.
    Runs a full update check including scope-filtered and major version discovery.

    Args:
        container_id: Container ID

    Returns:
        Update check results with success status
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    # Import UpdateChecker
    from app.services.update_checker import UpdateChecker

    try:
        # Check for updates with current settings
        update = await UpdateChecker.check_container(db, container)
        await db.commit()

        return {
            "success": True,
            "update_found": update is not None,
            "latest_tag": container.latest_tag,
            "latest_major_tag": container.latest_major_tag,
            "message": f"Update check completed for {container.name}",
        }
    except Exception as e:
        logger.error(
            f"Failed to re-check updates for {container.name}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to re-check updates")


@router.get("/{container_id}/logs")
async def get_container_logs(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    tail: int = Query(default=100, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get container logs.

    Args:
        container_id: Container ID
        tail: Number of log lines to retrieve (default: 100, max: 10000)

    Returns:
        Container logs with timestamp
    """
    import docker
    from datetime import datetime, timezone
    from app.services import SettingsService

    # Get container
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        # Get docker socket
        docker_socket = (
            await SettingsService.get(db, "docker_socket") or "/var/run/docker.sock"
        )

        # Determine docker host format
        if docker_socket.startswith(("tcp://", "unix://")):
            docker_host = docker_socket
        else:
            docker_host = f"unix://{docker_socket}"

        # Connect to Docker
        client = docker.DockerClient(base_url=docker_host, timeout=10)

        # Get running container
        docker_container = client.containers.get(container.name)

        # Get logs
        logs = docker_container.logs(tail=tail, timestamps=False).decode("utf-8")
        log_lines = logs.strip().split("\n") if logs else []

        client.close()

        return {"logs": log_lines, "timestamp": datetime.now(timezone.utc).isoformat()}

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found in Docker")
    except docker.errors.APIError as e:
        safe_error_response(logger, e, "Docker API error", status_code=500)
    except docker.errors.DockerException as e:
        safe_error_response(logger, e, "Docker error", status_code=500)
    except OperationalError as e:
        safe_error_response(logger, e, "Database error", status_code=500)
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        safe_error_response(logger, e, "Failed to parse logs", status_code=500)


@router.get("/{container_id}/app-dependencies", response_model=AppDependenciesResponse)
async def get_app_dependencies(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> AppDependenciesResponse:
    """Get application dependencies for a container.

    This endpoint scans the container's project files (package.json, requirements.txt, etc.)
    and returns all discovered dependencies with their current and latest versions.

    Args:
        container_id: Container ID

    Returns:
        Application dependencies with update information
    """
    from app.services.app_dependencies import scanner
    from datetime import datetime

    # Verify container exists and is marked as "My Project"
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    if not container.is_my_project:
        raise HTTPException(
            status_code=403,
            detail="App dependency scanning is only available for My Projects",
        )

    try:
        # Try to fetch persisted dependencies first
        dependencies = await scanner.get_persisted_dependencies(db, container_id)

        # If no dependencies found, scan and persist
        if not dependencies:
            logger.info(
                f"No persisted dependencies found for container {sanitize_log_message(str(container_id))}, scanning..."
            )
            # Scan dependencies
            scanned_deps = await scanner.scan_container_dependencies(
                container.compose_file, container.service_name
            )

            # Persist to database
            if scanned_deps:
                await scanner.persist_dependencies(db, container_id, scanned_deps)
                # Fetch the persisted dependencies with IDs
                dependencies = await scanner.get_persisted_dependencies(
                    db, container_id
                )
            else:
                dependencies = []

        # Calculate stats
        total = len(dependencies)
        with_updates = sum(1 for dep in dependencies if dep.update_available)
        with_security = sum(1 for dep in dependencies if dep.security_advisories > 0)

        # Get last checked time from first dependency if available
        last_scan = dependencies[0].last_checked if dependencies else datetime.utcnow()

        return AppDependenciesResponse(
            dependencies=[
                AppDependencySchema.model_validate(dep) for dep in dependencies
            ],
            total=total,
            with_updates=with_updates,
            with_security_issues=with_security,
            last_scan=last_scan,
            scan_status="idle",
        )
    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to access dependency files")
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(
            f"Invalid data scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse dependencies")
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(
            f"Missing module scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Dependency scanner not available")


@router.post("/{container_id}/app-dependencies/scan")
async def scan_app_dependencies(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Force a rescan of application dependencies.

    This endpoint triggers a fresh scan of the container's dependency files.

    Args:
        container_id: Container ID

    Returns:
        Status message
    """
    from app.services.app_dependencies import scanner

    # Verify container exists and is marked as "My Project"
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    if not container.is_my_project:
        raise HTTPException(
            status_code=403,
            detail="App dependency scanning is only available for My Projects",
        )

    try:
        # Trigger scan
        dependencies = await scanner.scan_container_dependencies(
            container.compose_file, container.service_name
        )

        # Persist to database
        if dependencies:
            await scanner.persist_dependencies(db, container_id, dependencies)

        return {
            "message": "Dependency scan completed and persisted",
            "dependencies_found": len(dependencies),
            "updates_available": sum(1 for dep in dependencies if dep.update_available),
        }
    except (OSError, PermissionError) as e:
        logger.error(
            f"File system error scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to access dependency files")
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(
            f"Invalid data scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse dependencies")
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(
            f"Missing module scanning dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Dependency scanner not available")


@router.get(
    "/{container_id}/dockerfile-dependencies",
    response_model=DockerfileDependenciesResponse,
)
async def get_dockerfile_dependencies(
    container_id: int,
    include_ignored: bool = Query(True, description="Include ignored dependencies"),
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> DockerfileDependenciesResponse:
    """Get Dockerfile dependencies for a container.

    Returns all base images and build images found in the container's Dockerfile.
    Ignored dependencies are included by default and marked with ignored=True for UI display.
    """
    try:
        from app.services.dockerfile_parser import DockerfileParser

        # Get container
        result = await db.execute(select(Container).where(Container.id == container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        # Get dependencies from database
        parser = DockerfileParser()
        all_dependencies = await parser.get_container_dockerfile_dependencies(
            db, container_id
        )

        # Always include ignored dependencies (frontend handles display logic)
        # The include_ignored parameter is kept for backwards compatibility but defaults to True
        if not include_ignored:
            dependencies = [dep for dep in all_dependencies if not dep.ignored]
        else:
            dependencies = all_dependencies

        return DockerfileDependenciesResponse(
            dependencies=[
                DockerfileDependencySchema.model_validate(dep) for dep in dependencies
            ],
            total=len(dependencies),
            with_updates=sum(
                1 for dep in dependencies if dep.update_available and not dep.ignored
            ),
            last_scan=dependencies[0].last_checked if dependencies else None,
            scan_status="idle",
        )
    except HTTPException:
        raise
    except OperationalError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Database error getting Dockerfile dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Database error retrieving dependencies"
        )
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data getting Dockerfile dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse dependency data")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module getting Dockerfile dependencies for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Dockerfile parser not available")


@router.post("/{container_id}/dockerfile-dependencies/scan")
async def scan_dockerfile_dependencies(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    manual_path: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Scan a container's Dockerfile for base image dependencies.

    This will parse the Dockerfile and extract all FROM statements,
    saving them as tracked dependencies.

    Args:
        container_id: ID of the container to scan
        manual_path: Optional manual path to Dockerfile (overrides auto-detection)

    Returns:
        Scan results summary
    """
    try:
        from app.services.dockerfile_parser import DockerfileParser

        # Get container
        result = await db.execute(select(Container).where(Container.id == container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        # Scan Dockerfile
        parser = DockerfileParser()
        dependencies = await parser.scan_container_dockerfile(
            db, container, manual_path
        )

        return {
            "success": True,
            "message": "Dockerfile scan completed",
            "dependencies_found": len(dependencies),
            "base_images": sum(
                1 for dep in dependencies if dep.dependency_type == "base_image"
            ),
            "build_images": sum(
                1 for dep in dependencies if dep.dependency_type == "build_image"
            ),
            "updates_available": sum(1 for dep in dependencies if dep.update_available),
        }
    except HTTPException:
        raise
    except (OSError, PermissionError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"File system error scanning Dockerfile for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to access Dockerfile")
    except OperationalError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Database error scanning Dockerfile for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Database error saving dependencies"
        )
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data scanning Dockerfile for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse Dockerfile")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module scanning Dockerfile for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Dockerfile parser not available")


@router.post("/dockerfile-dependencies/check-updates")
async def check_dockerfile_updates(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Check all Dockerfile dependencies for available updates.

    This will query Docker registries to check if newer versions
    of base images are available.

    Returns:
        Statistics about the update check
    """
    try:
        from app.services.dockerfile_parser import DockerfileParser

        parser = DockerfileParser()
        stats = await parser.check_all_for_updates(db)

        return {
            "success": True,
            "message": "Dockerfile dependency update check completed",
            **stats,
        }
    except OperationalError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Database error checking Dockerfile dependencies for updates: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Database error checking updates")
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data checking Dockerfile dependencies for updates: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to process update data")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module checking Dockerfile dependencies for updates: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Dockerfile parser not available")


@router.post("/scan-my-projects")
async def scan_my_projects(
    admin: Optional[dict] = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Scan projects directory for dev containers and add them to Tidewatch.

    This endpoint will:
    - Scan the projects directory for compose.yaml files
    - Auto-discover dev containers
    - Add them to the database with is_my_project=True

    Returns:
        Dictionary with scan results (added, updated, skipped counts)
    """
    try:
        from app.services.project_scanner import ProjectScanner

        scanner = ProjectScanner(db)
        results = await scanner.scan_projects_directory()

        # Extract only safe integer counts to prevent information exposure
        # Using explicit int() casts to ensure type safety
        added_count = int(results.get("added", 0))
        updated_count = int(results.get("updated", 0))
        skipped_count = int(results.get("skipped", 0))

        # Build response with only verified-safe data
        response_results = {
            "added": added_count,
            "updated": updated_count,
            "skipped": skipped_count,
        }

        # Map error messages to predefined safe strings (whitelist approach)
        error_msg = results.get("error")
        if error_msg == "Feature disabled":
            response_results["message"] = "My Projects feature is disabled"
        elif error_msg == "Auto-scan disabled":
            response_results["message"] = "Auto-scan is disabled in settings"

        return {"success": True, "results": response_results}
    except (OSError, PermissionError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"File system error scanning my projects: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to access projects directory"
        )
    except OperationalError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Database error scanning my projects: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Database error saving projects")
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data scanning my projects: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse project data")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module scanning my projects: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Project scanner not available")


@router.get("/{container_id}/http-servers", response_model=HttpServersResponse)
async def get_http_servers(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> HttpServersResponse:
    """Get HTTP servers detected in a container.

    Returns all HTTP servers running in the container with version information.
    """
    try:
        from app.services.http_server_scanner import http_scanner

        # Get container
        result = await db.execute(select(Container).where(Container.id == container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        # Scan for HTTP servers
        servers = await http_scanner.scan_container_http_servers(container.name)

        # Calculate severity for each server
        for server in servers:
            server["severity"] = http_scanner._calculate_severity(
                server.get("current_version"),
                server.get("latest_version"),
                server.get("update_available", False),
            )

        return HttpServersResponse(
            servers=[HttpServerSchema(**server) for server in servers],
            total=len(servers),
            with_updates=sum(
                1 for server in servers if server.get("update_available", False)
            ),
            last_scan=servers[0].get("last_checked") if servers else None,
            scan_status="idle",
        )
    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Docker exec error getting HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to execute scanner in container"
        )
    except asyncio.TimeoutError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Timeout getting HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=504, detail="HTTP server scan timed out")
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data getting HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse server data")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module getting HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="HTTP server scanner not available")


@router.post("/{container_id}/http-servers/scan")
async def scan_http_servers(
    container_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Scan a container for running HTTP servers.

    This will detect HTTP servers running in the container and their versions.

    Args:
        container_id: ID of the container to scan

    Returns:
        Scan results summary
    """
    try:
        from app.services.http_server_scanner import http_scanner

        # Get container
        result = await db.execute(select(Container).where(Container.id == container_id))
        container = result.scalar_one_or_none()

        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        # Scan for HTTP servers
        servers = await http_scanner.scan_container_http_servers(container.name)

        return {
            "success": True,
            "message": "HTTP server scan completed",
            "servers_found": len(servers),
            "servers": [server["name"] for server in servers],
            "updates_available": sum(
                1 for server in servers if server.get("update_available", False)
            ),
        }
    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Docker exec error scanning HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to execute scanner in container"
        )
    except asyncio.TimeoutError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Timeout scanning HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=504, detail="HTTP server scan timed out")
    except (ValueError, KeyError, AttributeError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Invalid data scanning HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="Failed to parse server data")
    except (ImportError, ModuleNotFoundError) as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"Missing module scanning HTTP servers for container {sanitize_log_message(str(container_id))}: {sanitize_log_message(str(e))}"
        )
        raise HTTPException(status_code=500, detail="HTTP server scanner not available")
