"""Add ignored_version_prefix for pattern-based ignore matching.

Migration: 037
Date: 2025-01-30
Description:
    - Adds ignored_version_prefix column to dockerfile_dependencies table
    - Adds ignored_version_prefix column to http_servers table
    - Adds ignored_version_prefix column to app_dependencies table
    - Enables pattern-based ignore (e.g., ignoring "3.15" ignores all 3.15.x versions)
    - Auto-clear only triggers when major.minor version changes
"""

from sqlalchemy import text


async def up(db):
    """Add ignored_version_prefix columns for pattern-based ignore matching."""

    # ===================================================================
    # Part 1: Add ignored_version_prefix to dockerfile_dependencies
    # ===================================================================
    result = await db.execute(text("PRAGMA table_info(dockerfile_dependencies)"))
    columns = {row[1] for row in result.fetchall()}

    if "ignored_version_prefix" not in columns:
        await db.execute(
            text(
                "ALTER TABLE dockerfile_dependencies ADD COLUMN ignored_version_prefix VARCHAR(50)"
            )
        )

    # ===================================================================
    # Part 2: Add ignored_version_prefix to http_servers
    # ===================================================================
    result = await db.execute(text("PRAGMA table_info(http_servers)"))
    columns = {row[1] for row in result.fetchall()}

    if "ignored_version_prefix" not in columns:
        await db.execute(
            text(
                "ALTER TABLE http_servers ADD COLUMN ignored_version_prefix VARCHAR(50)"
            )
        )

    # ===================================================================
    # Part 3: Add ignored_version_prefix to app_dependencies
    # ===================================================================
    result = await db.execute(text("PRAGMA table_info(app_dependencies)"))
    columns = {row[1] for row in result.fetchall()}

    if "ignored_version_prefix" not in columns:
        await db.execute(
            text(
                "ALTER TABLE app_dependencies ADD COLUMN ignored_version_prefix VARCHAR(50)"
            )
        )

    await db.commit()


async def down(db):
    """Remove ignored_version_prefix columns (limited by SQLite)."""
    # SQLite doesn't support DROP COLUMN directly
    # These columns will remain but be unused if downgrade is performed
    await db.commit()
