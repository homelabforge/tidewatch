#!/usr/bin/env python3
"""Migration: add health_check_method to containers.

This allows TideWatch to explicitly track whether a container should be
checked via HTTP or by docker inspect/health state.
"""

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
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result.fetchall())


async def migrate():
    logger.info("Starting migration: add health_check_method column")
    logger.info("Database URL: %s", DATABASE_URL)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            if not await column_exists(conn, "containers", "health_check_method"):
                logger.info("Adding health_check_method column to containers…")
                await conn.execute(
                    text(
                        "ALTER TABLE containers "
                        "ADD COLUMN health_check_method TEXT NOT NULL DEFAULT 'auto'"
                    )
                )
                logger.info("  ✓ Column added")
            else:
                logger.info("  ⊘ Column already exists")
    finally:
        await engine.dispose()

    logger.info("Migration completed ✅")


if __name__ == "__main__":
    asyncio.run(migrate())
