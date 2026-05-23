"""Phase 9 (D17): persistent ETag-revalidated tag cache.

Migration: 059
Description: Adds the ``tag_cache_entries`` table so that registry tag-list
responses can be revalidated via ``If-None-Match`` across process restarts.
GHCR, LSCR, GCR, and Quay honor ``ETag`` on ``/v2/{image}/tags/list`` and
return ``304`` with no body — effectively free. Docker Hub does not honor
ETag, so its rows use TTL-based eviction only.

The in-process ``TagCache`` (15-min TTL) remains as L1; this table is L2.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Create tag_cache_entries table with composite PK."""
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS tag_cache_entries (
                registry VARCHAR(64) NOT NULL,
                image VARCHAR(255) NOT NULL,
                etag VARCHAR(255),
                last_modified VARCHAR(64),
                tags TEXT NOT NULL,
                fetched_at DATETIME NOT NULL,
                PRIMARY KEY (registry, image)
            )
            """
        )
    )
    await db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tag_cache_fetched_at ON tag_cache_entries (fetched_at)"
        )
    )


async def downgrade(db) -> None:
    """Drop tag_cache_entries table."""
    await db.execute(text("DROP TABLE IF EXISTS tag_cache_entries"))
