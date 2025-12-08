#!/usr/bin/env python3
"""Database migration: Add Retry and Update Window Settings

This migration adds global settings for:
- Retry logic configuration (max attempts, backoff multiplier)
- Default update windows for new containers
- Window enforcement policy

Usage:
    python migrations/009_add_retry_and_window_settings.py
"""

import sys
import asyncio
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Add new settings for retry logic and update windows."""
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        # Retry configuration settings
        await conn.execute(text("""
            INSERT OR IGNORE INTO settings (key, value, description, category)
            VALUES
            ('update_retry_max_attempts', '3', 'Maximum retry attempts for failed updates (0-10)', 'updates'),
            ('update_retry_backoff_multiplier', '3.0', 'Exponential backoff multiplier for retry delays (1.0-10.0)', 'updates');
        """))
        logger.info("✅ Added retry configuration settings")

        # Update window settings
        await conn.execute(text("""
            INSERT OR IGNORE INTO settings (key, value, description, category)
            VALUES
            ('default_update_window', '', 'Default update window for new containers (e.g., 22:00-06:00 or Mon-Fri:02:00-06:00)', 'updates'),
            ('update_window_enforcement', 'strict', 'Update window enforcement (strict: block updates outside window, advisory: warn but allow)', 'updates');
        """))
        logger.info("✅ Added update window settings")

    await engine.dispose()
    logger.info("✅ Migration 009 completed: Retry and update window settings added")


async def main():
    """Run the migration."""
    logger.info("Running migration: 009_add_retry_and_window_settings")
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
