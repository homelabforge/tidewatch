"""Add database indexes for frequently queried columns.

Migration: 019
Date: 2025-11-24
Description: Add indexes on frequently queried columns to improve query performance
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import engine


async def upgrade():
    """Add indexes on frequently queried columns."""
    async with engine.begin() as conn:
        # Container indexes
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_containers_policy ON containers(policy)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_containers_update_available ON containers(update_available)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_containers_name ON containers(name)")
        )

        # Update indexes
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_updates_status ON updates(status)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_updates_container_id ON updates(container_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_updates_created_at ON updates(created_at DESC)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_updates_snoozed_until ON updates(snoozed_until)"
            )
        )

        # UpdateHistory indexes
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_update_history_container_id ON update_history(container_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_update_history_status ON update_history(status)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_update_history_created_at ON update_history(created_at DESC)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_update_history_started_at ON update_history(started_at DESC)"
            )
        )


async def downgrade():
    """Remove indexes."""
    async with engine.begin() as conn:
        # Drop all indexes in reverse order
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_history_started_at"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_history_created_at"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_history_status"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_history_container_id"))

        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_snoozed_until"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_created_at"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_container_id"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_status"))

        await conn.execute(text("DROP INDEX IF EXISTS idx_containers_name"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_containers_update_available"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_containers_policy"))
