"""Add scope_violation column to updates table.

Migration: 033
Date: 2025-12-25
Description: Add scope_violation column to track major version updates that are
             blocked by container scope settings. This allows these updates to
             appear in history with special indicators and "Apply Anyway" actions.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Add scope_violation column to updates table."""
    async with engine.begin() as conn:
        # Add column with default 0 (not a scope violation)
        await conn.execute(
            text(
                "ALTER TABLE updates ADD COLUMN scope_violation INTEGER DEFAULT 0 NOT NULL"
            )
        )


async def downgrade():
    """Remove scope_violation column from updates table."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE updates DROP COLUMN scope_violation"))
