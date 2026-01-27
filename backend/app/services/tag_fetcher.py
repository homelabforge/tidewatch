"""Tag fetcher service - separates registry fetching from update decisions.

This module extracts the registry tag fetching logic from the update checker,
enabling clean caching boundaries and rate limiting integration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.check_run_context import (
    CheckRunContext,
    ImageCheckKey,
    TagFetchResult,
)
from app.services.registry_client import RegistryClientFactory
from app.services.registry_rate_limiter import RateLimitedRequest, RegistryRateLimiter
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.models.container import Container

logger = logging.getLogger(__name__)


@dataclass
class FetchTagsRequest:
    """Request to fetch tags for an image.

    Attributes:
        registry: Registry name (e.g., "dockerhub", "ghcr")
        image: Image name (e.g., "postgres", "linuxserver/plex")
        current_tag: Current tag to compare against
        scope: Update scope ("patch", "minor", "major")
        include_prereleases: Whether to include prerelease tags
        current_digest: Current digest for 'latest' tag tracking
    """

    registry: str
    image: str
    current_tag: str
    scope: str
    include_prereleases: bool
    current_digest: str | None = None


@dataclass
class FetchTagsResponse:
    """Response from tag fetching operation.

    Attributes:
        latest_tag: Latest tag within scope (None if no update)
        latest_major_tag: Latest major version (for scope violation visibility)
        all_tags: All available tags for the image
        metadata: Additional metadata (e.g., digest for 'latest' tag)
        cache_hit: Whether result came from run-scoped cache
        fetch_duration_ms: Time taken to fetch (including rate limit waits)
        error: Error message if fetch failed
    """

    latest_tag: str | None
    latest_major_tag: str | None
    all_tags: list[str]
    metadata: dict[str, Any] | None
    cache_hit: bool
    fetch_duration_ms: float
    error: str | None = None


class TagFetcher:
    """Service for fetching tags from container registries.

    Responsibilities:
    - Fetch tags from registries with rate limiting
    - Use run-scoped caching (via CheckRunContext)
    - Handle errors gracefully
    - Record metrics

    Does NOT:
    - Make update decisions
    - Modify database records
    - Send notifications

    Example:
        rate_limiter = RegistryRateLimiter()
        run_context = CheckRunContext(job_id=123)
        fetcher = TagFetcher(db, rate_limiter, run_context)

        response = await fetcher.fetch_tags(FetchTagsRequest(
            registry="dockerhub",
            image="postgres",
            current_tag="15.0",
            scope="patch",
            include_prereleases=False,
        ))

        if response.error:
            # Handle error
            pass
        elif response.latest_tag:
            # Update available
            pass
    """

    def __init__(
        self,
        db: AsyncSession,
        rate_limiter: RegistryRateLimiter,
        run_context: CheckRunContext | None = None,
    ):
        """Initialize tag fetcher.

        Args:
            db: Database session for registry client credentials
            rate_limiter: Rate limiter for registry API calls
            run_context: Optional run context for caching (if None, no caching)
        """
        self._db = db
        self._rate_limiter = rate_limiter
        self._run_context = run_context

    async def fetch_tags(self, request: FetchTagsRequest) -> FetchTagsResponse:
        """Fetch tags for an image with caching and rate limiting.

        Flow:
        1. Check run-scoped cache (if run_context provided)
        2. If cache miss: acquire rate limit, call registry, cache result
        3. Return response with cache_hit flag and timing

        Args:
            request: Tag fetch request

        Returns:
            FetchTagsResponse with tags and metadata
        """
        start_time = time.monotonic()

        # Build cache key
        key = ImageCheckKey(
            registry=request.registry.lower(),
            image=request.image,
            current_tag=request.current_tag,
            scope=request.scope,
            include_prereleases=request.include_prereleases,
        )

        # Check run-scoped cache first
        if self._run_context:
            cached = await self._run_context.get_cached_result(key)
            if cached:
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.debug(
                    f"Run-cache hit for {request.image}:{request.current_tag} "
                    f"({duration_ms:.1f}ms)"
                )
                return FetchTagsResponse(
                    latest_tag=cached.latest_tag,
                    latest_major_tag=cached.latest_major_tag,
                    all_tags=cached.tags,
                    metadata=cached.metadata,
                    cache_hit=True,
                    fetch_duration_ms=duration_ms,
                )

        # Fetch from registry with rate limiting
        try:
            async with RateLimitedRequest(self._rate_limiter, request.registry):
                client = await RegistryClientFactory.get_client(
                    request.registry, self._db
                )

                try:
                    # Fetch latest tag within scope
                    latest_tag = await client.get_latest_tag(
                        request.image,
                        request.current_tag,
                        request.scope,
                        current_digest=request.current_digest,
                        include_prereleases=request.include_prereleases,
                    )

                    # Fetch latest major tag (for scope violation visibility)
                    latest_major_tag = None
                    if request.scope != "major":
                        try:
                            latest_major_tag = await client.get_latest_major_tag(
                                request.image,
                                request.current_tag,
                                include_prereleases=request.include_prereleases,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch major tag for {request.image}: {e}"
                            )

                    # Get all tags (may be cached in global 15-min cache)
                    all_tags = await client.get_all_tags(request.image)

                    # Get metadata for 'latest' tag (digest tracking)
                    metadata = None
                    if request.current_tag == "latest":
                        try:
                            metadata = await client.get_tag_metadata(
                                request.image, "latest"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch metadata for {request.image}:latest: {e}"
                            )

                    duration_ms = (time.monotonic() - start_time) * 1000

                    # Create result
                    result = TagFetchResult(
                        tags=all_tags,
                        latest_tag=latest_tag,
                        latest_major_tag=latest_major_tag,
                        metadata=metadata,
                    )

                    # Cache in run context
                    if self._run_context:
                        await self._run_context.set_cached_result(key, result)

                    logger.debug(
                        f"Fetched tags for {request.image}:{request.current_tag} "
                        f"-> latest={latest_tag} ({duration_ms:.1f}ms)"
                    )

                    return FetchTagsResponse(
                        latest_tag=latest_tag,
                        latest_major_tag=latest_major_tag,
                        all_tags=all_tags,
                        metadata=metadata,
                        cache_hit=False,
                        fetch_duration_ms=duration_ms,
                    )

                finally:
                    await client.close()

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                f"Error fetching tags for {request.image}:{request.current_tag}: {e}"
            )
            return FetchTagsResponse(
                latest_tag=None,
                latest_major_tag=None,
                all_tags=[],
                metadata=None,
                cache_hit=False,
                fetch_duration_ms=duration_ms,
                error=str(e),
            )

    async def fetch_tags_for_container(
        self, container: Container
    ) -> FetchTagsResponse:
        """Convenience method to fetch tags for a container.

        Automatically resolves the effective include_prereleases setting
        (container-specific or global default).

        Args:
            container: Container to fetch tags for

        Returns:
            FetchTagsResponse with tags and metadata
        """
        # Get effective include_prereleases setting
        # Container setting takes precedence, fall back to global
        include_prereleases: bool = container.include_prereleases or False  # type: ignore[attr-defined]
        if not include_prereleases:
            global_include_prereleases = await SettingsService.get_bool(
                self._db, "include_prereleases", default=False
            )
            include_prereleases = global_include_prereleases

        # Build request from container attributes
        registry: str = str(container.registry)  # type: ignore[attr-defined]
        image: str = str(container.image)  # type: ignore[attr-defined]
        current_tag: str = str(container.current_tag)  # type: ignore[attr-defined]
        scope: str = str(container.scope)  # type: ignore[attr-defined]
        current_digest: str | None = (
            container.current_digest if current_tag == "latest" else None
        )  # type: ignore[attr-defined]

        return await self.fetch_tags(
            FetchTagsRequest(
                registry=registry,
                image=image,
                current_tag=current_tag,
                scope=scope,
                include_prereleases=include_prereleases,
                current_digest=current_digest,
            )
        )

    async def fetch_tags_for_key(
        self, key: ImageCheckKey, current_digest: str | None = None
    ) -> FetchTagsResponse:
        """Fetch tags for an ImageCheckKey.

        Useful when processing deduplicated container groups.

        Args:
            key: ImageCheckKey specifying the image signature
            current_digest: Current digest for 'latest' tag tracking

        Returns:
            FetchTagsResponse with tags and metadata
        """
        return await self.fetch_tags(
            FetchTagsRequest(
                registry=key.registry,
                image=key.image,
                current_tag=key.current_tag,
                scope=key.scope,
                include_prereleases=key.include_prereleases,
                current_digest=current_digest,
            )
        )
