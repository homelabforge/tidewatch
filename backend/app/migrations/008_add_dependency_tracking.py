#!/usr/bin/env python3
"""Database migration: Add Dependency Tracking

This migration adds fields to track container dependencies:
- dependencies: JSON array of container names this container depends on
- dependents: JSON array of container names that depend on this container

Example:
  Container "app" depends on ["db", "redis"]
  Container "db" has dependents ["app", "worker"]

These fields enable dependency-ordered updates where dependencies
are updated before their dependents.

Usage:
    python migrations/008_add_dependency_tracking.py
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
    """Add dependency tracking columns to containers table."""
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        # Add dependencies column
        if not await column_exists(conn, "containers", "dependencies"):
            await conn.execute(
                text("""
                ALTER TABLE containers ADD COLUMN dependencies TEXT NULL;
            """)
            )
            logger.info("✅ Added dependencies column")
        else:
            logger.info("⏭️  Skipped dependencies column (already exists)")

        # Add dependents column
        if not await column_exists(conn, "containers", "dependents"):
            await conn.execute(
                text("""
                ALTER TABLE containers ADD COLUMN dependents TEXT NULL;
            """)
            )
            logger.info("✅ Added dependents column")
        else:
            logger.info("⏭️  Skipped dependents column (already exists)")

    await engine.dispose()
    logger.info("✅ Migration 008 completed: Dependency tracking added to containers table")


async def main():
    """Run the migration."""
    logger.info("Running migration: 008_add_dependency_tracking")
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
