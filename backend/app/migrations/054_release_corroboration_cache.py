"""Add release corroboration cache table.

Migration: 054
Description: Persistent cache for GitHub release EXISTS results.
    Only EXISTS results are cached; MISSING and ERROR are always re-checked.
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    """Create release_corroboration_cache table."""
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(text("BEGIN"))

        try:
            await conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS release_corroboration_cache (
                        id INTEGER NOT NULL PRIMARY KEY,
                        release_source VARCHAR NOT NULL,
                        tag VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        checked_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(release_source, tag)
                    )
                """)
            )

            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_corroboration_source "
                    "ON release_corroboration_cache(release_source)"
                )
            )

            await conn.execute(text("COMMIT"))
            logger.info("Migration 054 complete: release corroboration cache table created")

        except Exception:
            await conn.execute(text("ROLLBACK"))
            raise

        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def downgrade() -> None:
    """Downgrade not supported for safety."""
    raise NotImplementedError(
        "Downgrade not supported. Restore from pre-migration backup if needed."
    )
