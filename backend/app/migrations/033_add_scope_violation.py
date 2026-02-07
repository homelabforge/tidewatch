"""Add scope_violation column to updates table.

Migration: 033
Date: 2025-12-25
Description: Add scope_violation column to track major version updates that are
             blocked by container scope settings. This allows these updates to
             appear in history with special indicators and "Apply Anyway" actions.
"""

from sqlalchemy import text


async def upgrade(db):
    """Add scope_violation column to updates table."""
    result = await db.execute(text("PRAGMA table_info(updates)"))
    columns = {row[1] for row in result.fetchall()}

    if "scope_violation" not in columns:
        await db.execute(
            text("ALTER TABLE updates ADD COLUMN scope_violation INTEGER DEFAULT 0 NOT NULL")
        )

    # No explicit commit needed — runner's engine.begin() handles it


async def downgrade(db):  # noqa: ARG001
    """Remove scope_violation column from updates table."""
    # SQLite doesn't support DROP COLUMN directly in older versions
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
