"""Check run context for scoped caching and deduplication.

Provides run-scoped tag caching (separate from global 15-min cache) and
container deduplication to minimize redundant registry API calls during
a single update check job.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.container import Container

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageCheckKey:
    """Unique key for deduplication of image checks.

    Containers with identical ImageCheckKey can share the same registry
    lookup results since they're checking the same image with the same
    scope and prerelease settings.

    Attributes:
        registry: Registry name (normalized lowercase)
        image: Image name (e.g., "postgres", "linuxserver/plex")
        current_tag: Current tag being checked
        scope: Update scope ("patch", "minor", "major")
        include_prereleases: Whether prereleases are included in search
    """

    registry: str
    image: str
    current_tag: str
    scope: str
    include_prereleases: bool

    @classmethod
    def from_container(cls, container: Container, include_prereleases: bool) -> ImageCheckKey:
        """Create ImageCheckKey from a Container.

        Args:
            container: Container model instance
            include_prereleases: Effective include_prereleases setting

        Returns:
            ImageCheckKey for this container's image signature
        """
        # Use str() to handle SQLAlchemy Column types for pyright
        return cls(
            registry=str(container.registry).lower(),  # type: ignore[attr-defined]
            image=str(container.image),  # type: ignore[attr-defined]
            current_tag=str(container.current_tag),  # type: ignore[attr-defined]
            scope=str(container.scope),  # type: ignore[attr-defined]
            include_prereleases=include_prereleases,
        )


@dataclass
class TagFetchResult:
    """Result of fetching tags from a registry.

    Cached during a check run to avoid duplicate registry calls.

    Attributes:
        tags: All available tags for the image
        latest_tag: Latest tag within scope (None if no update)
        latest_major_tag: Latest major version (for scope violation visibility)
        metadata: Additional metadata (e.g., digest for 'latest' tag)
        fetched_at: When the result was fetched
        error: Error message if fetch failed
    """

    tags: list[str]
    latest_tag: str | None
    latest_major_tag: str | None
    metadata: dict[str, Any] | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


@dataclass
class CheckRunMetrics:
    """Metrics for a single check run.

    Collected during job execution for instrumentation and debugging.

    Attributes:
        started_at: When the check run started
        completed_at: When the check run completed
        total_containers: Total containers to check
        checked_containers: Containers processed so far
        deduplicated_containers: Containers saved by deduplication
        unique_images: Number of unique image signatures
        updates_found: Updates detected
        errors: Errors encountered
        container_latencies: Per-container check latency (seconds)
        registry_calls: Registry API call count per registry
        registry_cache_hits: Run-cache hits per registry
        registry_cache_misses: Run-cache misses per registry
    """

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Counts
    total_containers: int = 0
    checked_containers: int = 0
    deduplicated_containers: int = 0
    unique_images: int = 0
    updates_found: int = 0
    errors: int = 0

    # Timing
    container_latencies: list[float] = field(default_factory=list)

    # Registry stats
    registry_calls: dict[str, int] = field(default_factory=dict)
    registry_cache_hits: dict[str, int] = field(default_factory=dict)
    registry_cache_misses: dict[str, int] = field(default_factory=dict)

    def record_container_check(self, registry: str, latency: float, cache_hit: bool) -> None:
        """Record metrics for a container check.

        Args:
            registry: Registry that was checked
            latency: Check latency in seconds
            cache_hit: Whether run-cache was hit
        """
        self.container_latencies.append(latency)
        self.registry_calls[registry] = self.registry_calls.get(registry, 0) + 1

        if cache_hit:
            self.registry_cache_hits[registry] = self.registry_cache_hits.get(registry, 0) + 1
        else:
            self.registry_cache_misses[registry] = self.registry_cache_misses.get(registry, 0) + 1

    def record_update_found(self) -> None:
        """Record that an update was found."""
        self.updates_found += 1

    def record_error(self) -> None:
        """Record that an error occurred."""
        self.errors += 1

    @property
    def duration_seconds(self) -> float | None:
        """Get total run duration in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def avg_container_latency(self) -> float | None:
        """Get average per-container check latency."""
        if self.container_latencies:
            return sum(self.container_latencies) / len(self.container_latencies)
        return None

    @property
    def max_container_latency(self) -> float | None:
        """Get maximum per-container check latency."""
        if self.container_latencies:
            return max(self.container_latencies)
        return None

    @property
    def cache_hit_rate(self) -> float:
        """Get run-cache hit rate as percentage."""
        total_hits = sum(self.registry_cache_hits.values())
        total_misses = sum(self.registry_cache_misses.values())
        total = total_hits + total_misses
        return (total_hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize metrics to dictionary for storage/logging.

        Returns:
            Dict representation of metrics
        """
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "total_containers": self.total_containers,
            "checked_containers": self.checked_containers,
            "deduplicated_containers": self.deduplicated_containers,
            "unique_images": self.unique_images,
            "updates_found": self.updates_found,
            "errors": self.errors,
            "avg_container_latency": self.avg_container_latency,
            "max_container_latency": self.max_container_latency,
            "cache_hit_rate": self.cache_hit_rate,
            "registry_calls": self.registry_calls,
            "registry_cache_hits": self.registry_cache_hits,
            "registry_cache_misses": self.registry_cache_misses,
        }


class CheckRunContext:
    """Context for a single update check run.

    Provides:
    - Run-scoped tag caching (separate from global 15-min cache)
    - Container deduplication by image signature
    - Metrics collection

    The run-scoped cache differs from the global cache:
    - Global cache: 15-min TTL, keyed by registry:image, persists across runs
    - Run cache: Scoped to single job, keyed by full ImageCheckKey, discarded after run

    Example:
        run_context = CheckRunContext(job_id=123)

        # Group containers for deduplication
        groups = run_context.group_containers(containers)

        for key, group_containers in groups.items():
            # Check run-cache first
            cached = await run_context.get_cached_result(key)
            if cached is None:
                # Fetch from registry and cache
                result = await fetch_tags(...)
                await run_context.set_cached_result(key, result)
            else:
                # Use cached result for all containers in group
                pass

        # Get final metrics
        metrics = run_context.finalize()
    """

    def __init__(self, job_id: int):
        """Initialize check run context.

        Args:
            job_id: ID of the check job this context belongs to
        """
        self.job_id = job_id
        self._tag_cache: dict[ImageCheckKey, TagFetchResult] = {}
        self._lock = asyncio.Lock()
        self.metrics = CheckRunMetrics()

        # Container groups for deduplication
        self._container_groups: dict[ImageCheckKey, list[Container]] = {}
        self._checked_keys: set[ImageCheckKey] = set()

    async def get_cached_result(self, key: ImageCheckKey) -> TagFetchResult | None:
        """Get cached tag fetch result for this run.

        Args:
            key: ImageCheckKey to look up

        Returns:
            Cached TagFetchResult or None if not cached
        """
        async with self._lock:
            return self._tag_cache.get(key)

    async def set_cached_result(self, key: ImageCheckKey, result: TagFetchResult) -> None:
        """Cache tag fetch result for this run.

        Args:
            key: ImageCheckKey to cache
            result: TagFetchResult to store
        """
        async with self._lock:
            self._tag_cache[key] = result

    def group_containers(
        self, containers: list[Container], include_prereleases_lookup: dict[int, bool]
    ) -> dict[ImageCheckKey, list[Container]]:
        """Group containers by image signature for deduplication.

        Containers sharing the same image+tag+scope+prerelease config can
        share a single registry lookup. This method groups them by their
        ImageCheckKey.

        Args:
            containers: List of containers to group
            include_prereleases_lookup: Dict mapping container_id to effective
                include_prereleases setting (container setting or global default)

        Returns:
            Dict mapping ImageCheckKey to list of containers that share
            the same image signature
        """
        groups: dict[ImageCheckKey, list[Container]] = {}

        for container in containers:
            # Access SQLAlchemy attributes (type: ignore for pyright)
            container_id: int = container.id  # type: ignore[attr-defined]
            # Use the pre-resolved lookup (tri-state already resolved in check_job_service)
            include_prereleases = include_prereleases_lookup.get(container_id, False)
            key = ImageCheckKey.from_container(container, include_prereleases)

            if key not in groups:
                groups[key] = []
            groups[key].append(container)

        self._container_groups = groups
        self.metrics.total_containers = len(containers)
        self.metrics.unique_images = len(groups)
        self.metrics.deduplicated_containers = len(containers) - len(groups)

        logger.info(
            f"Job {self.job_id}: Grouped {len(containers)} containers into "
            f"{len(groups)} unique image signatures "
            f"(deduplicated {self.metrics.deduplicated_containers})"
        )

        return groups

    def mark_key_checked(self, key: ImageCheckKey) -> None:
        """Mark an image key as checked (for deduplication tracking).

        Args:
            key: ImageCheckKey that was checked
        """
        self._checked_keys.add(key)

    def is_key_checked(self, key: ImageCheckKey) -> bool:
        """Check if an image key has already been checked.

        Args:
            key: ImageCheckKey to check

        Returns:
            True if already checked, False otherwise
        """
        return key in self._checked_keys

    def get_container_group(self, key: ImageCheckKey) -> list[Container]:
        """Get containers in a group by key.

        Args:
            key: ImageCheckKey for the group

        Returns:
            List of containers in the group, or empty list
        """
        return self._container_groups.get(key, [])

    @property
    def cache_size(self) -> int:
        """Get current number of cached results."""
        return len(self._tag_cache)

    @property
    def groups_count(self) -> int:
        """Get number of container groups."""
        return len(self._container_groups)

    def finalize(self) -> CheckRunMetrics:
        """Finalize the check run and return metrics.

        Call this when the check job completes.

        Returns:
            CheckRunMetrics with final statistics
        """
        self.metrics.completed_at = datetime.now(UTC)

        logger.info(
            f"Job {self.job_id} metrics: "
            f"duration={self.metrics.duration_seconds:.1f}s, "
            f"containers={self.metrics.checked_containers}/{self.metrics.total_containers}, "
            f"deduplicated={self.metrics.deduplicated_containers}, "
            f"updates={self.metrics.updates_found}, "
            f"errors={self.metrics.errors}, "
            f"cache_hit_rate={self.metrics.cache_hit_rate:.1f}%"
        )

        return self.metrics
