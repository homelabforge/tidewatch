#!/usr/bin/env python3
"""Migration: Add is_my_project field for My Projects feature.

This migration adds:
1. is_my_project boolean column to containers table
2. Index on is_my_project for faster filtering

Created: 2025-11-21
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db import engine


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    return any(col[1] == column_name for col in columns)


async def upgrade():
    """Apply migration: Add is_my_project field."""
    async with engine.begin() as conn:
        print("Adding is_my_project field to containers table...")

        # Add is_my_project column with default False
        if not await column_exists(conn, "containers", "is_my_project"):
            await conn.execute(
                text("""
                ALTER TABLE containers
                ADD COLUMN is_my_project BOOLEAN NOT NULL DEFAULT 0
            """)
            )
            print("✓ Added is_my_project column")
        else:
            print("⏭️  Skipped is_my_project column (already exists)")

        # Create index for faster filtering
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_containers_is_my_project
            ON containers(is_my_project)
        """)
        )
        print("✓ Created index ix_containers_is_my_project")

        print("Migration completed successfully!")


async def downgrade():
    """Rollback migration: Remove is_my_project field."""
    async with engine.begin() as conn:
        print("Removing is_my_project field from containers table...")

        # Drop index
        await conn.execute(text("DROP INDEX IF EXISTS ix_containers_is_my_project"))
        print("✓ Dropped index ix_containers_is_my_project")

        # Drop column
        # Note: SQLite doesn't support DROP COLUMN directly, would need table recreation
        # For now, we'll just document this. In production, you'd need to:
        # 1. Create new table without the column
        # 2. Copy data
        # 3. Drop old table
        # 4. Rename new table
        print(
            "⚠ Note: SQLite doesn't support DROP COLUMN. Manual intervention required for full rollback."
        )

        print("Rollback completed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
