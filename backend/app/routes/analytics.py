"""Analytics endpoints for TideWatch dashboard insights."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.container import Container
from app.models.history import UpdateHistory
from app.schemas.analytics import (
    AnalyticsSummary,
    DistributionItem,
    FrequencyPoint,
    VulnerabilityPoint,
)
from app.services.auth import require_auth

router = APIRouter()


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    _admin: dict | None = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> AnalyticsSummary:
    """Return aggregated analytics for the dashboard."""
    now = datetime.now(UTC)
    start_window = now - timedelta(days=30)
    start_window_str = start_window.strftime("%Y-%m-%d %H:%M:%S")

    timestamp_col = func.datetime(
        func.coalesce(
            UpdateHistory.completed_at,
            UpdateHistory.started_at,
            UpdateHistory.created_at,
        )
    )
    day_col = func.strftime("%Y-%m-%d", timestamp_col)

    # Update frequency (successful updates per day)
    frequency_result = await db.execute(
        select(day_col.label("day"), func.count().label("count"))
        .where(
            UpdateHistory.status == "success",
            timestamp_col >= start_window_str,
        )
        .group_by(day_col)
        .order_by(day_col)
    )

    frequency_rows = frequency_result.all()

    update_frequency: list[FrequencyPoint] = [
        FrequencyPoint(date=row[0], count=int(row[1])) for row in frequency_rows
    ]

    # Vulnerability trends (CVEs fixed per day)
    history_rows = await db.execute(select(UpdateHistory).where(timestamp_col >= start_window_str))
    histories = history_rows.scalars().all()

    cve_counts: dict[str, int] = defaultdict(int)
    for record in histories:
        reference_time = record.completed_at or record.started_at or record.created_at or now
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=UTC)
        else:
            reference_time = reference_time.astimezone(UTC)
        day_key = reference_time.date().isoformat()
        cve_counts[day_key] += len(record.cves_fixed or [])

    vulnerability_trends: list[VulnerabilityPoint] = [
        VulnerabilityPoint(date=key, cves_fixed=value) for key, value in sorted(cve_counts.items())
    ]

    # Policy distribution
    policy_result = await db.execute(
        select(Container.policy, func.count().label("count")).group_by(Container.policy)
    )

    policy_rows = policy_result.all()
    policy_distribution: list[DistributionItem] = [
        DistributionItem(label=row[0], value=int(row[1])) for row in policy_rows
    ]

    # Total updates (all statuses) in the period
    total_updates_result = await db.execute(
        select(func.count()).select_from(UpdateHistory).where(timestamp_col >= start_window_str)
    )
    total_updates = total_updates_result.scalar_one()

    # Successful updates
    successful_updates_result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(
            UpdateHistory.status == "success",
            timestamp_col >= start_window_str,
        )
    )
    successful_updates = successful_updates_result.scalar_one()

    # Failed updates
    failed_updates_result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(
            UpdateHistory.status == "failed",
            timestamp_col >= start_window_str,
        )
    )
    failed_updates = failed_updates_result.scalar_one()

    # Average update duration
    duration_result = await db.execute(
        select(
            func.avg(
                func.julianday(UpdateHistory.completed_at)
                - func.julianday(UpdateHistory.started_at)
            )
        ).where(
            UpdateHistory.status == "success",
            UpdateHistory.completed_at.isnot(None),
            UpdateHistory.started_at.isnot(None),
            timestamp_col >= start_window_str,
        )
    )
    avg_duration_days = duration_result.scalar_one() or 0.0
    avg_update_duration_seconds = avg_duration_days * 86400  # Convert days to seconds

    # Total CVEs fixed in the period
    total_cves_fixed = sum(cve_counts.values())

    # Count updates that fixed at least one CVE
    updates_with_cves = sum(1 for record in histories if record.cves_fixed)

    return AnalyticsSummary(
        period_days=30,
        total_updates=total_updates,
        successful_updates=successful_updates,
        failed_updates=failed_updates,
        update_frequency=update_frequency,
        vulnerability_trends=vulnerability_trends,
        policy_distribution=policy_distribution,
        avg_update_duration_seconds=avg_update_duration_seconds,
        total_cves_fixed=total_cves_fixed,
        updates_with_cves=updates_with_cves,
    )
