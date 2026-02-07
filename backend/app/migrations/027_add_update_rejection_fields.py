"""Add rejection tracking fields to updates table.

This migration adds:
- rejected_by: Who rejected the update
- rejected_at: When the update was rejected
- rejection_reason: Why the update was rejected

These fields allow tracking rejection history similar to approval tracking.
"""

from sqlalchemy import text


async def up(db):
    """Add rejection fields to updates table."""
    # Check if columns exist before adding (idempotent)
    result = await db.execute(text("PRAGMA table_info(updates)"))
    columns = {row[1] for row in result.fetchall()}

    if "rejected_by" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN rejected_by VARCHAR"))
    if "rejected_at" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN rejected_at DATETIME"))
    if "rejection_reason" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN rejection_reason TEXT"))
    # No explicit commit needed — runner's engine.begin() handles it


async def down(db):  # noqa: ARG001
    """Remove rejection fields from updates table."""
    # SQLite doesn't support DROP COLUMN directly, so we'd need to recreate the table
    # For now, just document this limitation
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
