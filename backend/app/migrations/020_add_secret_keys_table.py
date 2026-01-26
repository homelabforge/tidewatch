#!/usr/bin/env python3
"""Migration: Add secret_keys table for database-backed secret management.

This migration adds:
1. secret_keys table for two-tier key architecture
2. Indexes for performance optimization

Created: 2025-11-25
Version: 3.0.0
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import engine


async def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    )
    return result.scalar() is not None


async def upgrade():
    """Apply migration: Add secret_keys table for database-backed secret management."""
    async with engine.begin() as conn:
        print("Adding secret_keys table for database-backed secret management...")

        # Check if secret_keys table already exists
        if await table_exists(conn, "secret_keys"):
            print("⏭️  Skipped secret_keys table creation (already exists)")
            return

        # Create secret_keys table
        await conn.execute(
            text("""
            CREATE TABLE secret_keys (
                key_name VARCHAR PRIMARY KEY,
                key_value VARCHAR NOT NULL,
                key_type VARCHAR NOT NULL,
                encrypted BOOLEAN DEFAULT FALSE,
                rotated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        print("✓ Created secret_keys table")

        # Create index on key_name for faster lookups
        await conn.execute(
            text("""
            CREATE INDEX ix_secret_keys_name ON secret_keys(key_name)
        """)
        )
        print("✓ Created index on key_name")

        # Create index on key_type for filtering
        await conn.execute(
            text("""
            CREATE INDEX ix_secret_keys_type ON secret_keys(key_type)
        """)
        )
        print("✓ Created index on key_type")

        print("")
        print("Migration completed successfully!")


async def downgrade():
    """Rollback migration: Remove secret_keys table."""
    async with engine.begin() as conn:
        print("Removing secret_keys table...")

        # Drop secret_keys table (indexes will be dropped automatically)
        await conn.execute(text("DROP TABLE IF EXISTS secret_keys"))
        print("✓ Removed secret_keys table")

        print("Rollback completed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
