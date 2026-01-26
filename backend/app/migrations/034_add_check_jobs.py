"""Add check_jobs table for background update check tracking.

Migration: 034
Date: 2026-01-23
Description: Creates the check_jobs table to track background update checks,
             enabling non-blocking update checks with progress reporting.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade() -> None:
    """Create check_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS check_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    total_count INTEGER NOT NULL DEFAULT 0,
                    checked_count INTEGER NOT NULL DEFAULT 0,
                    updates_found INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    current_container_id INTEGER,
                    current_container_name TEXT,
                    results TEXT DEFAULT '[]',
                    errors TEXT DEFAULT '[]',
                    triggered_by TEXT NOT NULL DEFAULT 'user',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)
        )

        # Create indexes
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_check_job_status ON check_jobs(status)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_check_job_created_at ON check_jobs(created_at)"
            )
        )


async def downgrade() -> None:
    """Drop check_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_check_job_created_at"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_check_job_status"))
        await conn.execute(text("DROP TABLE IF EXISTS check_jobs"))
