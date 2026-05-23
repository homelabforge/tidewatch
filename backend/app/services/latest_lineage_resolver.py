"""Phase 2 (D10): :latest lineage resolver.

Resolves the upstream major of ``:latest`` for a given image so the decision
maker can reject candidates whose major exceeds the cap. This is the defense
that would have caught the lidarr 8.1.2135 orphan-tag incident: ``:latest``
resolved to a v3 image, so any candidate with major > 3 must be rejected.

The cap is opt-out per container (``latest_lineage_cap_disabled`` flag) — the
default is to enforce. This is intentional: the original Phase 5 stable
channel anchor is opt-in per container, and lidarr (the incident victim)
hadn't opted in. Default-on closes that gap.

Two strategies are tried in order:

1. **Label strategy (primary, cheap):** fetch ``:latest``'s image config
   blob and parse ``org.opencontainers.image.version`` (or related labels).
   This is one round-trip per call once the manifest is in cache.
2. **Digest-walk fallback:** when the label is absent or unparseable, fetch
   the digest of ``:latest`` and walk a small set of top candidates,
   returning the major of the first matching digest.

For registries with no ``:latest`` tag (some Quay images, some private GHCR),
the resolver returns ``None`` and the cap is a no-op for that image.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.registry_client import RegistryClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineageResolution:
    """Resolved `:latest` lineage information.

    Attributes:
        major: Upstream major version of ``:latest``.
        method: Which strategy produced the value (``"label"`` or
            ``"digest_walk"``).
    """

    major: int
    method: str


class _LineageCache:
    """In-process cache for `:latest` lineage resolutions.

    Keyed on ``(registry, image)``. Short TTL so we don't pin a stale cap
    after upstream cuts a new major release.
    """

    def __init__(self, ttl_minutes: int = 15) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._store: dict[tuple[str, str], tuple[LineageResolution, datetime]] = {}

    def get(self, registry: str, image: str) -> LineageResolution | None:
        key = (registry.lower(), image)
        entry = self._store.get(key)
        if entry is None:
            return None
        resolution, stored_at = entry
        if datetime.now(UTC) - stored_at > self._ttl:
            del self._store[key]
            return None
        return resolution

    def set(self, registry: str, image: str, resolution: LineageResolution) -> None:
        self._store[(registry.lower(), image)] = (resolution, datetime.now(UTC))

    def clear(self) -> None:
        self._store.clear()


_lineage_cache = _LineageCache()


def get_lineage_cache() -> _LineageCache:
    """Access the process-global lineage cache."""
    return _lineage_cache


class LatestLineageResolver:
    """Resolve `:latest`'s upstream major for an image."""

    def __init__(self, client: RegistryClient):
        self._client = client

    async def resolve(
        self, image: str, *, current_best: str | None = None
    ) -> LineageResolution | None:
        """Resolve ``:latest`` to a major version.

        Args:
            image: Image name (e.g. ``"linuxserver/lidarr"``).
            current_best: Best semver candidate the comparator chose,
                threaded in so the digest-walk fallback can short-circuit
                when the best candidate's digest matches ``:latest``.

        Returns:
            ``LineageResolution`` with the resolved major and method used,
            or ``None`` if no strategy produced a value.
        """
        registry = getattr(self._client, "_registry_name", "")
        cached = _lineage_cache.get(registry, image)
        if cached is not None:
            return cached

        # Strategy 1: label-based.
        major_via_label = await self._resolve_via_labels(image)
        if major_via_label is not None:
            resolution = LineageResolution(major=major_via_label, method="label")
            _lineage_cache.set(registry, image, resolution)
            return resolution

        # Strategy 2: digest walk against the best candidate.
        if current_best:
            major_via_walk = await self._resolve_via_digest_walk(image, current_best)
            if major_via_walk is not None:
                resolution = LineageResolution(major=major_via_walk, method="digest_walk")
                _lineage_cache.set(registry, image, resolution)
                return resolution

        return None

    async def _resolve_via_labels(self, image: str) -> int | None:
        """Label strategy: read ``:latest``'s image config labels."""
        try:
            result = await self._client.get_image_labels(image, "latest")
        except Exception as exc:  # noqa: BLE001
            logger.debug("LatestLineageResolver label fetch failed for %s:latest — %s", image, exc)
            return None
        if not result:
            return None

        labels, _digest = result
        if not isinstance(labels, dict):
            return None

        # Reuse channel_anchor's label-key priority + parser.
        from app.services.channel_anchor import ANCHOR_LABEL_KEYS, extract_anchor_major

        for key in ANCHOR_LABEL_KEYS:
            value = labels.get(key)
            if not value:
                continue
            major = extract_anchor_major(key, value)
            if major is not None:
                return major
        return None

    async def _resolve_via_digest_walk(self, image: str, candidate_tag: str) -> int | None:
        """Digest-walk strategy: compare candidate_tag's digest to :latest's.

        Cheap path: if candidate's digest matches `:latest`'s digest, return
        the candidate's parsed major.
        """
        try:
            latest_meta = await self._client.get_tag_metadata(image, "latest")
            candidate_meta = await self._client.get_tag_metadata(image, candidate_tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LatestLineageResolver digest walk fetch failed for %s — %s", image, exc)
            return None

        latest_digest = (latest_meta or {}).get("digest")
        candidate_digest = (candidate_meta or {}).get("digest")
        if not latest_digest or not candidate_digest:
            return None
        if latest_digest != candidate_digest:
            return None

        # Parse the candidate's major via the client's normalizer.
        parsed = self._client._parse_semver(candidate_tag)  # noqa: SLF001
        if parsed is None:
            return None
        return parsed[0]
