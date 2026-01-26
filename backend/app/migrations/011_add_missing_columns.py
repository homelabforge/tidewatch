#!/usr/bin/env python3
"""Migration: add backup_path and current_digest columns."""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.database import DATABASE_URL  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists on a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result.fetchall())


async def migrate():
    logger.info(
        "Starting migration: add backup_path, current_digest, and update_window columns"
    )
    logger.info("Database URL: %s", DATABASE_URL)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            # Add backup_path column to update_history table
            if not await column_exists(conn, "update_history", "backup_path"):
                logger.info("Adding backup_path column to update_history…")
                await conn.execute(
                    text("ALTER TABLE update_history ADD COLUMN backup_path TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ backup_path column already exists")

            # Add current_digest column to containers table
            if not await column_exists(conn, "containers", "current_digest"):
                logger.info("Adding current_digest column to containers…")
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN current_digest TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ current_digest column already exists")

            # Add update_window column to containers table
            if not await column_exists(conn, "containers", "update_window"):
                logger.info("Adding update_window column to containers…")
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN update_window TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ update_window column already exists")

            # Add dependencies column to containers table
            if not await column_exists(conn, "containers", "dependencies"):
                logger.info("Adding dependencies column to containers…")
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN dependencies TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ dependencies column already exists")

            # Add dependents column to containers table
            if not await column_exists(conn, "containers", "dependents"):
                logger.info("Adding dependents column to containers…")
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN dependents TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ dependents column already exists")

            # Add recommendation column to updates table
            if not await column_exists(conn, "updates", "recommendation"):
                logger.info("Adding recommendation column to updates…")
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN recommendation TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ recommendation column already exists")

            # Add retry logic columns to updates table
            if not await column_exists(conn, "updates", "retry_count"):
                logger.info("Adding retry_count column to updates…")
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN retry_count INTEGER DEFAULT 0")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ retry_count column already exists")

            if not await column_exists(conn, "updates", "max_retries"):
                logger.info("Adding max_retries column to updates…")
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN max_retries INTEGER DEFAULT 3")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ max_retries column already exists")

            if not await column_exists(conn, "updates", "next_retry_at"):
                logger.info("Adding next_retry_at column to updates…")
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN next_retry_at TIMESTAMP")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ next_retry_at column already exists")

            if not await column_exists(conn, "updates", "last_error"):
                logger.info("Adding last_error column to updates…")
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN last_error TEXT")
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ last_error column already exists")

            if not await column_exists(conn, "updates", "backoff_multiplier"):
                logger.info("Adding backoff_multiplier column to updates…")
                await conn.execute(
                    text(
                        "ALTER TABLE updates ADD COLUMN backoff_multiplier INTEGER DEFAULT 3"
                    )
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ backoff_multiplier column already exists")
    finally:
        await engine.dispose()

    logger.info("Migration completed ✅")


if __name__ == "__main__":
    asyncio.run(migrate())
