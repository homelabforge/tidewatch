"""Add version column for optimistic locking on updates table.

Migration: 029
Date: 2025-01-28
Description: Add version column to updates table to prevent race conditions during
             concurrent approve/reject/apply operations. Uses optimistic locking
             pattern to detect and prevent concurrent modifications.
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import engine


async def upgrade():
    """Add version column for optimistic locking."""
    async with engine.begin() as conn:
        # Check if column exists before adding (idempotent)
        result = await conn.execute(text("PRAGMA table_info(updates)"))
        columns = {row[1] for row in result.fetchall()}

        if "version" not in columns:
            # Add version column with default value of 1
            await conn.execute(
                text("""
                ALTER TABLE updates
                ADD COLUMN version INTEGER DEFAULT 1 NOT NULL
            """)
            )

            # Initialize existing rows to version 1
            await conn.execute(
                text("""
                UPDATE updates
                SET version = 1
                WHERE version IS NULL
            """)
            )


async def downgrade():
    """Remove version column (SQLite limitation - column remains but unused)."""
    # SQLite doesn't support DROP COLUMN before version 3.35.0
    # For compatibility, we'll leave the column but it will be ignored
    # To truly remove it, you'd need to recreate the table without the column
    pass
