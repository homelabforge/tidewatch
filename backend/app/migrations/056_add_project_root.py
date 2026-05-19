"""Add project_root column to containers table.

Migration: 056
Description: Adds a nullable project_root column that anchors My Project rows
             whose discovery does not depend on a compose file. Downstream
             scanners (dockerfile_parser, http_server_scanner, app_dependencies)
             resolve project paths via app.utils.project_resolver.resolve_project_root,
             which prefers project_root when set and falls back to
             Path(compose_file).parent otherwise.

             Backfill of project_root for legacy My Project rows happens at
             scanner runtime, not in this migration — keeps the migration
             trivially idempotent and avoids touching rows the scanner is
             about to re-evaluate anyway.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add project_root column to containers table."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "project_root" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN project_root VARCHAR(512) NULL"))


async def downgrade(db) -> None:  # noqa: ARG001
    """Remove project_root column from containers table."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
