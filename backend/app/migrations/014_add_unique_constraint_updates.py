#!/usr/bin/env python3
"""Migration: Add unique constraint to updates table to prevent race conditions.

This migration adds:
1. A composite index for faster lookups
2. A unique constraint to prevent duplicate update records for the same container/version/status

Created: 2025-11-18
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database import engine


async def upgrade():
    """Apply migration: Add unique constraint for updates."""
    async with engine.begin() as conn:
        print("Adding composite index and unique constraint to updates table...")

        # Create composite index for faster lookups
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_update_lookup
            ON updates(container_id, from_tag, to_tag, status)
        """)
        )
        print("✓ Created composite index idx_update_lookup")

        # Check if constraint already exists
        result = await conn.execute(
            text("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='uq_active_update'
        """)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            # Clean up duplicates before creating unique constraint
            # Keep only the most recent duplicate (by id) for each combination
            print("Cleaning up duplicate update records...")
            await conn.execute(
                text("""
                DELETE FROM updates
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM updates
                    GROUP BY container_id, from_tag, to_tag, status
                )
            """)
            )

            result = await conn.execute(text("SELECT changes()"))
            deleted_count = result.scalar()
            if deleted_count > 0:
                print(f"✓ Removed {deleted_count} duplicate update record(s)")
            else:
                print("✓ No duplicate records found")

            # For SQLite, we'll create a unique index
            # This will prevent duplicates across all statuses, not just active ones
            # but that's acceptable for this use case
            await conn.execute(
                text("""
                CREATE UNIQUE INDEX uq_active_update
                ON updates(container_id, from_tag, to_tag, status)
            """)
            )
            print("✓ Created unique constraint uq_active_update")
        else:
            print("✓ Unique constraint already exists")

        print("Migration completed successfully!")


async def downgrade():
    """Rollback migration: Remove unique constraint."""
    async with engine.begin() as conn:
        print("Removing unique constraint and index from updates table...")

        # Drop unique index
        await conn.execute(text("DROP INDEX IF EXISTS uq_active_update"))
        print("✓ Dropped unique constraint uq_active_update")

        # Drop composite index
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_lookup"))
        print("✓ Dropped composite index idx_update_lookup")

        print("Rollback completed successfully!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
