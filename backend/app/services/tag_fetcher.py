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
from app.services.registry_client import RegistryClientFactory, is_non_semver_tag
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
        version_track: Versioning scheme override (None=auto, "semver", "calver")
        stable_anchor_major: Phase 5 anchor bound; candidates with a higher
            major are rejected. ``None`` disables the bound.
    """

    registry: str
    image: str
    current_tag: str
    scope: str
    include_prereleases: bool
    current_digest: str | None = None
    version_track: str | None = None
    stable_anchor_major: int | None = None
    # Phase 2 (D10): when True, resolve `:latest` lineage and expose
    # ``latest_lineage_major`` on the response so the decision maker can
    # reject candidates with major > cap. Default True (cap is opt-out per
    # container).
    latest_lineage_cap_enabled: bool = True


@dataclass
class FetchTagsResponse:
    """Response from tag fetching operation.

    Attributes:
        latest_tag: Latest tag within scope (None if no update)
        latest_major_tag: Latest major version (for scope violation visibility)
        calver_blocked_tag: Best CalVer candidate blocked for SemVer container (UI badge)
        all_tags: All available tags for the image
        metadata: Additional metadata (e.g., digest for 'latest' tag)
        cache_hit: Whether result came from run-scoped cache
        fetch_duration_ms: Time taken to fetch (including rate limit waits)
        error: Error message if fetch failed
        anchor_decision: Phase 5/6 stable-channel anchor state machine result
            for the per-container fetch path. ``None`` for the cache-hit
            and key-only paths where no anchor resolution was attempted.
    """

    latest_tag: str | None
    latest_major_tag: str | None
    all_tags: list[str]
    metadata: dict[str, Any] | None
    cache_hit: bool
    fetch_duration_ms: float
    calver_blocked_tag: str | None = None
    error: str | None = None
    anchor_decision: Any | None = None  # AnchorDecision; Any to avoid import cycle
    # Resolved upstream major of the *current* (mutable) tag's digest. Used
    # by the decision maker to detect cross-major drift on digest-tracked
    # containers (Phase 6.2). ``None`` if the tag is semver, the registry
    # client does not expose labels, or label resolution failed.
    current_tag_major: int | None = None
    # Phase 1 (continuity check): union of majors successfully parsed from
    # the candidate set across all pages scanned. Empty when the client did
    # not enumerate candidates (e.g. pure digest tracking path).
    candidate_majors_seen: set[int] | None = None
    # Phase 2 (`:latest` lineage cap): upstream major of ``:latest``'s digest
    # or its OCI image.version label. ``None`` if unavailable. The decision
    # maker rejects any candidate whose major exceeds this cap (unless the
    # container has opted out).
    latest_lineage_major: int | None = None
    latest_lineage_method: str | None = None  # "label", "digest_walk", "unresolved"
    # Phase 3 (stale-tag heuristic): when each was last pushed/built.
    latest_tag_pushed_at: Any | None = None  # datetime or None
    current_tag_pushed_at: Any | None = None  # datetime or None


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

        # Build cache key. Every field that influences the registry call's
        # outcome must be part of the key — otherwise a cached response from
        # one anchor/digest group can leak to another. The dedupe layer
        # (check_run_context.ImageCheckKey.from_container) already partitions
        # groups by these fields; the inline key must mirror that.
        key = ImageCheckKey(
            registry=request.registry.lower(),
            image=request.image,
            current_tag=request.current_tag,
            scope=request.scope,
            include_prereleases=request.include_prereleases,
            version_track=request.version_track,
            # Phase 5/6 — these affect the registry-result selection
            # (stable_anchor_major bounds _compare_versions; the others
            # change channel_shift classification in the decision maker
            # that reads this cached response).
            stable_anchor_tag=None,  # request does not carry the tag itself
            accepted_anchor_major=request.stable_anchor_major,
            last_digest_major=None,  # carried via current_tag_major on response
        )

        # Check run-scoped cache first
        if self._run_context:
            cached = await self._run_context.get_cached_result(key)
            if cached:
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.debug(
                    f"Run-cache hit for {request.image}:{request.current_tag} ({duration_ms:.1f}ms)"
                )
                return FetchTagsResponse(
                    latest_tag=cached.latest_tag,
                    latest_major_tag=cached.latest_major_tag,
                    calver_blocked_tag=cached.calver_blocked_tag,
                    all_tags=cached.tags,
                    metadata=cached.metadata,
                    cache_hit=True,
                    fetch_duration_ms=duration_ms,
                    current_tag_major=cached.current_tag_major,
                )

        # Fetch from registry with rate limiting
        response: FetchTagsResponse | None = None
        try:
            async with RateLimitedRequest(self._rate_limiter, request.registry):
                client = await RegistryClientFactory.get_client(request.registry, self._db)

                try:
                    is_non_semver = is_non_semver_tag(request.current_tag)

                    # For registries that use TagCache (GHCR/LSCR/GCR/Quay),
                    # pre-populate cache so get_latest_tag and get_latest_major_tag
                    # avoid redundant API calls. Skip for Docker Hub (uses its own
                    # optimized paginated fetch) and non-semver tags (only need digest).
                    all_tags: list[str] = []
                    if client.uses_tag_cache_for_latest and not is_non_semver:
                        all_tags = await client.get_all_tags(request.image)

                    # Fetch latest tag within scope
                    latest_tag = await client.get_latest_tag(
                        request.image,
                        request.current_tag,
                        request.scope,
                        current_digest=request.current_digest,
                        include_prereleases=request.include_prereleases,
                        version_track=request.version_track,
                        stable_anchor_major=request.stable_anchor_major,
                    )

                    # Fetch latest major tag (for scope violation visibility)
                    latest_major_tag = None
                    if request.scope != "major":
                        try:
                            latest_major_tag = await client.get_latest_major_tag(
                                request.image,
                                request.current_tag,
                                include_prereleases=request.include_prereleases,
                                version_track=request.version_track,
                                stable_anchor_major=request.stable_anchor_major,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to fetch major tag for {request.image}: {e}")

                    # Phase 7 (D15): drop the unconditional Docker Hub
                    # ``get_all_tags`` re-fetch. The semver path already
                    # scanned the first 5 pages and ``all_tags`` is only used
                    # by the UI tag dropdown (which now lazy-fetches on
                    # demand) and the non-semver digest path (handled
                    # below). Re-paginating thousands of tags for
                    # linuxserver/* / plex burned Docker Hub quota for no
                    # downstream benefit.
                    # For non-DockerHub registries, all_tags was already
                    # populated above via the TagCache pre-population path.
                    if not all_tags and not is_non_semver and client.uses_tag_cache_for_latest:
                        all_tags = await client.get_all_tags(request.image)

                    # Get metadata for non-semver tags (digest tracking)
                    metadata = None
                    current_tag_major: int | None = None
                    if is_non_semver:
                        try:
                            metadata = await client.get_tag_metadata(
                                request.image, request.current_tag
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch metadata for "
                                f"{request.image}:{request.current_tag}: {e}"
                            )
                        # Phase 6.2: resolve the upstream major of the
                        # current mutable tag so the decision maker can
                        # detect cross-major drift on digest-tracked
                        # containers. Best-effort — registries without a
                        # ``get_image_labels`` override return None and the
                        # decision maker falls back to the legacy "digest"
                        # update_kind.
                        try:
                            from app.services.channel_anchor import resolve_anchor_major

                            current_anchor = await resolve_anchor_major(
                                client, request.image, request.current_tag
                            )
                            if current_anchor is not None:
                                current_tag_major = current_anchor.anchor_major
                        except Exception as e:  # noqa: BLE001
                            logger.debug(
                                "Could not resolve current_tag major for %s:%s — %s",
                                request.image,
                                request.current_tag,
                                e,
                            )

                    duration_ms = (time.monotonic() - start_time) * 1000

                    # Collect cross-scheme rejection for UI visibility (one summary log per check)
                    calver_blocked_tag = getattr(client, "_best_cross_scheme_rejected", None)
                    if calver_blocked_tag:
                        logger.info(
                            "Cross-scheme candidate blocked for %s:%s — best rejected: %s "
                            "[reason=track_mismatch]",
                            request.image,
                            request.current_tag,
                            calver_blocked_tag,
                        )

                    # Phase 1 (D9): expose candidate majors observed by the
                    # client so callers / tests can audit continuity decisions.
                    candidate_majors_seen = (
                        set(getattr(client, "_last_candidate_majors_seen", set())) or None
                    )

                    # Phase 2 (D10): resolve `:latest` lineage cap. Default-on
                    # for every container unless the caller explicitly opted
                    # out. Best-effort — registries with no `:latest` tag or
                    # no label/digest support return None and the cap is a
                    # no-op for the decision maker.
                    latest_lineage_major: int | None = None
                    latest_lineage_method: str | None = None
                    if request.latest_lineage_cap_enabled and not is_non_semver:
                        try:
                            from app.services.latest_lineage_resolver import (
                                LatestLineageResolver,
                            )

                            resolver = LatestLineageResolver(client)
                            res = await resolver.resolve(request.image, current_best=latest_tag)
                            if res is not None:
                                latest_lineage_major = res.major
                                latest_lineage_method = res.method
                            else:
                                latest_lineage_method = "unresolved"
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(
                                "latest_lineage_resolver failed for %s: %s",
                                request.image,
                                exc,
                            )
                            latest_lineage_method = "unresolved"

                    # Phase 3 (D11): collect pushed-at timestamps for the
                    # stale-tag heuristic. Best-effort — clients that can't
                    # expose this return None.
                    latest_pushed = None
                    current_pushed = None
                    if latest_tag and not is_non_semver:
                        try:
                            latest_pushed = await self._fetch_pushed_at(
                                client, request.image, latest_tag
                            )
                            current_pushed = await self._fetch_pushed_at(
                                client, request.image, request.current_tag
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("pushed_at fetch failed for %s: %s", request.image, exc)

                    # Create result
                    result = TagFetchResult(
                        tags=all_tags,
                        latest_tag=latest_tag,
                        latest_major_tag=latest_major_tag,
                        calver_blocked_tag=calver_blocked_tag,
                        metadata=metadata,
                        current_tag_major=current_tag_major,
                    )

                    # Cache in run context
                    if self._run_context:
                        await self._run_context.set_cached_result(key, result)

                    logger.debug(
                        f"Fetched tags for {request.image}:{request.current_tag} "
                        f"-> latest={latest_tag} ({duration_ms:.1f}ms)"
                    )

                    response = FetchTagsResponse(
                        latest_tag=latest_tag,
                        latest_major_tag=latest_major_tag,
                        calver_blocked_tag=calver_blocked_tag,
                        all_tags=all_tags,
                        metadata=metadata,
                        cache_hit=False,
                        fetch_duration_ms=duration_ms,
                        current_tag_major=current_tag_major,
                        candidate_majors_seen=candidate_majors_seen,
                        latest_lineage_major=latest_lineage_major,
                        latest_lineage_method=latest_lineage_method,
                        latest_tag_pushed_at=latest_pushed,
                        current_tag_pushed_at=current_pushed,
                    )

                finally:
                    await client.close()

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"Error fetching tags for {request.image}:{request.current_tag}: {e}")
            response = FetchTagsResponse(
                latest_tag=None,
                latest_major_tag=None,
                all_tags=[],
                metadata=None,
                cache_hit=False,
                fetch_duration_ms=duration_ms,
                error=str(e),
            )

        if response is None:
            raise RuntimeError(
                f"Tag fetch for {request.image}:{request.current_tag} "
                "completed without producing a response"
            )
        return response

    async def fetch_tags_for_container(self, container: Container) -> FetchTagsResponse:
        """Convenience method to fetch tags for a container.

        Automatically resolves the effective include_prereleases setting
        (container-specific or global default) and, for opt-in containers,
        resolves a stable-channel anchor major via the Phase 5.4 state
        machine (``channel_anchor.decide_anchor_bound``).

        Args:
            container: Container to fetch tags for

        Returns:
            FetchTagsResponse with tags and metadata
        """
        # Get effective include_prereleases setting (tri-state)
        # None=inherit global, True=force include, False=force stable only
        container_prereleases: bool | None = container.include_prereleases  # type: ignore[attr-defined]
        if container_prereleases is not None:
            include_prereleases: bool = container_prereleases
        else:
            include_prereleases = await SettingsService.get_bool(
                self._db, "include_prereleases", default=False
            )

        # Build request from container attributes
        registry: str = str(container.registry)  # type: ignore[attr-defined]
        image: str = str(container.image)  # type: ignore[attr-defined]
        current_tag: str = str(container.current_tag)  # type: ignore[attr-defined]
        scope: str = str(container.scope)  # type: ignore[attr-defined]
        current_digest: str | None = (
            container.current_digest if is_non_semver_tag(current_tag) else None
        )  # type: ignore[attr-defined]
        version_track: str | None = container.version_track if container.version_track else None  # type: ignore[attr-defined]

        # Phase 5: resolve stable-channel anchor if the user has opted in.
        # The bound returned by ``decide_anchor_bound`` enforces the
        # accepted upstream major; fresh upward drift is reported via the
        # AnchorDecision so the decision-maker can surface it as a
        # channel_shift update kind rather than a normal upgrade.
        anchor_decision = await self._resolve_anchor_decision(container)
        stable_anchor_major = (
            anchor_decision.upper_major_bound if anchor_decision is not None else None
        )

        response = await self.fetch_tags(
            FetchTagsRequest(
                registry=registry,
                image=image,
                current_tag=current_tag,
                scope=scope,
                include_prereleases=include_prereleases,
                current_digest=current_digest,
                version_track=version_track,
                stable_anchor_major=stable_anchor_major,
            )
        )
        # Attach the anchor decision so downstream callers can detect drift
        # and classify the update as channel_shift when appropriate.
        if anchor_decision is not None:
            response.anchor_decision = anchor_decision
        return response

    async def _resolve_anchor_decision(self, container: Container):
        """Resolve the full Phase 5.4 anchor decision for a container.

        Returns ``None`` when the feature is disabled. Otherwise returns an
        ``AnchorDecision`` whose ``upper_major_bound`` is the active enforcement
        bound and whose ``channel_shift`` flag tells the decision-maker
        whether fresh anchor drift should be surfaced as a separate update
        kind (Phase 6).
        """
        anchor_tag: str | None = container.stable_anchor_tag  # type: ignore[attr-defined]
        accepted: int | None = container.accepted_anchor_major  # type: ignore[attr-defined]
        if anchor_tag is None and accepted is None:
            return None

        # Local imports keep this module's import graph light when the
        # anchor feature is unused.
        from app.services.channel_anchor import (
            AnchorResolution,
            decide_anchor_bound,
            get_anchor_cache,
            resolve_anchor_major,
        )
        from app.services.registry_client import RegistryClientFactory

        registry: str = str(container.registry)  # type: ignore[attr-defined]
        image: str = str(container.image)  # type: ignore[attr-defined]
        fresh: AnchorResolution | None = None

        if anchor_tag:
            cache = get_anchor_cache()
            cached = cache.get(registry, image, anchor_tag)
            if cached is not None:
                fresh = cached
            else:
                client = await RegistryClientFactory.get_client(registry, self._db)
                try:
                    fresh = await resolve_anchor_major(client, image, anchor_tag)
                    if fresh is not None:
                        cache.set(registry, image, anchor_tag, fresh)
                finally:
                    await client.close()

        decision = decide_anchor_bound(accepted_anchor_major=accepted, fresh=fresh)

        # First-resolution baseline persistence (codex finding #2):
        # When the user has opted in but no accepted_anchor_major is on the
        # row yet, the first successful resolution must be written back to
        # the container row. Otherwise `decide_anchor_bound(None, fresh)`
        # silently treats every subsequent fresh major as a non-shift
        # baseline, defeating the channel_shift mechanism. We persist via a
        # targeted UPDATE rather than relying on the existing session
        # because the container row was loaded by a different
        # session/transaction in the check job worker.
        if accepted is None and fresh is not None and decision.upper_major_bound is not None:
            try:
                from sqlalchemy import update as sa_update

                from app.models.container import Container as ContainerModel

                container_id: int = container.id  # type: ignore[attr-defined]
                await self._db.execute(
                    sa_update(ContainerModel)
                    .where(ContainerModel.id == container_id)
                    .values(accepted_anchor_major=fresh.anchor_major)
                )
                # Reflect the new value on the in-memory row so any
                # subsequent decision in this same request sees it.
                container.accepted_anchor_major = fresh.anchor_major  # type: ignore[assignment]
                logger.info(
                    "Anchor baseline persisted for container %d (image=%s, anchor=%s, major=%d)",
                    container_id,
                    image,
                    anchor_tag,
                    fresh.anchor_major,
                )
            except Exception as exc:  # noqa: BLE001 — never crash the check on persistence
                logger.warning(
                    "Failed to persist initial anchor baseline for container %s:%s — %s",
                    image,
                    anchor_tag,
                    exc,
                )

        return decision

    async def _fetch_pushed_at(self, client, image: str, tag: str):
        """Phase 3 (D11): best-effort fetch of a tag's pushed/built timestamp.

        For DockerHub, this comes from ``last_updated`` in the tag metadata
        endpoint. For OCI registries the value comes from the image config
        blob's ``org.opencontainers.image.created`` label (resolved via
        ``get_image_labels``). Returns None when the registry exposes neither.
        """
        from datetime import datetime as _dt

        # DockerHub-style metadata exposes last_updated directly.
        try:
            meta = await client.get_tag_metadata(image, tag)
        except Exception:  # noqa: BLE001
            meta = None
        if isinstance(meta, dict):
            last_updated = meta.get("last_updated")
            if isinstance(last_updated, str):
                try:
                    return _dt.fromisoformat(last_updated.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if isinstance(last_updated, _dt):
                return last_updated

        # OCI / label fallback.
        try:
            label_result = await client.get_image_labels(image, tag)
        except Exception:  # noqa: BLE001
            label_result = None
        if isinstance(label_result, tuple) and label_result:
            labels = label_result[0] if label_result else {}
            if isinstance(labels, dict):
                created = labels.get("org.opencontainers.image.created") or labels.get(
                    "org.label-schema.build-date"
                )
                if isinstance(created, str):
                    try:
                        return _dt.fromisoformat(created.replace("Z", "+00:00"))
                    except ValueError:
                        return None
        return None

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
                version_track=key.version_track,
            )
        )
