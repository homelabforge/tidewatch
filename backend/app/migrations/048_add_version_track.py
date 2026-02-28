"""Add version_track column to containers table.

Migration: 048
Description: Per-container versioning scheme override.
  NULL=auto-detect (default), 'semver'=force SemVer, 'calver'=force CalVer.
  Allows operators to explicitly lock a container to a versioning scheme,
  overriding structural CalVer auto-detection. Primary use case: migrating
  a container from SemVer to CalVer (e.g., project changes release format).
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add version_track column to containers table."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "version_track" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN version_track TEXT NULL"))


async def downgrade(db) -> None:  # noqa: ARG001
    """Remove version_track column from containers table."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
