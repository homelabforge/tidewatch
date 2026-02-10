"""Add trigger retry tracking fields to pending_scan_jobs.

Supports bounded retry with backoff when VulnForge hasn't discovered
a newly-recreated container yet (race condition between TideWatch update
and VulnForge auto-discovery).
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upgrade(connection):
    """Add trigger_attempt_count and last_trigger_attempt_at columns."""
    result = await connection.execute(text("PRAGMA table_info(pending_scan_jobs)"))
    columns = {row[1] for row in result.fetchall()}

    if "trigger_attempt_count" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE pending_scan_jobs "
                "ADD COLUMN trigger_attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        )
        logger.info("  Added column 'trigger_attempt_count'")
    else:
        logger.info("  -> Column 'trigger_attempt_count' already exists, skipping")

    if "last_trigger_attempt_at" not in columns:
        await connection.execute(
            text("ALTER TABLE pending_scan_jobs ADD COLUMN last_trigger_attempt_at DATETIME")
        )
        logger.info("  Added column 'last_trigger_attempt_at'")
    else:
        logger.info("  -> Column 'last_trigger_attempt_at' already exists, skipping")


async def downgrade(connection):
    """SQLite does not support DROP COLUMN before 3.35.0; log only."""
    logger.info(
        "  Downgrade: trigger_attempt_count and last_trigger_attempt_at "
        "columns left in place (SQLite limitation)"
    )
