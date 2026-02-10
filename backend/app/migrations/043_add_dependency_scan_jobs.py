"""Add dependency_scan_jobs table for background dependency scan tracking.

Migration: 043
Date: 2026-02-09
Description: Creates the dependency_scan_jobs table to track background dependency
             scans for My Projects, enabling non-blocking scans with progress reporting.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade() -> None:
    """Create dependency_scan_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS dependency_scan_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    total_count INTEGER NOT NULL DEFAULT 0,
                    scanned_count INTEGER NOT NULL DEFAULT 0,
                    updates_found INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    current_project TEXT,
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
                "CREATE INDEX IF NOT EXISTS idx_dep_scan_job_status ON dependency_scan_jobs(status)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_dep_scan_job_created_at "
                "ON dependency_scan_jobs(created_at)"
            )
        )


async def downgrade() -> None:
    """Drop dependency_scan_jobs table."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_dep_scan_job_created_at"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_dep_scan_job_status"))
        await conn.execute(text("DROP TABLE IF EXISTS dependency_scan_jobs"))
