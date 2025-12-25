"""Add latest_major_tag column to containers table.

Migration: 032
Date: 2025-12-25
Description: Add latest_major_tag column to track major version updates that exist
             outside the container's configured scope (patch/minor). This allows users
             to see major updates as informational indicators even when scope blocks them.
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import engine


async def upgrade():
    """Add latest_major_tag column to containers table."""
    async with engine.begin() as conn:
        # Add column for storing major version updates (nullable, no default)
        await conn.execute(
            text("ALTER TABLE containers ADD COLUMN latest_major_tag TEXT NULL")
        )


async def downgrade():
    """Remove latest_major_tag column from containers table."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE containers DROP COLUMN latest_major_tag"))
