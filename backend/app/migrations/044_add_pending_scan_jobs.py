"""Add pending_scan_jobs table for durable VulnForge scan tracking.

Migration: 044
Date: 2026-02-09
Description: Creates the pending_scan_jobs table so TideWatch can persist
             VulnForge scan requests across restarts. Replaces the fire-and-forget
             asyncio.create_task() pattern with a durable, scheduler-driven workflow.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade() -> None:
    """Create pending_scan_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS pending_scan_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    container_name TEXT NOT NULL,
                    update_id INTEGER NOT NULL,
                    vulnforge_job_id INTEGER,
                    vulnforge_scan_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    poll_count INTEGER NOT NULL DEFAULT 0,
                    max_polls INTEGER NOT NULL DEFAULT 12,
                    last_polled_at TIMESTAMP,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (update_id) REFERENCES updates(id)
                )
            """)
        )

        # Index on status for worker polling
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_pending_scan_job_status "
                "ON pending_scan_jobs(status)"
            )
        )

        # Index on update_id for lookups
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_pending_scan_job_update_id "
                "ON pending_scan_jobs(update_id)"
            )
        )


async def downgrade() -> None:
    """Drop pending_scan_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_pending_scan_job_update_id"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_pending_scan_job_status"))
        await conn.execute(text("DROP TABLE IF EXISTS pending_scan_jobs"))
