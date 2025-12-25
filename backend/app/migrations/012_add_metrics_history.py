#!/usr/bin/env python3
"""Migration: add metrics_history table for storing historical container metrics."""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db import DATABASE_URL  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def table_exists(conn, table: str) -> bool:
    """Check if a table exists."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    )
    return result.fetchone() is not None


async def migrate():
    logger.info("Starting migration: add metrics_history table")
    logger.info("Database URL: %s", DATABASE_URL)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            if not await table_exists(conn, "metrics_history"):
                logger.info("Creating metrics_history table...")
                await conn.execute(
                    text("""
                        CREATE TABLE metrics_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            container_id INTEGER NOT NULL,
                            collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            cpu_percent REAL NOT NULL,
                            memory_usage INTEGER NOT NULL,
                            memory_limit INTEGER NOT NULL,
                            memory_percent REAL NOT NULL,
                            network_rx INTEGER NOT NULL,
                            network_tx INTEGER NOT NULL,
                            block_read INTEGER NOT NULL,
                            block_write INTEGER NOT NULL,
                            pids INTEGER NOT NULL,
                            FOREIGN KEY (container_id) REFERENCES containers(id) ON DELETE CASCADE
                        )
                    """)
                )
                logger.info("  ✓ Table created")

                logger.info("Creating indexes...")
                await conn.execute(
                    text(
                        "CREATE INDEX idx_metrics_history_container ON metrics_history(container_id)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_metrics_history_collected ON metrics_history(collected_at)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_container_collected ON metrics_history(container_id, collected_at)"
                    )
                )
                logger.info("  ✓ Indexes created")
            else:
                logger.info("  ⊘ Table already exists")
    finally:
        await engine.dispose()

    logger.info("Migration completed ✅")


if __name__ == "__main__":
    asyncio.run(migrate())
