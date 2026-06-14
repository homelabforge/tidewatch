"""Add vuln_scanned_at column to containers table.

Migration: 063
Description: Adds a nullable vuln_scanned_at timestamp recording the last time
             VulnForge returned a vulnerability match for a container's image.
             NULL means "never scanned" — the UI renders that as "Not scanned"
             instead of a falsely-reassuring "No known vulnerabilities".

             current_vuln_count alone could not distinguish never-scanned
             (model default 0) from genuinely clean (also 0). My Projects,
             whose local/empty image refs never match a VulnForge-scanned
             image, were permanently stuck on the misleading "0 = clean"
             reading.

             No backfill: existing rows get NULL and are stamped on the next
             successful VulnForge baseline refresh (runs on every update check
             for vulnforge-enabled containers). Forward-only.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add vuln_scanned_at column to containers table (idempotent)."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "vuln_scanned_at" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN vuln_scanned_at DATETIME"))


async def downgrade(db) -> None:  # noqa: ARG001
    """Remove vuln_scanned_at column from containers table."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
