"""Supply chain anomaly detection analyzer.

Provides image-level enrichment (size anomaly) and per-container
hard holds (release corroboration). Also provides the digest
immutability gate used at apply time.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.release_corroboration_cache import ReleaseCorroborationCache
from app.models.supply_chain_baseline import SupplyChainBaseline
from app.services.registry_client import RegistryClientFactory
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class DigestMutationError(Exception):
    """Tag digest changed between detection and apply — integrity violation."""


class ReleaseStatus(Enum):
    """Result of checking whether a GitHub release exists for a tag."""

    EXISTS = "exists"
    MISSING = "missing"
    NO_SOURCE = "no_source"
    ERROR = "error"


@dataclass
class AnomalySignal:
    """A single anomaly detection signal."""

    name: str
    score: int
    detail: str
    tier: str  # "hard_hold" or "enrichment"


@dataclass
class ImageAnalysisResult:
    """Image-level analysis result (shared across containers using the same image)."""

    score: int
    flags: list[AnomalySignal]
    candidate_digest: str | None
    candidate_size: int | None


@dataclass
class ContainerAnalysisResult:
    """Per-container analysis result (release corroboration)."""

    held: bool
    flags: list[AnomalySignal]


def signal_to_dict(signal: AnomalySignal) -> dict:
    """Convert an AnomalySignal to a serializable dict."""
    return asdict(signal)


async def check_release_exists(
    release_source: str,
    tag: str,
    token: str | None,
) -> ReleaseStatus:
    """Check if a GitHub release exists for a given tag.

    Tries multiple tag formats: exact, with 'v' prefix, without 'v' prefix.
    A 200 response (even with empty body) = EXISTS.
    A 404 for all variants = MISSING.
    Any other error = ERROR.
    """
    if not release_source:
        return ReleaseStatus.NO_SOURCE

    # Normalize release_source — strip "github:" prefix if present
    repo = release_source
    if repo.startswith("github:"):
        repo = repo[7:]

    # Try multiple tag variants
    tag_variants = [tag]
    if not tag.startswith("v"):
        tag_variants.append(f"v{tag}")
    elif tag.startswith("v"):
        tag_variants.append(tag[1:])

    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        for variant in tag_variants:
            url = f"https://api.github.com/repos/{repo}/releases/tags/{variant}"
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    return ReleaseStatus.EXISTS
                if response.status_code == 404:
                    continue
                # Unexpected status — treat as error
                logger.warning(
                    "GitHub release check for %s/%s returned %d",
                    repo,
                    variant,
                    response.status_code,
                )
                return ReleaseStatus.ERROR
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
                logger.warning("GitHub release check failed for %s/%s: %s", repo, variant, e)
                return ReleaseStatus.ERROR

    # All variants returned 404
    return ReleaseStatus.MISSING


def resolve_supply_chain_enabled(
    container_enabled: bool | None,
    global_enabled: bool,
) -> bool:
    """Resolve per-container supply chain enablement.

    Container-level override takes precedence; None = inherit global.
    """
    if container_enabled is not None:
        return container_enabled
    return global_enabled


class SupplyChainAnalyzer:
    """Orchestrates supply chain anomaly detection for a check run.

    Create one instance per run_job() — its corroboration cache is scoped
    to a single check run and shared across workers via asyncio.Lock.
    """

    def __init__(self) -> None:
        # Completed results (run-scoped hot cache — fast lookup, no awaiting)
        self._completed: dict[tuple[str, str], ReleaseStatus] = {}
        # In-flight tasks (active GitHub requests — concurrent callers await the same task)
        self._inflight: dict[tuple[str, str], asyncio.Task[ReleaseStatus]] = {}
        self._lock = asyncio.Lock()

    async def _fetch_and_cache(
        self, db: AsyncSession, release_source: str, tag: str
    ) -> ReleaseStatus:
        """Fetch release status from GitHub and persist EXISTS results."""
        token = await SettingsService.get(db, "ghcr_token")
        status = await check_release_exists(release_source, tag, token)
        if status == ReleaseStatus.EXISTS:
            now = datetime.now(UTC)
            await db.execute(
                text("""
                    INSERT INTO release_corroboration_cache
                        (release_source, tag, status, checked_at, created_at, updated_at)
                    VALUES (:source, :tag, :status, :checked_at, :checked_at, :checked_at)
                    ON CONFLICT(release_source, tag) DO UPDATE SET
                        status = :status,
                        checked_at = :checked_at,
                        updated_at = :checked_at
                """),
                {
                    "source": release_source,
                    "tag": tag,
                    "status": "exists",
                    "checked_at": now,
                },
            )
            await db.commit()
        return status

    async def capture_candidate_metadata(
        self,
        db: AsyncSession,
        registry: str,
        image: str,
        tag: str,
    ) -> tuple[str | None, int | None]:
        """First-class digest+size capture for a candidate tag.

        Registry-agnostic. Returns (digest, size).
        Size may be None for non-Docker Hub registries.
        """
        client = await RegistryClientFactory.get_client(registry, db)
        try:
            meta = await client.get_tag_metadata(image, tag)
        finally:
            await client.close()

        if meta:
            return meta.get("digest"), meta.get("full_size")
        return None, None

    async def analyze_image(
        self,
        db: AsyncSession,
        registry: str,
        image: str,
        version_track: str | None,
        candidate_size: int | None,
    ) -> ImageAnalysisResult:
        """Image-level enrichment: size anomaly detection.

        Compares candidate size against baseline. Only meaningful for
        registries that return size (Docker Hub). Fails open.
        """
        flags: list[AnomalySignal] = []

        if candidate_size:
            baseline = (
                await db.execute(
                    select(SupplyChainBaseline).where(
                        SupplyChainBaseline.registry == registry,
                        SupplyChainBaseline.image == image,
                        SupplyChainBaseline.version_track == version_track,
                    )
                )
            ).scalar_one_or_none()

            if baseline and baseline.last_trusted_size_bytes:
                delta_pct = (
                    abs(candidate_size - baseline.last_trusted_size_bytes)
                    / baseline.last_trusted_size_bytes
                )
                if delta_pct > 0.5:
                    flags.append(
                        AnomalySignal(
                            name="size_anomaly",
                            score=25,
                            detail=f"Size changed {delta_pct:.0%} from baseline",
                            tier="enrichment",
                        )
                    )

        return ImageAnalysisResult(
            score=sum(f.score for f in flags),
            flags=flags,
            candidate_digest=None,
            candidate_size=candidate_size,
        )

    async def analyze_container(
        self,
        db: AsyncSession,
        release_source: str | None,
        new_tag: str,
    ) -> ContainerAnalysisResult:
        """Per-container analysis: release corroboration (hard hold).

        If release_source is set, checks GitHub for a matching release.
        Missing release or GitHub error = held.

        Uses a three-tier cache:
        1. In-memory completed cache (hot path, within-run dedup)
        2. Persistent DB cache (cross-run, EXISTS only, TTL-gated)
        3. GitHub API (cache miss)
        """
        if not release_source:
            return ContainerAnalysisResult(held=False, flags=[])

        cache_key = (release_source, new_tag)

        # Check in-memory completed cache and inflight tasks under lock
        task: asyncio.Task[ReleaseStatus] | None = None
        status: ReleaseStatus | None = None

        async with self._lock:
            if cache_key in self._completed:
                status = self._completed[cache_key]
            elif cache_key in self._inflight:
                task = self._inflight[cache_key]
            else:
                # Check persistent DB cache before creating a task
                ttl_hours = await SettingsService.get_int(
                    db, "supply_chain_cache_ttl_hours", default=2
                )
                cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
                row = (
                    await db.execute(
                        select(ReleaseCorroborationCache).where(
                            ReleaseCorroborationCache.release_source == release_source,
                            ReleaseCorroborationCache.tag == new_tag,
                            ReleaseCorroborationCache.status == "exists",
                            ReleaseCorroborationCache.checked_at >= cutoff,
                        )
                    )
                ).scalar_one_or_none()

                if row:
                    status = ReleaseStatus.EXISTS
                    self._completed[cache_key] = status
                    logger.debug(
                        "Persistent cache hit for %s:%s (checked %s)",
                        release_source,
                        new_tag,
                        row.checked_at,
                    )
                else:
                    # First caller for this key — create task
                    task = asyncio.create_task(self._fetch_and_cache(db, release_source, new_tag))
                    self._inflight[cache_key] = task

        # If we need to await a task (our own or another caller's), do it outside the lock
        if status is None and task is not None:
            try:
                status = await task
                async with self._lock:
                    self._completed[cache_key] = status
                    self._inflight.pop(cache_key, None)
            except Exception:
                # Failed — evict so next caller retries (identity check)
                async with self._lock:
                    if self._inflight.get(cache_key) is task:
                        del self._inflight[cache_key]
                raise

        # Fallback — should not happen, but satisfy type checker
        if status is None:
            status = ReleaseStatus.ERROR

        if status == ReleaseStatus.MISSING:
            return ContainerAnalysisResult(
                held=True,
                flags=[
                    AnomalySignal(
                        name="missing_release",
                        score=0,
                        detail=f"No GitHub release for {new_tag}",
                        tier="hard_hold",
                    )
                ],
            )
        elif status == ReleaseStatus.ERROR:
            # Check for grace period — recent successful check for this source
            grace_hours = await SettingsService.get_int(
                db, "supply_chain_github_grace_period_hours", default=24
            )
            grace_cutoff = datetime.now(UTC) - timedelta(hours=grace_hours)
            recent_success = (
                await db.execute(
                    select(ReleaseCorroborationCache)
                    .where(
                        ReleaseCorroborationCache.release_source == release_source,
                        ReleaseCorroborationCache.status == "exists",
                        ReleaseCorroborationCache.checked_at >= grace_cutoff,
                    )
                    .order_by(ReleaseCorroborationCache.checked_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if recent_success and recent_success.checked_at:
                hours_ago = int(
                    (datetime.now(UTC) - recent_success.checked_at).total_seconds() / 3600
                )
                return ContainerAnalysisResult(
                    held=True,
                    flags=[
                        AnomalySignal(
                            name="github_grace_period",
                            score=0,
                            detail=(
                                f"GitHub unreachable but {release_source} "
                                f"verified {hours_ago}h ago — manual approval required"
                            ),
                            tier="hard_hold",
                        )
                    ],
                )

            return ContainerAnalysisResult(
                held=True,
                flags=[
                    AnomalySignal(
                        name="release_check_failed",
                        score=0,
                        detail="GitHub API unreachable",
                        tier="hard_hold",
                    )
                ],
            )

        return ContainerAnalysisResult(held=False, flags=[])
