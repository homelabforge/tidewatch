"""Metrics collector service for storing container metrics history."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.metrics_history import MetricsHistory
from app.services.docker_stats import docker_stats_service

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Service for collecting and storing container metrics."""

    @staticmethod
    async def collect_all_metrics(db: AsyncSession) -> dict:
        """Collect metrics for all containers and store in database.

        Args:
            db: Database session

        Returns:
            Dict with collection statistics
        """
        stats = {
            "collected": 0,
            "skipped": 0,
            "errors": 0,
        }

        # Get all tracked containers
        result = await db.execute(select(Container))
        containers = result.scalars().all()

        for container in containers:
            try:
                # Check if container is running
                is_running = await docker_stats_service.check_container_running(container.name)

                if not is_running:
                    logger.debug(
                        f"Container {container.name} is not running, skipping metrics collection"
                    )
                    stats["skipped"] += 1
                    continue

                # Get current metrics
                metrics = await docker_stats_service.get_container_stats(container.name)

                if not metrics:
                    logger.warning(f"Failed to get metrics for {container.name}")
                    stats["errors"] += 1
                    continue

                # Create metrics history record
                history = MetricsHistory(
                    container_id=container.id,
                    collected_at=datetime.now(UTC),
                    cpu_percent=metrics["cpu_percent"],
                    memory_usage=metrics["memory_usage"],
                    memory_limit=metrics["memory_limit"],
                    memory_percent=metrics["memory_percent"],
                    network_rx=metrics["network_rx"],
                    network_tx=metrics["network_tx"],
                    block_read=metrics["block_read"],
                    block_write=metrics["block_write"],
                    pids=metrics["pids"],
                )

                db.add(history)
                stats["collected"] += 1

            except OperationalError as e:
                logger.error(f"Database error collecting metrics for {container.name}: {e}")
                stats["errors"] += 1
                continue
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Invalid metrics data for {container.name}: {e}")
                stats["errors"] += 1
                continue

        # Commit all metrics at once
        try:
            await db.commit()
            logger.info(
                f"Metrics collection complete: {stats['collected']} collected, "
                f"{stats['skipped']} skipped, {stats['errors']} errors"
            )
        except OperationalError as e:
            logger.error(f"Database error committing metrics: {e}")
            await db.rollback()
            stats["errors"] += stats["collected"]
            stats["collected"] = 0

        return stats

    @staticmethod
    async def cleanup_old_metrics(db: AsyncSession, days: int = 30) -> int:
        """Delete metrics older than specified days.

        Args:
            db: Database session
            days: Number of days to retain metrics (default: 30)

        Returns:
            Number of records deleted
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        cursor_result = await db.execute(
            delete(MetricsHistory).where(MetricsHistory.collected_at < cutoff_date)
        )

        deleted_count: int = cursor_result.rowcount  # type: ignore[assignment]
        await db.commit()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old metrics records (older than {days} days)")

        return deleted_count


# Singleton instance
metrics_collector = MetricsCollector()
