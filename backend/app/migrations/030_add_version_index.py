"""Add database index on (status, version) for optimized concurrent queries.

Migration: 030
Date: 2025-01-28
Description: Add composite index on updates table for status and version columns
             to improve performance during concurrent update operations with
             optimistic locking.
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import engine


async def upgrade():
    """Add composite index on (status, version) for faster concurrent lookups."""
    async with engine.begin() as conn:
        # Create index on status and version for optimized concurrent queries
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_updates_status_version ON updates(status, version)"
            )
        )


async def downgrade():
    """Remove the status/version index."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_status_version"))
