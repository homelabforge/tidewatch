#!/usr/bin/env python3
"""Database migration: Add Retry Logic for Failed Updates

This migration adds fields to track retry attempts and scheduling:
- retry_count: Number of retry attempts made
- max_retries: Maximum retries allowed for this update
- next_retry_at: Timestamp for next retry attempt
- last_error: Last error message from failed attempt
- backoff_multiplier: Exponential backoff multiplier (default 3)

Usage:
    python migrations/006_add_retry_logic.py
"""

import asyncio
import logging
import sys
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
    """Add retry logic columns to updates table."""
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        # Add retry_count column
        if not await column_exists(conn, "updates", "retry_count"):
            await conn.execute(
                text("""
                ALTER TABLE updates ADD COLUMN retry_count INTEGER DEFAULT 0;
            """)
            )
            logger.info("✅ Added retry_count column")
        else:
            logger.info("⏭️  Skipped retry_count column (already exists)")

        # Add max_retries column
        if not await column_exists(conn, "updates", "max_retries"):
            await conn.execute(
                text("""
                ALTER TABLE updates ADD COLUMN max_retries INTEGER DEFAULT 3;
            """)
            )
            logger.info("✅ Added max_retries column")
        else:
            logger.info("⏭️  Skipped max_retries column (already exists)")

        # Add next_retry_at column
        if not await column_exists(conn, "updates", "next_retry_at"):
            await conn.execute(
                text("""
                ALTER TABLE updates ADD COLUMN next_retry_at TIMESTAMP NULL;
            """)
            )
            logger.info("✅ Added next_retry_at column")
        else:
            logger.info("⏭️  Skipped next_retry_at column (already exists)")

        # Add last_error column
        if not await column_exists(conn, "updates", "last_error"):
            await conn.execute(
                text("""
                ALTER TABLE updates ADD COLUMN last_error TEXT NULL;
            """)
            )
            logger.info("✅ Added last_error column")
        else:
            logger.info("⏭️  Skipped last_error column (already exists)")

        # Add backoff_multiplier column
        if not await column_exists(conn, "updates", "backoff_multiplier"):
            await conn.execute(
                text("""
                ALTER TABLE updates ADD COLUMN backoff_multiplier INTEGER DEFAULT 3;
            """)
            )
            logger.info("✅ Added backoff_multiplier column")
        else:
            logger.info("⏭️  Skipped backoff_multiplier column (already exists)")

    await engine.dispose()
    logger.info("✅ Migration 006 completed: Retry logic fields added to updates table")


async def main():
    """Run the migration."""
    logger.info("Running migration: 006_add_retry_logic")
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
