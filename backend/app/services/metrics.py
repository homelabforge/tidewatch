"""Prometheus metrics for TideWatch."""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.update import Update
from app.models.history import UpdateHistory

# Application info
app_info = Info("tidewatch_app", "TideWatch application information")
app_info.info({"version": "3.6.0", "name": "TideWatch"})

# Container metrics
containers_total = Gauge(
    "tidewatch_containers_total", "Total number of containers tracked"
)
containers_with_updates = Gauge(
    "tidewatch_containers_with_updates_available", "Containers with available updates"
)
containers_by_policy = Gauge(
    "tidewatch_containers_by_policy", "Containers grouped by policy", ["policy"]
)
containers_by_registry = Gauge(
    "tidewatch_containers_by_registry", "Containers grouped by registry", ["registry"]
)

# Update metrics
updates_pending = Gauge("tidewatch_updates_pending", "Pending updates")
updates_approved = Gauge("tidewatch_updates_approved", "Approved updates")
updates_rejected = Gauge("tidewatch_updates_rejected", "Rejected updates")
updates_applied_total = Counter(
    "tidewatch_updates_applied_total", "Total updates applied"
)
updates_failed_total = Counter("tidewatch_updates_failed_total", "Total updates failed")

# Update history metrics
update_history_success = Gauge(
    "tidewatch_update_history_success", "Successful updates in history"
)
update_history_failed = Gauge(
    "tidewatch_update_history_failed", "Failed updates in history"
)
update_history_rolled_back = Gauge(
    "tidewatch_update_history_rolled_back", "Rolled back updates in history"
)

# Update check metrics
update_checks_total = Counter(
    "tidewatch_update_checks_total", "Total update checks performed"
)
update_check_duration = Histogram(
    "tidewatch_update_check_duration_seconds", "Update check duration"
)

# Registry API metrics
registry_api_calls_total = Counter(
    "tidewatch_registry_api_calls_total", "Registry API calls", ["registry", "status"]
)
registry_cache_hits = Counter(
    "tidewatch_registry_cache_hits_total", "Registry cache hits", ["registry"]
)
registry_cache_misses = Counter(
    "tidewatch_registry_cache_misses_total", "Registry cache misses", ["registry"]
)

# Check job performance metrics
check_job_duration = Histogram(
    "tidewatch_check_job_duration_seconds",
    "Check job total duration",
    buckets=[10, 30, 60, 120, 300, 600, 1200],
)
check_job_containers_total = Histogram(
    "tidewatch_check_job_containers_total",
    "Containers checked per job",
    buckets=[10, 25, 50, 100, 200, 500],
)
check_job_deduplication_savings = Gauge(
    "tidewatch_check_job_deduplication_savings",
    "Containers saved by deduplication in last job",
)
check_job_cache_hit_rate = Gauge(
    "tidewatch_check_job_cache_hit_rate",
    "Run-cache hit rate percentage in last job",
)
container_check_latency = Histogram(
    "tidewatch_container_check_latency_seconds",
    "Per-container check latency",
    ["registry"],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
)
rate_limit_waits_total = Counter(
    "tidewatch_rate_limit_waits_total",
    "Rate limit wait events",
    ["registry"],
)
check_concurrency_active = Gauge(
    "tidewatch_check_concurrency_active",
    "Current number of concurrent container checks",
)

# Health check metrics
health_check_success_total = Counter(
    "tidewatch_health_check_success_total", "Successful health checks", ["container"]
)
health_check_failure_total = Counter(
    "tidewatch_health_check_failure_total", "Failed health checks", ["container"]
)
health_check_duration = Histogram(
    "tidewatch_health_check_duration_seconds", "Health check duration", ["container"]
)
health_check_failures_24h = Gauge(
    "tidewatch_health_check_failures_24h", "Health check failures in last 24 hours"
)


async def collect_metrics(db: AsyncSession) -> None:
    """Collect current metrics from database.

    Args:
        db: Database session
    """
    # Container metrics
    result = await db.execute(select(func.count()).select_from(Container))
    containers_total.set(result.scalar() or 0)

    result = await db.execute(
        select(func.count()).select_from(Container).where(Container.update_available)
    )
    containers_with_updates.set(result.scalar() or 0)

    # Containers by policy
    result = await db.execute(
        select(Container.policy, func.count(Container.id)).group_by(Container.policy)
    )
    policy_counts = {policy: 0 for policy in ["auto", "manual", "disabled", "security"]}
    for policy, count in result.fetchall():
        policy_counts[policy] = count
    for policy, count in policy_counts.items():
        containers_by_policy.labels(policy=policy).set(count)

    # Containers by registry
    result = await db.execute(
        select(Container.registry, func.count(Container.id)).group_by(
            Container.registry
        )
    )
    registry_counts = {}
    for registry, count in result.fetchall():
        if registry:
            registry_counts[registry] = count
    for registry, count in registry_counts.items():
        containers_by_registry.labels(registry=registry).set(count)

    # Update metrics
    result = await db.execute(
        select(func.count()).select_from(Update).where(Update.status == "pending")
    )
    updates_pending.set(result.scalar() or 0)

    result = await db.execute(
        select(func.count()).select_from(Update).where(Update.status == "approved")
    )
    updates_approved.set(result.scalar() or 0)

    result = await db.execute(
        select(func.count()).select_from(Update).where(Update.status == "rejected")
    )
    updates_rejected.set(result.scalar() or 0)

    # Update history metrics
    result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(UpdateHistory.status == "success")
    )
    update_history_success.set(result.scalar() or 0)

    result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(UpdateHistory.status == "failed")
    )
    update_history_failed.set(result.scalar() or 0)

    result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(UpdateHistory.status == "rolled_back")
    )
    update_history_rolled_back.set(result.scalar() or 0)

    # Health check failure metrics (last 24 hours)
    from datetime import datetime, timedelta, timezone

    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    result = await db.execute(
        select(func.count())
        .select_from(UpdateHistory)
        .where(UpdateHistory.status == "failed")
        .where(UpdateHistory.created_at >= last_24h)
        .where(UpdateHistory.error_message.like("%health%check%"))
    )
    health_check_failures_24h.set(result.scalar() or 0)


def get_metrics() -> bytes:
    """Get Prometheus metrics in text format.

    Returns:
        Metrics in Prometheus text format
    """
    return generate_latest()


def get_content_type() -> str:
    """Get Prometheus metrics content type.

    Returns:
        Content type string
    """
    return CONTENT_TYPE_LATEST
