"""Post-main-pass sibling drift detection and safety-net reconciliation.

Narrow safety net over :mod:`check_job_service`. Not a systemic drift fix —
see plan ``squishy-wiggling-wall.md`` for the full framing.

Responsibilities:

- Group containers by ``(compose_file, registry, image)`` to identify sibling
  sets (containers sharing the same image in the same compose file).
- For each sibling group with >= 2 members, detect two kinds of drift:

  1. **Tag drift** — siblings with differing ``current_tag`` values.
  2. **Settings drift** — siblings with differing effective check settings
     (``scope``, ``include_prereleases``, ``version_track``).

- Record a :class:`SiblingDrift` entry whenever either kind is present, so the
  event can be reported via SSE and notifications regardless of whether we can
  safely auto-reconcile.
- Run a narrow reconciliation pass only for groups where every sibling shares
  identical settings AND the same ``current_tag`` as the dominant tag. In that
  case, a shared :class:`FetchTagsResponse` is safe to reuse because
  :class:`UpdateDecisionMaker` would compute the same derived fields for every
  sibling in the group.
- Never create speculative Update records for drifted-tag siblings. That path
  is the bug that started the authentik incident; resolution happens via the
  runbook (``POST /api/containers/sync`` then ``POST /api/updates/check``).
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.sibling_drift_event import SiblingDriftEvent
from app.services.check_run_context import CheckRunContext
from app.services.registry_rate_limiter import RegistryRateLimiter
from app.services.settings_service import SettingsService
from app.services.tag_fetcher import TagFetcher
from app.services.update_checker import UpdateChecker
from app.services.update_decision_maker import UpdateDecisionMaker

logger = logging.getLogger(__name__)


@dataclass
class SiblingDrift:
    """Observed drift between siblings sharing an image."""

    compose_file: str
    registry: str
    image: str
    sibling_names: list[str]
    dominant_tag: str
    per_container_tags: dict[str, str]
    settings_divergent: bool
    reconciled_names: list[str] = field(default_factory=list)

    @property
    def has_tag_drift(self) -> bool:
        return any(tag != self.dominant_tag for tag in self.per_container_tags.values())


def _effective_prereleases(container: Container, global_default: bool) -> bool:
    """Resolve effective include_prereleases for a container."""
    explicit = container.include_prereleases  # type: ignore[attr-defined]
    if explicit is None:
        return global_default
    return bool(explicit)


def _settings_signature(container: Container, global_prereleases: bool) -> tuple:
    """Build the check-settings signature used to detect settings drift."""
    return (
        str(container.scope),  # type: ignore[attr-defined]
        _effective_prereleases(container, global_prereleases),
        container.version_track if container.version_track else None,  # type: ignore[attr-defined]
    )


def _group_siblings(containers: list[Container]) -> dict[tuple[str, str, str], list[Container]]:
    """Group non-disabled containers by (compose_file, registry, image)."""
    groups: dict[tuple[str, str, str], list[Container]] = defaultdict(list)
    for container in containers:
        if str(container.policy) == "disabled":  # type: ignore[attr-defined]
            continue
        key = (
            str(container.compose_file),  # type: ignore[attr-defined]
            str(container.registry).lower(),  # type: ignore[attr-defined]
            str(container.image).lower(),  # type: ignore[attr-defined]
        )
        groups[key].append(container)
    return groups


async def reconcile_siblings(
    db: AsyncSession,
    run_context: CheckRunContext,
    rate_limiter: RegistryRateLimiter,
    all_containers: list[Container],
    updated_ids: set[int],
    global_prereleases: bool,
    job_id: int = 0,
) -> list[SiblingDrift]:
    """Run the post-main-pass sibling drift detection + safety-net reconciliation.

    Args:
        db: Database session for registry client credentials and DB writes.
            Each successful reconciliation apply commits on this session.
        run_context: Run-scoped check context (shared cache hits live here).
        rate_limiter: Registry rate limiter (shared across the job).
        all_containers: All non-disabled containers discovered in this job.
            Typically the same list used to build the main-pass groups.
        updated_ids: Container IDs that already received an Update record via
            the main pass; reconciliation skips these.
        global_prereleases: Global include_prereleases default (used to
            resolve per-container None values).
        job_id: Check job ID for correlating drift events with runs.

    Returns:
        A list of :class:`SiblingDrift` entries, one per sibling group that
        observed drift (tag or settings). An empty list means everything is
        in sync.
    """
    drifts: list[SiblingDrift] = []

    enabled = await SettingsService.get_bool(db, "sibling_reconciliation_enabled", default=True)
    if not enabled:
        logger.debug("Sibling reconciliation disabled by setting")
        return drifts

    sibling_groups = _group_siblings(all_containers)

    for (compose_file, registry, image), group in sibling_groups.items():
        if len(group) < 2:
            continue

        tag_counts = Counter(str(c.current_tag) for c in group)  # type: ignore[attr-defined]
        dominant_tag = tag_counts.most_common(1)[0][0]
        per_container_tags = {
            str(c.name): str(c.current_tag)
            for c in group  # type: ignore[attr-defined]
        }
        drifted_by_tag = [
            c
            for c in group
            if str(c.current_tag) != dominant_tag  # type: ignore[attr-defined]
        ]

        signatures = {_settings_signature(c, global_prereleases) for c in group}
        settings_homogeneous = len(signatures) == 1

        drift_present = bool(drifted_by_tag) or not settings_homogeneous
        drift: SiblingDrift | None = None
        if drift_present:
            drift = SiblingDrift(
                compose_file=compose_file,
                registry=registry,
                image=image,
                sibling_names=[str(c.name) for c in group],  # type: ignore[attr-defined]
                dominant_tag=dominant_tag,
                per_container_tags=per_container_tags,
                settings_divergent=not settings_homogeneous,
            )
            drifts.append(drift)
            logger.info(
                "Sibling drift detected in %s for image %s: tags=%s settings_divergent=%s",
                compose_file,
                image,
                per_container_tags,
                not settings_homogeneous,
            )

        # Only auto-reconcile when settings match. Sharing a FetchTagsResponse
        # across divergent-settings siblings would reuse latest_tag /
        # latest_major_tag that were computed for one signature, which is the
        # exact bug Codex flagged.
        recon_attempted = False

        if not settings_homogeneous:
            pass  # Skip reconciliation; recon_attempted stays False
        else:
            representative = next(c for c in group if str(c.current_tag) == dominant_tag)  # type: ignore[attr-defined]
            try:
                tag_fetcher = TagFetcher(db, rate_limiter, run_context)
                fetch_response = await tag_fetcher.fetch_tags_for_container(representative)
            except Exception as exc:
                logger.warning(
                    "Sibling reconciliation fetch failed for image %s: %s",
                    image,
                    exc,
                )
                fetch_response = None

            if fetch_response is not None and not fetch_response.error:
                recon_attempted = True
                decision_maker = UpdateDecisionMaker()
                decision = decision_maker.make_decision(
                    representative,
                    fetch_response,
                    _effective_prereleases(representative, global_prereleases),
                )

                if decision.has_update:
                    for sibling in group:
                        sibling_id: int = int(sibling.id)  # type: ignore[attr-defined]
                        sibling_name: str = str(sibling.name)  # type: ignore[attr-defined]

                        if sibling_id in updated_ids:
                            continue

                        # Drifted-tag siblings: the main pass would have computed a
                        # DIFFERENT decision for them (from_tag = their own current_tag,
                        # which differs from the representative's). Auto-creating an
                        # Update from the representative's decision would persist a
                        # wrong from_tag. This is the bug that started the incident.
                        if str(sibling.current_tag) != dominant_tag:  # type: ignore[attr-defined]
                            continue

                        try:
                            await UpdateChecker.apply_decision(
                                db, sibling, decision, fetch_response
                            )
                            await db.commit()
                            if drift is not None:
                                drift.reconciled_names.append(sibling_name)
                            updated_ids.add(sibling_id)
                            logger.info(
                                "Sibling reconciliation created Update for %s (%s -> %s)",
                                sibling_name,
                                sibling.current_tag,  # type: ignore[attr-defined]
                                decision.latest_tag,
                            )
                        except Exception as exc:
                            logger.error(
                                "Sibling reconciliation apply failed for %s: %s",
                                sibling_name,
                                exc,
                            )
                            await db.rollback()
            elif fetch_response is not None and fetch_response.error:
                logger.warning(
                    "Sibling reconciliation skipped for image %s: %s",
                    image,
                    fetch_response.error,
                )

        # Persist drift event with savepoint isolation — a failed insert
        # rolls back only the savepoint and does not poison the session
        # for subsequent groups.
        if drift is not None:
            try:
                async with db.begin_nested():
                    event = SiblingDriftEvent(
                        compose_file=drift.compose_file,
                        registry=drift.registry,
                        image=drift.image,
                        sibling_names=json.dumps(drift.sibling_names),
                        dominant_tag=drift.dominant_tag,
                        per_container_tags=json.dumps(drift.per_container_tags),
                        settings_divergent=drift.settings_divergent,
                        reconciliation_attempted=recon_attempted,
                        reconciled_names=(
                            json.dumps(drift.reconciled_names) if drift.reconciled_names else None
                        ),
                        job_id=job_id,
                    )
                    db.add(event)
                    await db.flush()
                logger.debug(
                    "Persisted drift event for image %s (job_id=%d, recon_attempted=%s)",
                    drift.image,
                    job_id,
                    recon_attempted,
                )
            except Exception:
                logger.warning(
                    "Failed to persist drift event for %s",
                    drift.image,
                    exc_info=True,
                )

    return drifts
