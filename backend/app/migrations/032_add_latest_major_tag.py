"""Add latest_major_tag column to containers table.

Migration: 032
Date: 2025-12-25
Description: Add latest_major_tag column to track major version updates that exist
             outside the container's configured scope (patch/minor). This allows users
             to see major updates as informational indicators even when scope blocks them.
"""

from sqlalchemy import text


async def upgrade(db):
    """Add latest_major_tag column to containers table."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "latest_major_tag" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN latest_major_tag TEXT NULL"))

    # No explicit commit needed — runner's engine.begin() handles it


async def downgrade(db):  # noqa: ARG001
    """Remove latest_major_tag column from containers table."""
    # SQLite doesn't support DROP COLUMN directly in older versions
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
