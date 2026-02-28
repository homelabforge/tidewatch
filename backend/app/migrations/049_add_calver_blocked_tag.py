"""Add calver_blocked_tag column to containers table.

Migration: 049
Description: Stores the best cross-scheme candidate rejected during the last check.
             UI equivalent of latest_major_tag, but for version-scheme mismatches.
             Only populated when a CalVer candidate is blocked for a SemVer container
             (is_curr_calver=False, is_cand_calver=True). Cleared each check run.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add calver_blocked_tag column to containers table."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "calver_blocked_tag" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN calver_blocked_tag TEXT NULL"))


async def downgrade(db) -> None:  # noqa: ARG001
    """Remove calver_blocked_tag column from containers table."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
