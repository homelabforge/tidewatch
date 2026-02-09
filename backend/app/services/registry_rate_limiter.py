"""Per-registry rate limiting for TideWatch update checks.

Provides bounded concurrency and sliding window rate limiting per container
registry to avoid throttling from Docker Hub, GHCR, LSCR, etc.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RegistryType(Enum):
    """Supported container registries."""

    DOCKERHUB = "dockerhub"
    GHCR = "ghcr"
    LSCR = "lscr"
    GCR = "gcr"
    QUAY = "quay"


@dataclass
class RegistryRateLimits:
    """Rate limit configuration per registry.

    Attributes:
        requests_per_minute: Maximum requests per minute (sliding window)
        concurrent_limit: Maximum concurrent requests
        burst_limit: Initial burst allowance before rate limiting kicks in
    """

    requests_per_minute: int
    concurrent_limit: int
    burst_limit: int = 10


# Documented rate limits per registry (conservative estimates)
REGISTRY_RATE_LIMITS: dict[RegistryType, RegistryRateLimits] = {
    # Docker Hub: 100 pulls/6 hours unauthenticated, 200/6 hours authenticated
    # Authenticated = 200 req/6 hrs = ~33 req/hr = 0.55 req/min
    # Being VERY conservative to avoid 429 errors during full checks:
    # - 3 req/min = 180 req/hr (stays well under 6-hour quota if checks run hourly)
    # - Low concurrent limit to avoid burst exhaustion
    RegistryType.DOCKERHUB: RegistryRateLimits(
        requests_per_minute=3,
        concurrent_limit=2,
        burst_limit=5,
    ),
    # GHCR: 60 req/hour unauthenticated, 5000/hour authenticated
    # With auth: ~80 req/min safe; being conservative at 60
    RegistryType.GHCR: RegistryRateLimits(
        requests_per_minute=60,
        concurrent_limit=10,
        burst_limit=15,
    ),
    # LSCR: Uses GHCR backend, similar limits
    RegistryType.LSCR: RegistryRateLimits(
        requests_per_minute=60,
        concurrent_limit=10,
        burst_limit=15,
    ),
    # GCR: Generally permissive, but be conservative
    RegistryType.GCR: RegistryRateLimits(
        requests_per_minute=60,
        concurrent_limit=10,
        burst_limit=15,
    ),
    # Quay: Generally permissive
    RegistryType.QUAY: RegistryRateLimits(
        requests_per_minute=60,
        concurrent_limit=10,
        burst_limit=15,
    ),
}

# Default limits for unknown registries (conservative to avoid rate limiting)
DEFAULT_RATE_LIMITS = RegistryRateLimits(
    requests_per_minute=5,
    concurrent_limit=3,
    burst_limit=5,
)


@dataclass
class RateLimitState:
    """Track rate limit state for a registry.

    Attributes:
        semaphore: Asyncio semaphore for concurrent request limiting
        request_times: List of request timestamps in the sliding window
        lock: Asyncio lock for thread-safe state updates
    """

    semaphore: asyncio.Semaphore
    request_times: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RegistryRateLimiter:
    """Manages rate limiting across all registries.

    Provides:
    - Global concurrency limit across all registries
    - Per-registry concurrency limits
    - Per-registry sliding window rate limiting

    Example:
        limiter = RegistryRateLimiter(global_concurrency=5)
        async with RateLimitedRequest(limiter, "dockerhub"):
            # Make registry API call
            pass
    """

    def __init__(self, global_concurrency: int = 5):
        """Initialize rate limiter.

        Args:
            global_concurrency: Maximum concurrent requests across all registries
        """
        self._global_semaphore = asyncio.Semaphore(global_concurrency)
        self._registry_states: dict[str, RateLimitState] = {}
        self._lock = asyncio.Lock()

        # Metrics tracking
        self._wait_count: dict[str, int] = {}
        self._total_requests: dict[str, int] = {}

    async def _get_registry_state(self, registry: str) -> RateLimitState:
        """Get or create rate limit state for a registry.

        Args:
            registry: Registry name (e.g., "dockerhub", "ghcr")

        Returns:
            RateLimitState for the registry
        """
        normalized = self._normalize_registry_name(registry)
        async with self._lock:
            if normalized not in self._registry_states:
                registry_type = self._get_registry_type(registry)
                limits = REGISTRY_RATE_LIMITS.get(registry_type, DEFAULT_RATE_LIMITS)
                self._registry_states[normalized] = RateLimitState(
                    semaphore=asyncio.Semaphore(limits.concurrent_limit)
                )
                logger.debug(
                    f"Created rate limit state for {normalized}: "
                    f"{limits.requests_per_minute} req/min, "
                    f"{limits.concurrent_limit} concurrent"
                )
            return self._registry_states[normalized]

    def _normalize_registry_name(self, registry: str) -> str:
        """Normalize registry name for consistent key lookup.

        Args:
            registry: Registry name or hostname

        Returns:
            Normalized lowercase registry name
        """
        registry_lower = registry.lower().strip()

        # Map hostnames to registry names
        hostname_map = {
            "docker.io": "dockerhub",
            "registry.hub.docker.com": "dockerhub",
            "ghcr.io": "ghcr",
            "lscr.io": "lscr",
            "gcr.io": "gcr",
            "quay.io": "quay",
        }

        return hostname_map.get(registry_lower, registry_lower)

    def _get_registry_type(self, registry: str) -> RegistryType:
        """Get RegistryType enum from registry name.

        Args:
            registry: Registry name or hostname

        Returns:
            RegistryType enum value
        """
        normalized = self._normalize_registry_name(registry)

        type_map = {
            "dockerhub": RegistryType.DOCKERHUB,
            "docker.io": RegistryType.DOCKERHUB,
            "ghcr": RegistryType.GHCR,
            "lscr": RegistryType.LSCR,
            "gcr": RegistryType.GCR,
            "quay": RegistryType.QUAY,
        }

        return type_map.get(normalized, RegistryType.DOCKERHUB)

    async def acquire(self, registry: str) -> float:
        """Acquire rate limit slot for registry request.

        Blocks until both global and per-registry limits allow the request.
        Implements sliding window rate limiting within the per-registry limit.

        The rate-limit window is checked BEFORE acquiring semaphores so that
        sleeping on a throttled registry (e.g. Docker Hub) does not hold a
        global semaphore slot and starve requests to other registries.

        Args:
            registry: Registry name

        Returns:
            Wait time in seconds (0 if no wait was needed)
        """
        start_time = time.monotonic()
        state = await self._get_registry_state(registry)
        registry_type = self._get_registry_type(registry)
        limits = REGISTRY_RATE_LIMITS.get(registry_type, DEFAULT_RATE_LIMITS)
        normalized = self._normalize_registry_name(registry)

        # Track total requests
        self._total_requests[normalized] = self._total_requests.get(normalized, 0) + 1

        total_wait = 0.0

        # Phase 1: Wait for rate-limit window BEFORE acquiring semaphores.
        # This ensures no global/per-registry slots are held during sleep.
        while True:
            async with state.lock:
                now = time.monotonic()
                window_start = now - 60  # 1 minute window
                state.request_times = [t for t in state.request_times if t > window_start]

                if len(state.request_times) < limits.requests_per_minute:
                    break  # Within window, proceed to acquire semaphores

                # Calculate how long to wait until oldest request exits the window
                oldest = min(state.request_times)
                wait_needed = (oldest + 60) - now

            # Sleep WITHOUT holding any locks or semaphores
            if wait_needed > 0:
                logger.debug(
                    f"Rate limiting {normalized}: waiting {wait_needed:.2f}s "
                    f"({len(state.request_times)} requests in window)"
                )
                self._wait_count[normalized] = self._wait_count.get(normalized, 0) + 1
                await asyncio.sleep(wait_needed)
                total_wait += wait_needed

        # Phase 2: Acquire both semaphores now that rate limit is clear
        await self._global_semaphore.acquire()
        await state.semaphore.acquire()

        # Phase 3: Re-check window under lock after acquiring semaphores.
        # Another task may have consumed the window during our acquire wait.
        while True:
            async with state.lock:
                now = time.monotonic()
                window_start = now - 60
                state.request_times = [t for t in state.request_times if t > window_start]

                if len(state.request_times) < limits.requests_per_minute:
                    # Window is clear — record this request and proceed
                    state.request_times.append(time.monotonic())
                    break

                # Window exceeded after acquiring (race condition) — must retry
                oldest = min(state.request_times)
                wait_needed = (oldest + 60) - now

            # Release both semaphores before sleeping to avoid starvation
            state.semaphore.release()
            self._global_semaphore.release()

            if wait_needed > 0:
                logger.debug(f"Rate limit race for {normalized}: re-waiting {wait_needed:.2f}s")
                await asyncio.sleep(wait_needed)
                total_wait += wait_needed

            # Re-acquire semaphores for next attempt
            await self._global_semaphore.acquire()
            await state.semaphore.acquire()

        elapsed = time.monotonic() - start_time
        if elapsed > 0.1:
            logger.debug(f"Acquired rate limit for {normalized} in {elapsed:.2f}s")

        return total_wait

    async def release(self, registry: str) -> None:
        """Release rate limit slot.

        Args:
            registry: Registry name
        """
        state = await self._get_registry_state(registry)
        state.semaphore.release()
        self._global_semaphore.release()

    def get_metrics(self) -> dict[str, dict[str, int]]:
        """Get rate limiter metrics.

        Returns:
            Dict with per-registry metrics:
            - total_requests: Total requests made
            - wait_count: Number of times rate limiting caused a wait
        """
        return {
            registry: {
                "total_requests": self._total_requests.get(registry, 0),
                "wait_count": self._wait_count.get(registry, 0),
            }
            for registry in set(self._total_requests.keys()) | set(self._wait_count.keys())
        }

    def reset_metrics(self) -> None:
        """Reset rate limiter metrics (typically at start of new check run)."""
        self._wait_count.clear()
        self._total_requests.clear()


class RateLimitedRequest:
    """Async context manager for rate-limited registry requests.

    Example:
        limiter = RegistryRateLimiter()
        async with RateLimitedRequest(limiter, "dockerhub") as ctx:
            # Make registry API call
            result = await client.get_tags()
        print(f"Wait time: {ctx.wait_time}s")
    """

    def __init__(self, limiter: RegistryRateLimiter, registry: str):
        """Initialize rate-limited request context.

        Args:
            limiter: RegistryRateLimiter instance
            registry: Registry name
        """
        self._limiter = limiter
        self._registry = registry
        self.wait_time: float = 0.0

    async def __aenter__(self) -> "RateLimitedRequest":
        """Acquire rate limit slot."""
        self.wait_time = await self._limiter.acquire(self._registry)
        return self

    async def __aexit__(
        self,
        _exc_type: type | None,
        _exc_val: BaseException | None,
        _exc_tb: object | None,
    ) -> bool:
        """Release rate limit slot."""
        await self._limiter.release(self._registry)
        return False
