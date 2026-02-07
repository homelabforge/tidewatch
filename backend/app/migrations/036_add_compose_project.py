"""Add compose_project column to containers table.

Migration: 036
Date: 2026-01-24
Description: Add compose_project column to store the Docker Compose project name
             per container. This enables TideWatch to use explicit -p and -f flags
             when executing docker compose commands, fixing issues with containers
             in different compose projects (e.g., 'homelab' vs 'proxies').
"""

from sqlalchemy import text


async def up(db):
    """Add compose_project column to containers table."""
    # Check if column exists before adding (idempotent)
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "compose_project" not in columns:
        await db.execute(
            text("ALTER TABLE containers ADD COLUMN compose_project TEXT DEFAULT NULL")
        )

    # No explicit commit needed — runner's engine.begin() handles it


async def down(db):  # noqa: ARG001
    """Remove compose_project column from containers table."""
    # SQLite doesn't support DROP COLUMN directly in older versions
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
