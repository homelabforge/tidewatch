#!/usr/bin/env python3
"""Migration: Add theme setting for light/dark mode.

This migration adds:
1. Default 'theme' setting to settings table with value 'dark'

Created: 2025-11-24
Version: 2.9.0
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db import engine


async def setting_exists(conn, key: str) -> bool:
    """Check if a setting exists in the settings table."""
    result = await conn.execute(
        text("SELECT COUNT(*) FROM settings WHERE key = :key"),
        {"key": key}
    )
    count = result.scalar()
    return count > 0


async def upgrade():
    """Apply migration: Add theme setting."""
    async with engine.begin() as conn:
        print("Adding theme setting...")

        # Add theme setting if it doesn't exist
        if not await setting_exists(conn, "theme"):
            await conn.execute(text("""
                INSERT INTO settings (key, value, category, description, encrypted)
                VALUES (
                    'theme',
                    'dark',
                    'general',
                    'User interface theme (light or dark)',
                    0
                )
            """))
            print("✓ Added theme setting with default value 'dark'")
        else:
            print("⏭️  Skipped theme setting (already exists)")

        print("Migration completed successfully!")


async def downgrade():
    """Rollback migration: Remove theme setting."""
    async with engine.begin() as conn:
        print("Removing theme setting...")

        # Delete theme setting
        await conn.execute(text("DELETE FROM settings WHERE key = 'theme'"))
        print("✓ Removed theme setting")

        print("Rollback completed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
