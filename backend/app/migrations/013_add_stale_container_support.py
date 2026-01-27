#!/usr/bin/env python3
"""
Migration 013: Add Stale Container Support

Adds snoozed_until field to updates table to support snoozing/dismissing
stale container notifications for a configurable period.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    """Add snoozed_until column to updates table."""
    async with engine.begin() as conn:
        logger.info("Adding snoozed_until column to updates table…")

        # Check if column already exists
        result = await conn.execute(text("PRAGMA table_info(updates)"))
        columns = [row[1] for row in result.fetchall()]

        if "snoozed_until" in columns:
            logger.info("  ⚠ Column already exists, skipping")
        else:
            await conn.execute(
                text("""
                ALTER TABLE updates
                ADD COLUMN snoozed_until DATETIME
            """)
            )
            logger.info("  ✓ Column added")

        logger.info("Migration completed ✅")


if __name__ == "__main__":
    asyncio.run(migrate())
