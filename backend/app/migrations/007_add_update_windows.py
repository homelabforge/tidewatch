#!/usr/bin/env python3
"""Database migration: Add Update Window Configuration

This migration adds a field to configure maintenance windows:
- update_window: JSON string defining allowed update times
  Format examples:
    - "02:00-06:00" (daily between 2am-6am)
    - "Sat,Sun:00:00-23:59" (weekends only)
    - "Mon-Fri:22:00-06:00" (weeknights)
  Empty/null means no restrictions

Usage:
    python migrations/007_add_update_windows.py
"""

import sys
import asyncio
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    return any(col[1] == column_name for col in columns)


async def upgrade():
    """Add update_window column to containers table."""
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        if not await column_exists(conn, "containers", "update_window"):
            await conn.execute(
                text("""
                ALTER TABLE containers ADD COLUMN update_window TEXT NULL;
            """)
            )
            logger.info("✅ Added update_window column to containers table")
            logger.info("   Format: 'HH:MM-HH:MM' or 'Days:HH:MM-HH:MM'")
        else:
            logger.info("⏭️  Skipped update_window column (already exists)")

    await engine.dispose()
    logger.info("✅ Migration 007 completed: Update window configuration added")


async def main():
    """Run the migration."""
    logger.info("Running migration: 007_add_update_windows")
    try:
        await upgrade()
        logger.info("✅ Migration completed successfully")
        return 0
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
