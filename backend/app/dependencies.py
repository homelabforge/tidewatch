"""Shared FastAPI dependencies for route handlers."""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.container import Container


async def get_container_or_404(
    container_id: int,
    db: AsyncSession = Depends(get_db),
) -> Container:
    """Fetch a container by ID or raise 404.

    Args:
        container_id: Container ID from path parameter
        db: Database session

    Returns:
        Container instance

    Raises:
        HTTPException: 404 if container not found
    """
    result = await db.execute(select(Container).where(Container.id == container_id))
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    return container
