"""Metrics collector service for storing container metrics history."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.container import Container
from app.models.metrics_history import MetricsHistory
from app.services.docker_stats import docker_stats_service
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Service for collecting and storing container metrics."""

    @staticmethod
    async def collect_all_metrics() -> dict:
        """Collect metrics for all containers and store in database.

        Three-phase design with batched docker calls:

        1. Short DB read — list tracked containers + concurrency setting.
        2. One ``docker ps`` (~10ms) to find running names, then ONE batched
           ``docker stats c1 c2 …`` (~2s for 40 containers) instead of N
           serial or concurrent calls. Falls back to per-container concurrent
           gather+semaphore on failure.
        3. Short DB write — bulk insert history rows.

        With 43 containers we measured: serial 91s → gather(4) 22s → batched 2s.
        DB session is never held across the docker calls so the dashboard
        stays responsive during the cycle.

        Returns:
            Dict with collection statistics
        """
        # Phase 1: short-held session — read container list and concurrency setting
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Container))
            rows = [(c.id, c.runtime_name, c.name) for c in result.scalars().all()]
            raw_concurrency = await SettingsService.get_int(db, "metrics_concurrency", default=4)
        metrics_concurrency = max(1, min(raw_concurrency, 16))

        if not rows:
            return {"collected": 0, "skipped": 0, "errors": 0}

        # Phase 2: fetch docker stats. Try the batched fast path first; if
        # docker can't list running names (proxy hiccup, daemon hiccup,
        # missing CLI), fall back to per-container gather.
        results: list[tuple]
        running_names = await docker_stats_service.list_running_container_names()
        if running_names is not None:
            results = await MetricsCollector._batched_phase2(rows, running_names)
        else:
            logger.warning("docker ps failed, falling back to per-container concurrent fetch")
            results = await MetricsCollector._concurrent_phase2(rows, metrics_concurrency)

        # Phase 3: short-held session — bulk insert + commit
        now = datetime.now(UTC)
        history_rows = [
            MetricsHistory(
                container_id=cid,
                collected_at=now,
                cpu_percent=m["cpu_percent"],
                memory_usage=m["memory_usage"],
                memory_limit=m["memory_limit"],
                memory_percent=m["memory_percent"],
                network_rx=m["network_rx"],
                network_tx=m["network_tx"],
                block_read=m["block_read"],
                block_write=m["block_write"],
                pids=m["pids"],
            )
            for status, cid, _name, m in results
            if status == "ok" and m is not None
        ]

        collected = len(history_rows)
        skipped = sum(1 for s, *_ in results if s == "skipped")
        errors = sum(1 for s, *_ in results if s == "error")

        if history_rows:
            async with AsyncSessionLocal() as db:
                try:
                    db.add_all(history_rows)
                    await db.commit()
                except OperationalError as e:
                    logger.error("Database error committing metrics: %s", e)
                    await db.rollback()
                    errors += collected
                    collected = 0

        logger.info(
            "Metrics collection complete: %d collected, %d skipped, %d errors",
            collected,
            skipped,
            errors,
        )
        return {"collected": collected, "skipped": skipped, "errors": errors}

    @staticmethod
    async def _batched_phase2(rows: list[tuple], running_names: set[str]) -> list[tuple]:
        """Batched fast path: filter to running, then ONE docker stats call."""
        # Partition rows into "running" (will get stats) and "skipped" (not running)
        to_stat: list[tuple[int, str, str]] = []
        results: list[tuple] = []
        for cid, runtime, name in rows:
            if runtime in running_names:
                to_stat.append((cid, runtime, name))
            else:
                logger.debug("Container %s is not running, skipping metrics collection", name)
                results.append(("skipped", cid, name, None))

        if not to_stat:
            return results

        names = [runtime for _, runtime, _ in to_stat]
        stats_by_name = await docker_stats_service.get_batched_stats(names)

        if not stats_by_name:
            # Batched call failed entirely (likely a container disappeared
            # between ps and stats). Mark these as errors; the next cycle
            # will retry. Don't fall back to per-container here — we'd be
            # paying double the docker overhead in the failure case.
            for cid, _runtime, name in to_stat:
                logger.warning("Failed to get metrics for %s (batched stats failed)", name)
                results.append(("error", cid, name, None))
            return results

        for cid, runtime, name in to_stat:
            metrics = stats_by_name.get(runtime)
            if not metrics:
                logger.warning("No stats returned for %s in batch", name)
                results.append(("error", cid, name, None))
            else:
                results.append(("ok", cid, name, metrics))
        return results

    @staticmethod
    async def _concurrent_phase2(rows: list[tuple], metrics_concurrency: int) -> list[tuple]:
        """Fallback path used when ``docker ps`` fails — per-container fetch.

        Per-task try/except is mandatory: asyncio.gather without
        ``return_exceptions=True`` propagates the first exception and aborts
        the whole batch. Broad except is intentional: per-container telemetry
        must never abort the cycle. ``check_container_running`` raises bare
        ``TimeoutError`` from ``asyncio.wait_for`` that narrower tuples
        wouldn't catch.
        """
        sem = asyncio.Semaphore(metrics_concurrency)

        async def fetch(cid: int, runtime: str, name: str) -> tuple:
            async with sem:
                try:
                    is_running = await docker_stats_service.check_container_running(runtime)
                    if not is_running:
                        logger.debug(
                            "Container %s is not running, skipping metrics collection", name
                        )
                        return ("skipped", cid, name, None)
                    metrics = await docker_stats_service.get_container_stats(runtime)
                    if not metrics:
                        logger.warning("Failed to get metrics for %s", name)
                        return ("error", cid, name, None)
                    return ("ok", cid, name, metrics)
                except Exception as e:  # noqa: BLE001 — telemetry resilience
                    logger.warning(
                        "Error collecting metrics for %s: %s: %s",
                        name,
                        type(e).__name__,
                        e,
                    )
                    return ("error", cid, name, None)

        return list(await asyncio.gather(*(fetch(*row) for row in rows)))

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
