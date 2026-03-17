"""Service for container cleanup operations."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.history import UpdateHistory
from app.models.restart_log import ContainerRestartLog
from app.models.restart_state import ContainerRestartState
from app.models.update import Update
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


class ContainerCleanupService:
    """Service for removing containers and their related records."""

    @staticmethod
    async def remove_stale_container(db: AsyncSession, update_id: int) -> dict[str, Any]:
        """Remove a stale container and all related records from the database.

        Validates the update is a stale-type notification, then deletes all
        related records (history, restart state/logs, updates) and the
        container itself in a nested transaction.

        Args:
            db: Database session
            update_id: Update ID (must be stale-type)

        Returns:
            Success dict with message

        Raises:
            HTTPException: 404 if not found, 400 if not stale, 500 on DB error
        """
        from fastapi import HTTPException

        result = await db.execute(select(Update).where(Update.id == update_id))
        update = result.scalar_one_or_none()

        if not update:
            raise HTTPException(status_code=404, detail="Update not found")

        if update.reason_type != "stale":
            raise HTTPException(
                status_code=400,
                detail="Only stale container notifications can use remove-container action",
            )

        container_result = await db.execute(
            select(Container).where(Container.id == update.container_id)
        )
        container = container_result.scalar_one_or_none()

        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        container_name = container.name

        try:
            async with db.begin_nested():
                # Delete related records
                await db.execute(
                    UpdateHistory.__table__.delete().where(
                        UpdateHistory.container_id == container.id
                    )
                )
                await db.execute(
                    ContainerRestartState.__table__.delete().where(
                        ContainerRestartState.container_id == container.id
                    )
                )
                await db.execute(
                    ContainerRestartLog.__table__.delete().where(
                        ContainerRestartLog.container_id == container.id
                    )
                )
                await db.execute(
                    Update.__table__.delete().where(Update.container_id == container.id)
                )
                await db.delete(container)

            await db.commit()

            logger.info(
                f"Removed stale container from database: "
                f"{sanitize_log_message(str(container_name))}"
            )

            return {
                "success": True,
                "message": f"Container '{container_name}' removed from database",
            }
        except IntegrityError as e:
            await db.rollback()
            logger.error(
                f"Database constraint violation removing container: {sanitize_log_message(str(e))}"
            )
            raise HTTPException(
                status_code=500,
                detail="Database constraint error during container removal",
            )
        except OperationalError as e:
            await db.rollback()
            logger.error(f"Database error removing container: {sanitize_log_message(str(e))}")
            raise HTTPException(
                status_code=500,
                detail="Database error during container removal",
            )
        except (KeyError, AttributeError) as e:
            await db.rollback()
            logger.error(f"Invalid data removing container: {sanitize_log_message(str(e))}")
            raise HTTPException(
                status_code=500,
                detail="Invalid container data",
            )
