"""Remove authentication infrastructure.

This migration removes the users and secret_keys tables that were part of the
authentication system. Authentication has been removed in favor of network-level
security (Traefik, firewall, etc.).
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def upgrade():
    """Drop users and secret_keys tables."""
    logger.info("Starting migration 021: Remove authentication tables")

    async with engine.begin() as conn:
        # Drop users table (no foreign keys reference it)
        await conn.execute(text("DROP TABLE IF EXISTS users"))
        logger.info("Dropped users table")

        # Drop secret_keys table (no foreign keys reference it)
        await conn.execute(text("DROP TABLE IF EXISTS secret_keys"))
        logger.info("Dropped secret_keys table")

    logger.info("Migration 021 completed: Authentication tables removed")


async def downgrade():
    """Recreate tables (not implemented - use backups if needed)."""
    logger.warning(
        "Downgrade not implemented for migration 021. "
        "Restore from backup if you need to recover authentication tables."
    )
