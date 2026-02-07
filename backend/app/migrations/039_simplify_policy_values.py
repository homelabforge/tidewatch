"""Simplify container policy values from 6 to 3.

Migration: 039
Date: 2026-02-06
Description: Replace patch-only, minor-and-patch, security with auto.
    Replace manual with monitor. Scope now controls version granularity.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Convert old policy values to new simplified set (auto, monitor, disabled)."""
    async with engine.begin() as conn:
        # patch-only, minor-and-patch, security → auto
        # (scope already handles version filtering at the registry level)
        result = await conn.execute(
            text(
                "UPDATE containers SET policy = 'auto' "
                "WHERE policy IN ('patch-only', 'minor-and-patch', 'security')"
            )
        )
        print(f"  Converted {result.rowcount} containers to 'auto' policy")

        # manual → monitor
        result = await conn.execute(
            text("UPDATE containers SET policy = 'monitor' WHERE policy = 'manual'")
        )
        print(f"  Converted {result.rowcount} containers to 'monitor' policy")

        # Update default_policy setting if it exists
        result = await conn.execute(
            text(
                "UPDATE settings SET value = 'auto' "
                "WHERE key = 'default_policy' "
                "AND value IN ('patch-only', 'minor-and-patch', 'security')"
            )
        )
        if result.rowcount:
            print("  Updated default_policy setting to 'auto'")

        result = await conn.execute(
            text(
                "UPDATE settings SET value = 'monitor' "
                "WHERE key = 'default_policy' AND value = 'manual'"
            )
        )
        if result.rowcount:
            print("  Updated default_policy setting to 'monitor'")


async def downgrade():
    """Revert policy values (monitor → manual). Other values cannot be restored."""
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE containers SET policy = 'manual' WHERE policy = 'monitor'"))
        await conn.execute(
            text(
                "UPDATE settings SET value = 'manual' "
                "WHERE key = 'default_policy' AND value = 'monitor'"
            )
        )
        print("  Reverted 'monitor' → 'manual' (other values cannot be restored)")
