"""Add data backup fields to update_history table.

Migration: 040
Date: 2026-02-06
Description: Add data_backup_id and data_backup_status columns to support
    pre-update volume/bind-mount backup tracking for full rollback.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Add data backup tracking columns to update_history."""
    async with engine.begin() as conn:
        # Check existing columns for idempotency
        result = await conn.execute(text("PRAGMA table_info(update_history)"))
        existing_columns = {row[1] for row in result.fetchall()}

        if "data_backup_id" not in existing_columns:
            await conn.execute(text("ALTER TABLE update_history ADD COLUMN data_backup_id VARCHAR"))
            print("  Added data_backup_id to update_history")
        else:
            print("  data_backup_id already exists, skipping")

        if "data_backup_status" not in existing_columns:
            await conn.execute(
                text("ALTER TABLE update_history ADD COLUMN data_backup_status VARCHAR")
            )
            print("  Added data_backup_status to update_history")
        else:
            print("  data_backup_status already exists, skipping")


async def downgrade():
    """SQLite does not support DROP COLUMN on older versions."""
    print("  Downgrade not supported (SQLite limitation)")
