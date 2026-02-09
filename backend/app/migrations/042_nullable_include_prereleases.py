"""Make include_prereleases nullable for tri-state logic.

Migration: 042
Date: 2026-02-08
Description: Change include_prereleases from boolean (default False) to
    nullable boolean (default NULL). This enables tri-state logic:
    NULL = inherit global setting, True = force include, False = force stable only.
    Existing False values are converted to NULL (inherit) since the old toggle
    could not distinguish 'user chose stable' from 'never configured'.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Convert existing include_prereleases=False to NULL (inherit global)."""
    async with engine.begin() as conn:
        # Check how many containers have the old default value
        result = await conn.execute(
            text("SELECT COUNT(*) FROM containers WHERE include_prereleases = 0")
        )
        count = result.scalar() or 0

        if count > 0:
            # Convert all False (0) values to NULL (inherit global setting)
            # Users who had True (1) keep their explicit opt-in
            await conn.execute(
                text(
                    "UPDATE containers SET include_prereleases = NULL WHERE include_prereleases = 0"
                )
            )
            print(
                f"  Migration 042: Converted {count} containers from include_prereleases=False to NULL (inherit global)"
            )
        else:
            print("  Migration 042: No containers need conversion")
