"""Phase 9 (D17): persistent ETag-revalidated tag cache.

A small L2 layer that lets registry clients revalidate tag lists across
process restarts via HTTP ``If-None-Match`` (ETag) and ``If-Modified-Since``.
GHCR, LSCR, GCR, and Quay honor ETag on ``/v2/{image}/tags/list`` and reply
with a 304 carrying no body — effectively a free hit. Docker Hub does not
honor ETag, so its entries fall through to TTL-based eviction.

The in-process ``TagCache`` (15-min TTL in ``registry_client.py``) remains
the L1 layer; this module is L2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_DOCKERHUB_TTL = timedelta(hours=1)
DEFAULT_STALE_LIMIT = timedelta(days=7)


@dataclass(frozen=True)
class CachedTagListing:
    """One persisted tag listing for an image.

    ``etag`` and ``last_modified`` are revalidation hints; ``tags`` holds
    the latest known tag set; ``fetched_at`` is the wall-clock time the
    entry was last refreshed (either via 200 OK or a 304-confirmed hit).
    """

    tags: list[str]
    etag: str | None
    last_modified: str | None
    fetched_at: datetime


class PersistentTagCache:
    """L2 tag-list cache backed by ``tag_cache_entries``."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self, registry: str, image: str) -> CachedTagListing | None:
        """Look up a cached listing. Returns None when absent."""
        result = await self._db.execute(
            text(
                "SELECT etag, last_modified, tags, fetched_at "
                "FROM tag_cache_entries "
                "WHERE registry = :registry AND image = :image"
            ),
            {"registry": registry.lower(), "image": image},
        )
        row = result.fetchone()
        if row is None:
            return None
        etag, last_modified, tags_json, fetched_at_raw = row
        try:
            tags = json.loads(tags_json) if tags_json else []
        except json.JSONDecodeError:
            tags = []
        if isinstance(fetched_at_raw, str):
            try:
                fetched_at = datetime.fromisoformat(fetched_at_raw)
            except ValueError:
                fetched_at = datetime.now(UTC)
        elif isinstance(fetched_at_raw, datetime):
            fetched_at = fetched_at_raw
        else:
            fetched_at = datetime.now(UTC)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return CachedTagListing(
            tags=tags,
            etag=etag,
            last_modified=last_modified,
            fetched_at=fetched_at,
        )

    async def upsert(
        self,
        registry: str,
        image: str,
        *,
        tags: list[str],
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        """Insert or update the entry. Refreshes ``fetched_at``."""
        await self._db.execute(
            text(
                """
                INSERT INTO tag_cache_entries (
                    registry, image, etag, last_modified, tags, fetched_at
                ) VALUES (
                    :registry, :image, :etag, :last_modified, :tags, :fetched_at
                )
                ON CONFLICT(registry, image) DO UPDATE SET
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    tags = excluded.tags,
                    fetched_at = excluded.fetched_at
                """
            ),
            {
                "registry": registry.lower(),
                "image": image,
                "etag": etag,
                "last_modified": last_modified,
                "tags": json.dumps(tags),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._db.commit()

    async def touch(self, registry: str, image: str) -> None:
        """Refresh ``fetched_at`` without rewriting tags (304 confirmation)."""
        await self._db.execute(
            text(
                "UPDATE tag_cache_entries SET fetched_at = :fetched_at "
                "WHERE registry = :registry AND image = :image"
            ),
            {
                "registry": registry.lower(),
                "image": image,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._db.commit()

    async def evict_stale(self, *, older_than: timedelta = DEFAULT_STALE_LIMIT) -> int:
        """Remove entries that haven't been confirmed inside ``older_than``."""
        threshold = (datetime.now(UTC) - older_than).isoformat()
        result = await self._db.execute(
            text("DELETE FROM tag_cache_entries WHERE fetched_at < :threshold"),
            {"threshold": threshold},
        )
        await self._db.commit()
        deleted: int = result.rowcount or 0  # type: ignore[assignment]
        return deleted
