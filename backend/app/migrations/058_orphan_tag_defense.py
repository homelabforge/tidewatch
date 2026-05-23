"""Phase 2/6 orphan-tag defense — per-container opt-out + audit flag.

Migration: 058
Description: Adds two nullable boolean columns to ``containers``:

  * ``latest_lineage_cap_disabled`` (Phase 2 / D10): default False. When
    False (the default), the :latest lineage cap is enforced — any candidate
    whose major exceeds :latest's major is rejected. Power users with
    intentional cross-major pins (e.g. bookworm -> trixie when :latest is
    :trixie) flip this to True.
  * ``require_approval_for_major_change`` (Phase 6 / D14): default True.
    When True, any major bump (regardless of scope policy) is held for
    manual approval. Belt-and-suspenders against the lidarr-class incident
    where scope=major + auto_update=on let a corrupt jump through.

Both columns are nullable to preserve backward compat with rows that pre-date
this migration; application code reads them with explicit defaults.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add latest_lineage_cap_disabled and require_approval_for_major_change."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "latest_lineage_cap_disabled" not in columns:
        await db.execute(
            text("ALTER TABLE containers ADD COLUMN latest_lineage_cap_disabled BOOLEAN DEFAULT 0")
        )
    if "require_approval_for_major_change" not in columns:
        await db.execute(
            text(
                "ALTER TABLE containers "
                "ADD COLUMN require_approval_for_major_change BOOLEAN DEFAULT 1"
            )
        )


async def downgrade(db) -> None:  # noqa: ARG001
    """Downgrade not supported for SQLite ALTER TABLE ADD COLUMN."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
