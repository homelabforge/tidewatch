#!/usr/bin/env python3
"""Database migration: Enrich update history with reason context.

This migration adds:
- reason_type column to update_history (security, feature, bugfix, maintenance, etc.)
- reason_summary column to capture the snapshot of the update summary
- Backfills reason data from existing updates
"""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure backend package is importable when running script directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import DATABASE_URL  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_column_exists(conn, table: str, column: str) -> bool:
    """Check if column exists on a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result.fetchall())


async def migrate():
    """Run migration."""
    logger.info("Starting migration: Update history reason fields")
    logger.info("Database URL: %s", DATABASE_URL)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            # ------------------------------------------------------------------
            # Step 1: Add reason_type column
            # ------------------------------------------------------------------
            if not await check_column_exists(conn, "update_history", "reason_type"):
                logger.info("Adding reason_type column to update_history...")
                await conn.execute(
                    text(
                        "ALTER TABLE update_history "
                        "ADD COLUMN reason_type TEXT NOT NULL DEFAULT 'unknown'"
                    )
                )
                logger.info("  ✓ reason_type column added")
            else:
                logger.info("  ⊘ reason_type column already exists")

            # ------------------------------------------------------------------
            # Step 2: Add reason_summary column
            # ------------------------------------------------------------------
            if not await check_column_exists(conn, "update_history", "reason_summary"):
                logger.info("Adding reason_summary column to update_history...")
                await conn.execute(
                    text("ALTER TABLE update_history ADD COLUMN reason_summary TEXT")
                )
                logger.info("  ✓ reason_summary column added")
            else:
                logger.info("  ⊘ reason_summary column already exists")

            # ------------------------------------------------------------------
            # Step 3: Backfill reason summary from legacy reason field
            # ------------------------------------------------------------------
            logger.info("Backfilling reason_summary from legacy reason column...")
            await conn.execute(
                text(
                    """
                    UPDATE update_history
                    SET reason_summary = reason
                    WHERE (reason_summary IS NULL OR reason_summary = '')
                      AND reason IS NOT NULL
                    """
                )
            )

            # ------------------------------------------------------------------
            # Step 4: Backfill reason type from updates table when possible
            # ------------------------------------------------------------------
            logger.info("Backfilling reason_type from updates.reason_type...")
            await conn.execute(
                text(
                    """
                    UPDATE update_history
                    SET reason_type = (
                        SELECT reason_type
                        FROM updates
                        WHERE updates.id = update_history.update_id
                    )
                    WHERE update_id IN (SELECT id FROM updates)
                    """
                )
            )

            # ------------------------------------------------------------------
            # Step 5: Normalize empty reason types
            # ------------------------------------------------------------------
            logger.info("Normalizing empty reason_type values...")
            await conn.execute(
                text(
                    """
                    UPDATE update_history
                    SET reason_type = 'unknown'
                    WHERE reason_type IS NULL OR reason_type = ''
                    """
                )
            )

        logger.info("Migration completed successfully ✅")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
